"""HTTP surface.

Kept deliberately small - the web interface is used by company secretaries and
directors, not developers, so every endpoint maps to something a person does:
sign in, create a meeting, upload the pack, generate, review, export.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field

from .. import service
from ..actions import tracker
from ..config import get_settings
from ..db import audit, execute, new_id, now, query, query_one
from ..ingest import SUPPORTED_EXTENSIONS
from ..security import hash_password, issue_token, verify_password
from .deps import (
    CurrentUser,
    assert_client_access,
    client_for_briefing,
    client_for_pack,
    current_user,
    require_role,
)

router = APIRouter(prefix="/api")


def _service_error(exc: service.ServiceError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- Auth --------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    token: str
    email: str
    role: str
    display_name: str


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    user = query_one("SELECT * FROM users WHERE email = ?", (payload.email.lower(),))
    if user is None or not verify_password(payload.password, user["password_hash"]):
        # One message for both cases - do not reveal which addresses exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    client_ids = [
        r["client_id"]
        for r in query("SELECT client_id FROM user_clients WHERE user_id = ?", (user["id"],))
    ]
    audit("auth.login", user_id=user["id"], detail={"email": user["email"]})
    return TokenResponse(
        token=issue_token(
            user_id=user["id"], email=user["email"], role=user["role"], client_ids=client_ids
        ),
        email=user["email"],
        role=user["role"],
        display_name=user["display_name"] or user["email"],
    )


@router.get("/auth/me")
def me(user: CurrentUser = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role, "clients": user.client_ids}


# --- Clients -----------------------------------------------------------------


class ClientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)


@router.get("/clients")
def list_clients(user: CurrentUser = Depends(current_user)) -> list[dict]:
    if not user.client_ids:
        return []
    # Only the number of placeholders is interpolated; every value is bound.
    placeholders = ",".join("?" * len(user.client_ids))
    rows = query(
        f"SELECT id, name, created_at FROM clients WHERE id IN ({placeholders}) ORDER BY name",  # noqa: S608
        tuple(user.client_ids),
    )
    return [dict(r) for r in rows]


@router.post("/clients", status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate, user: CurrentUser = Depends(require_role("admin"))
) -> dict:
    if query_one("SELECT id FROM clients WHERE name = ?", (payload.name,)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A board with that name already exists.")

    client_id = new_id("cli")
    execute(
        "INSERT INTO clients (id, name, created_at) VALUES (?,?,?)",
        (client_id, payload.name, now()),
    )
    # The creating admin is granted membership; without it they could not see
    # the board they just created.
    execute(
        "INSERT INTO user_clients (user_id, client_id) VALUES (?,?)", (user.id, client_id)
    )
    audit("client.create", user_id=user.id, client_id=client_id, detail={"name": payload.name})
    return {"id": client_id, "name": payload.name}


class MembershipCreate(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|secretary|director)$")
    display_name: str = ""
    password: str | None = None


@router.get("/clients/{client_id}/members")
def list_members(client_id: str, user: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    """Who can reach this board.

    Admin-only: the membership list is the segregation boundary made visible,
    and a director has no business enumerating the other directors' accounts.
    """
    assert_client_access(user, client_id)
    rows = query(
        """
        SELECT u.id, u.email, u.role, u.display_name, u.created_at
          FROM users u
          JOIN user_clients uc ON uc.user_id = u.id
         WHERE uc.client_id = ?
         ORDER BY u.created_at
        """,
        (client_id,),
    )
    return [dict(r) for r in rows]


@router.delete(
    "/clients/{client_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_member(
    client_id: str, user_id: str, user: CurrentUser = Depends(require_role("admin"))
) -> None:
    """Revoke access to one board without deleting the account.

    Memberships are re-read on every request, so this takes effect on the
    revoked user's very next call rather than when their token expires.
    """
    assert_client_access(user, client_id)
    if user_id == user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "You cannot remove your own access to a board you administer.",
        )
    execute(
        "DELETE FROM user_clients WHERE user_id = ? AND client_id = ?", (user_id, client_id)
    )
    audit(
        "client.member_remove",
        user_id=user.id,
        client_id=client_id,
        detail={"removed_user_id": user_id},
    )


@router.post("/clients/{client_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    client_id: str,
    payload: MembershipCreate,
    user: CurrentUser = Depends(require_role("admin")),
) -> dict:
    assert_client_access(user, client_id)

    existing = query_one("SELECT * FROM users WHERE email = ?", (payload.email.lower(),))
    if existing is None:
        if not payload.password:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A password is required to create a new user account.",
            )
        user_id = new_id("usr")
        execute(
            """
            INSERT INTO users (id, email, password_hash, role, display_name, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                user_id,
                payload.email.lower(),
                hash_password(payload.password),
                payload.role,
                payload.display_name,
                now(),
            ),
        )
    else:
        user_id = existing["id"]

    execute(
        "INSERT OR IGNORE INTO user_clients (user_id, client_id) VALUES (?,?)",
        (user_id, client_id),
    )
    audit(
        "client.member_add",
        user_id=user.id,
        client_id=client_id,
        detail={"email": payload.email, "role": payload.role},
    )
    return {"user_id": user_id, "email": payload.email, "role": payload.role}


# --- Packs -------------------------------------------------------------------


class PackCreate(BaseModel):
    meeting_label: str = Field(min_length=2, max_length=160)
    meeting_date: str = ""
    classification: str = Field(
        default="confidential",
        pattern="^(public|internal|confidential|strictly_confidential)$",
    )


@router.post("/clients/{client_id}/packs", status_code=status.HTTP_201_CREATED)
def create_pack(
    client_id: str,
    payload: PackCreate,
    user: CurrentUser = Depends(require_role("secretary")),
) -> dict:
    assert_client_access(user, client_id)
    pack_id = service.create_pack(
        client_id=client_id,
        meeting_label=payload.meeting_label,
        meeting_date=payload.meeting_date or datetime.now(UTC).date().isoformat(),
        classification=payload.classification,
        user_id=user.id,
    )
    return {"id": pack_id}


@router.get("/clients/{client_id}/packs")
def list_packs(client_id: str, user: CurrentUser = Depends(current_user)) -> list[dict]:
    assert_client_access(user, client_id)
    rows = query(
        """
        SELECT p.*,
               (SELECT COUNT(*) FROM documents d WHERE d.pack_id = p.id) AS document_count,
               (SELECT b.id FROM briefings b WHERE b.pack_id = p.id
                 ORDER BY b.created_at DESC LIMIT 1) AS briefing_id
          FROM packs p
         WHERE p.client_id = ?
         ORDER BY p.created_at DESC
        """,
        (client_id,),
    )
    return [dict(r) for r in rows]


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    client_id = client_for_pack(user, pack_id)
    pack = dict(query_one("SELECT * FROM packs WHERE id = ?", (pack_id,)))
    documents = query(
        """
        SELECT id, filename, doc_kind, classification, pages, chunk_count, size_bytes,
               ocr_pages, created_at
          FROM documents WHERE pack_id = ? ORDER BY created_at
        """,
        (pack_id,),
    )
    pack["documents"] = [
        {**dict(d), "ocr_pages": json.loads(d["ocr_pages"] or "[]")} for d in documents
    ]
    briefing = service.latest_briefing_for_pack(client_id, pack_id)
    pack["briefing_id"] = briefing["id"] if briefing else None
    return pack


@router.post("/packs/{pack_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_documents(
    pack_id: str,
    files: list[UploadFile] = File(...),
    user: CurrentUser = Depends(require_role("secretary")),
) -> dict:
    client_id = client_for_pack(user, pack_id)
    pack = query_one("SELECT classification FROM packs WHERE id = ?", (pack_id,))

    accepted, rejected = [], []
    for upload in files:
        data = await upload.read()
        try:
            accepted.append(
                service.add_document(
                    client_id=client_id,
                    pack_id=pack_id,
                    filename=upload.filename or "document",
                    data=data,
                    doc_kind=None,
                    classification=pack["classification"],
                    user_id=user.id,
                )
            )
        except service.ServiceError as exc:
            rejected.append({"filename": upload.filename, "reason": str(exc)})

    if not accepted and rejected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"message": "No files could be accepted.", "rejected": rejected},
        )
    return {"accepted": accepted, "rejected": rejected}


class DocumentUpdate(BaseModel):
    doc_kind: str = Field(
        pattern="^(prior_minutes|board_deck|financial_pack|risk_report|"
        "internal_audit|business_update|other)$"
    )


@router.patch("/documents/{document_id}")
def update_document(
    document_id: str,
    payload: DocumentUpdate,
    user: CurrentUser = Depends(require_role("secretary")),
) -> dict:
    row = query_one("SELECT client_id FROM documents WHERE id = ?", (document_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    assert_client_access(user, row["client_id"])

    execute("UPDATE documents SET doc_kind = ? WHERE id = ?", (payload.doc_kind, document_id))
    audit(
        "document.reclassify",
        user_id=user.id,
        client_id=row["client_id"],
        detail={"document_id": document_id, "doc_kind": payload.doc_kind},
    )
    return {"id": document_id, "doc_kind": payload.doc_kind}


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str, user: CurrentUser = Depends(require_role("secretary"))
) -> None:
    row = query_one("SELECT client_id FROM documents WHERE id = ?", (document_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    assert_client_access(user, row["client_id"])
    try:
        service.delete_document(row["client_id"], document_id, user_id=user.id)
    except service.ServiceError as exc:
        raise _service_error(exc) from exc


# --- Briefing ----------------------------------------------------------------


@router.post("/packs/{pack_id}/briefing", status_code=status.HTTP_202_ACCEPTED)
def start_briefing(
    pack_id: str,
    background: BackgroundTasks,
    user: CurrentUser = Depends(require_role("secretary")),
) -> dict:
    client_id = client_for_pack(user, pack_id)
    pack = query_one("SELECT status FROM packs WHERE id = ?", (pack_id,))
    if pack["status"] == "processing":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A briefing is already being generated for this pack."
        )

    documents = query_one(
        "SELECT COUNT(*) AS n FROM documents WHERE pack_id = ?", (pack_id,)
    )
    if not documents["n"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Upload the board pack before generating a briefing."
        )

    service.set_pack_status(pack_id, "processing", progress="Queued")
    background.add_task(
        _run_briefing_task, client_id=client_id, pack_id=pack_id, user_id=user.id
    )
    return {"status": "processing", "pack_id": pack_id}


def _run_briefing_task(*, client_id: str, pack_id: str, user_id: str) -> None:
    """Background wrapper.

    `run_briefing` already records the failure on the pack row, so the error is
    swallowed here rather than escaping into the event loop where nothing would
    surface it to the operator.
    """
    with contextlib.suppress(Exception):
        service.run_briefing(client_id=client_id, pack_id=pack_id, user_id=user_id)


@router.get("/packs/{pack_id}/briefing")
def pack_briefing(pack_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    client_id = client_for_pack(user, pack_id)
    briefing = service.latest_briefing_for_pack(client_id, pack_id)
    if briefing is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No briefing has been generated for this pack yet."
        )
    audit(
        "briefing.view", user_id=user.id, client_id=client_id, detail={"pack_id": pack_id}
    )
    return briefing


@router.get("/briefings/{briefing_id}")
def get_briefing(briefing_id: str, user: CurrentUser = Depends(current_user)) -> dict:
    client_id = client_for_briefing(user, briefing_id)
    audit(
        "briefing.view",
        user_id=user.id,
        client_id=client_id,
        detail={"briefing_id": briefing_id},
    )
    return service.get_briefing(client_id, briefing_id)


@router.get("/briefings/{briefing_id}/export")
def export_briefing(
    briefing_id: str, format: str = "pdf", user: CurrentUser = Depends(current_user)
) -> FileResponse:
    client_id = client_for_briefing(user, briefing_id)
    try:
        path = service.export_briefing(client_id, briefing_id, format, user_id=user.id)
    except service.ServiceError as exc:
        raise _service_error(exc) from exc

    media_type = (
        "application/pdf"
        if format == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/packs/{pack_id}/source/{chunk_id}")
def source_passage(
    pack_id: str, chunk_id: str, user: CurrentUser = Depends(current_user)
) -> dict:
    """Open the exact passage behind a citation - the audit link in practice."""
    client_id = client_for_pack(user, pack_id)
    try:
        return service.source_passage(client_id, pack_id, chunk_id)
    except service.ServiceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# --- Action register ---------------------------------------------------------


@router.get("/clients/{client_id}/actions")
def list_actions(
    client_id: str,
    include_closed: bool = True,
    user: CurrentUser = Depends(current_user),
) -> list[dict]:
    assert_client_access(user, client_id)
    return [a.to_dict() for a in tracker.register(client_id, include_closed=include_closed)]


class ActionUpdate(BaseModel):
    status: str = Field(pattern="^(open|in_progress|completed|superseded|unclear)$")
    status_basis: str = ""


@router.patch("/clients/{client_id}/actions/{action_id}")
def update_action(
    client_id: str,
    action_id: str,
    payload: ActionUpdate,
    user: CurrentUser = Depends(require_role("secretary")),
) -> dict:
    assert_client_access(user, client_id)
    if not tracker.set_status(
        client_id, action_id, payload.status, payload.status_basis, user_id=user.id
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid status.")
    return {"id": action_id, "status": payload.status}


# --- Meta --------------------------------------------------------------------


@router.get("/meta")
def meta() -> dict:
    from ..providers import detect_provider, model_for

    settings = get_settings()
    configured = (settings.provider or "auto").strip().lower()
    active = configured if configured != "auto" else detect_provider()

    return {
        "supported_extensions": list(SUPPORTED_EXTENSIONS),
        "max_upload_mb": settings.max_upload_mb,
        "provider": active,
        "provider_pinned": configured != "auto",
        "model": model_for(active) if active else None,
        "dense_retrieval": settings.dense_retrieval,
    }
