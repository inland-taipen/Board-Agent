"""Application services: ingestion, indexing, briefing runs and exports.

The API layer stays thin - it authenticates, authorises and validates, then
calls into here. Everything in this module takes an explicit `client_id` and
scopes its queries by it; there is no ambient "current client".
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .actions import tracker
from .brief import DocumentInput, generate_briefing
from .config import get_settings
from .db import audit, execute, new_id, now, query, query_one, transaction
from .export import BriefingDocument, render_docx, render_pdf
from .ingest import Segment, UnsupportedFormat, classify, parse_file
from .rag import PackIndex, chunk_segments
from .security import (
    blob_path_for,
    decrypt_blob,
    encrypt_blob,
    safe_filename,
    sha256,
)

log = logging.getLogger(__name__)


class ServiceError(RuntimeError):
    """Raised for conditions the API should report as a 4xx."""


# --- Packs -------------------------------------------------------------------


def create_pack(
    *,
    client_id: str,
    meeting_label: str,
    meeting_date: str,
    classification: str,
    user_id: str,
) -> str:
    pack_id = new_id("pack")
    execute(
        """
        INSERT INTO packs (id, client_id, meeting_label, meeting_date, classification,
                           status, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            pack_id,
            client_id,
            meeting_label,
            meeting_date or datetime.now(UTC).date().isoformat(),
            classification,
            "draft",
            user_id,
            now(),
        ),
    )
    audit("pack.create", user_id=user_id, client_id=client_id, detail={"pack_id": pack_id})
    return pack_id


def set_pack_status(pack_id: str, status: str, *, progress: str = "", error: str = "") -> None:
    execute(
        "UPDATE packs SET status = ?, progress = ?, error = ? WHERE id = ?",
        (status, progress, error, pack_id),
    )


def set_progress(pack_id: str, message: str) -> None:
    execute("UPDATE packs SET progress = ? WHERE id = ?", (message, pack_id))


# --- Documents ---------------------------------------------------------------


def add_document(
    *,
    client_id: str,
    pack_id: str,
    filename: str,
    data: bytes,
    doc_kind: str | None,
    classification: str,
    user_id: str,
) -> dict:
    """Store, parse and cache one uploaded document.

    Parsing happens at upload so the operator learns immediately that a file is
    a scan or is unreadable - discovering that at briefing time, after the pack
    has been assembled, wastes a meeting cycle.
    """
    settings = get_settings()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ServiceError(
            f"{filename} exceeds the {settings.max_upload_mb} MB upload limit."
        )

    clean_name = safe_filename(filename)
    document_id = new_id("doc")
    suffix = Path(clean_name).suffix.lower()

    blob_path = blob_path_for(client_id, document_id, suffix)
    encrypt_blob(data, blob_path)

    # Parse from a plaintext temp copy under the same per-client directory, and
    # remove it immediately - parsers need a real path on disk.
    scratch = blob_path.with_suffix(".scratch" + suffix)
    try:
        scratch.write_bytes(data)
        scratch.chmod(0o600)
        try:
            segments = parse_file(scratch)
        except UnsupportedFormat as exc:
            blob_path.unlink(missing_ok=True)
            raise ServiceError(str(exc)) from exc
        except Exception as exc:  # parser failures must not 500
            blob_path.unlink(missing_ok=True)
            raise ServiceError(f"{clean_name} could not be parsed: {exc}") from exc
    finally:
        scratch.unlink(missing_ok=True)

    sample = "\n".join(s.text for s in segments[:6])
    kind = doc_kind or classify(clean_name, sample)

    ocr_pages = sorted(
        {s.page for s in segments if s.meta.get("needs_ocr") or s.meta.get("empty")}
    )
    pages = max((s.page for s in segments), default=0)

    _cache_segments(client_id, document_id, segments)

    execute(
        """
        INSERT INTO documents (id, pack_id, client_id, filename, doc_kind, classification,
                               blob_path, sha256, size_bytes, pages, chunk_count,
                               ocr_pages, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            document_id,
            pack_id,
            client_id,
            clean_name,
            str(kind),
            classification,
            str(blob_path),
            sha256(data),
            len(data),
            pages,
            0,
            json.dumps(ocr_pages),
            now(),
        ),
    )
    audit(
        "document.upload",
        user_id=user_id,
        client_id=client_id,
        detail={"pack_id": pack_id, "document_id": document_id, "filename": clean_name},
    )

    return {
        "id": document_id,
        "filename": clean_name,
        "doc_kind": str(kind),
        "pages": pages,
        "segments": len(segments),
        "unreadable_pages": ocr_pages,
        "size_bytes": len(data),
    }


def delete_document(client_id: str, document_id: str, *, user_id: str) -> None:
    row = query_one(
        "SELECT blob_path FROM documents WHERE id = ? AND client_id = ?",
        (document_id, client_id),
    )
    if row is None:
        raise ServiceError("Document not found.")
    Path(row["blob_path"]).unlink(missing_ok=True)
    _segments_path(client_id, document_id).unlink(missing_ok=True)
    execute(
        "DELETE FROM documents WHERE id = ? AND client_id = ?", (document_id, client_id)
    )
    audit(
        "document.delete",
        user_id=user_id,
        client_id=client_id,
        detail={"document_id": document_id},
    )


def _segments_path(client_id: str, document_id: str) -> Path:
    return get_settings().blob_dir / client_id / f"{document_id}.segments.json.enc"


def _cache_segments(client_id: str, document_id: str, segments: list[Segment]) -> None:
    payload = json.dumps([asdict(s) for s in segments]).encode()
    encrypt_blob(payload, _segments_path(client_id, document_id))


def _load_segments(client_id: str, document_id: str) -> list[Segment]:
    path = _segments_path(client_id, document_id)
    if not path.exists():
        raise ServiceError(
            f"Parsed content for document {document_id} is missing. Re-upload the file."
        )
    return [Segment(**item) for item in json.loads(decrypt_blob(path))]


# --- Indexing ----------------------------------------------------------------


def build_index(client_id: str, pack_id: str) -> tuple[PackIndex, list[DocumentInput]]:
    """Chunk every document in the pack and build its retrieval index.

    Chunk IDs are numbered continuously across the whole pack so a single ID
    identifies one passage unambiguously in the briefing.
    """
    settings = get_settings()
    rows = query(
        "SELECT * FROM documents WHERE pack_id = ? AND client_id = ? ORDER BY created_at",
        (pack_id, client_id),
    )
    if not rows:
        raise ServiceError("This pack has no documents. Upload the board pack first.")

    inputs: list[DocumentInput] = []
    all_chunks = []
    counter = 0

    for row in rows:
        segments = _load_segments(client_id, row["id"])
        chunks = chunk_segments(
            segments,
            doc_id=row["id"],
            doc_name=row["filename"],
            doc_kind=row["doc_kind"],
            start_index=counter,
            target_tokens=settings.chunk_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
        counter += len(chunks)
        all_chunks.extend(chunks)

        execute(
            "UPDATE documents SET chunk_count = ? WHERE id = ?", (len(chunks), row["id"])
        )
        inputs.append(
            DocumentInput(
                doc_id=row["id"],
                name=row["filename"],
                kind=row["doc_kind"],
                chunks=chunks,
                ocr_pages=json.loads(row["ocr_pages"] or "[]"),
            )
        )

    index = PackIndex(
        all_chunks,
        dense_model=settings.dense_model if settings.dense_retrieval else None,
    ).build()
    index.save(settings.index_dir / client_id / pack_id)
    return index, inputs


def load_index(client_id: str, pack_id: str) -> PackIndex:
    directory = get_settings().index_dir / client_id / pack_id
    if not (directory / "index.json").exists():
        raise ServiceError("No index exists for this pack. Generate the briefing first.")
    return PackIndex.load(directory)


# --- Briefing run ------------------------------------------------------------


def run_briefing(*, client_id: str, pack_id: str, user_id: str) -> str:
    """Full pipeline for one pack. Long-running; call from a background task."""
    pack = query_one(
        "SELECT * FROM packs WHERE id = ? AND client_id = ?", (pack_id, client_id)
    )
    if pack is None:
        raise ServiceError("Pack not found.")

    client = query_one("SELECT name FROM clients WHERE id = ?", (client_id,))
    company = client["name"] if client else "the company"

    set_pack_status(pack_id, "processing", progress="Preparing the board pack")

    try:
        index, documents = build_index(client_id, pack_id)
        set_progress(pack_id, f"Indexed {len(index.chunks)} passages")

        result = generate_briefing(
            client_id=client_id,
            pack_id=pack_id,
            company=company,
            meeting_label=pack["meeting_label"],
            documents=documents,
            index=index,
            user_id=user_id,
            progress=lambda msg: set_progress(pack_id, msg),
        )

        briefing_id = new_id("brf")
        execute(
            """
            INSERT INTO briefings (id, pack_id, client_id, content, verification, model, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                briefing_id,
                pack_id,
                client_id,
                result.briefing.model_dump_json(),
                json.dumps(result.verification.to_dict()),
                get_settings().model,
                now(),
            ),
        )
        set_pack_status(pack_id, "ready", progress="Briefing ready for review")
        audit(
            "briefing.generate",
            user_id=user_id,
            client_id=client_id,
            detail={
                "pack_id": pack_id,
                "briefing_id": briefing_id,
                "grounding_rate": result.verification.grounding_rate,
                "issues": len(result.verification.issues),
                "actions_created": result.actions_created,
                "actions_reconciled": result.actions_reconciled,
            },
        )
        return briefing_id

    except Exception as exc:  # surfaced to the operator, then re-raised
        log.exception("briefing run failed for pack %s", pack_id)
        set_pack_status(pack_id, "failed", error=str(exc))
        audit(
            "briefing.failed",
            user_id=user_id,
            client_id=client_id,
            detail={"pack_id": pack_id, "error": str(exc)},
        )
        raise


# --- Retrieval for the review UI ---------------------------------------------


def get_briefing(client_id: str, briefing_id: str) -> dict:
    row = query_one(
        "SELECT * FROM briefings WHERE id = ? AND client_id = ?", (briefing_id, client_id)
    )
    if row is None:
        raise ServiceError("Briefing not found.")

    pack = query_one("SELECT * FROM packs WHERE id = ?", (row["pack_id"],))
    client = query_one("SELECT name FROM clients WHERE id = ?", (client_id,))

    return {
        "id": row["id"],
        "pack_id": row["pack_id"],
        "company": client["name"] if client else "",
        "meeting_label": pack["meeting_label"] if pack else "",
        "meeting_date": pack["meeting_date"] if pack else "",
        "classification": pack["classification"] if pack else "confidential",
        "model": row["model"],
        "created_at": row["created_at"],
        "content": json.loads(row["content"]),
        "verification": json.loads(row["verification"] or "{}"),
    }


def latest_briefing_for_pack(client_id: str, pack_id: str) -> dict | None:
    row = query_one(
        """
        SELECT id FROM briefings WHERE pack_id = ? AND client_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (pack_id, client_id),
    )
    return get_briefing(client_id, row["id"]) if row else None


def source_passage(client_id: str, pack_id: str, chunk_id: str) -> dict:
    """Full text of one cited passage - the audit trail the BRD requires."""
    index = load_index(client_id, pack_id)
    chunk = index.get(chunk_id)
    if chunk is None:
        raise ServiceError(f"'{chunk_id}' is not a passage in this pack.")
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.doc_id,
        "document": chunk.doc_name,
        "document_kind": chunk.doc_kind,
        "page": chunk.page,
        "locator": chunk.locator,
        "heading": chunk.heading,
        "text": chunk.text,
    }


# --- Exports -----------------------------------------------------------------


def export_briefing(client_id: str, briefing_id: str, fmt: str, *, user_id: str) -> Path:
    if fmt not in ("docx", "pdf"):
        raise ServiceError("Format must be 'docx' or 'pdf'.")

    record = get_briefing(client_id, briefing_id)
    document = BriefingDocument(
        company=record["company"],
        meeting_label=record["meeting_label"],
        meeting_date=record["meeting_date"],
        classification=record["classification"],
        generated_at=record["created_at"],
        model=record["model"],
        briefing=record["content"],
        citation_map=record["verification"].get("citation_map", {}),
        verification=record["verification"],
        action_register=[a.to_dict() for a in tracker.register(client_id)],
    )

    slug = "".join(
        c if c.isalnum() else "-" for c in f"{record['company']}-{record['meeting_label']}"
    ).strip("-")[:80]
    destination = get_settings().export_dir / client_id / f"{slug}-{briefing_id}.{fmt}"

    if fmt == "docx":
        render_docx(document, destination)
    else:
        render_pdf(document, destination)

    audit(
        "briefing.export",
        user_id=user_id,
        client_id=client_id,
        detail={"briefing_id": briefing_id, "format": fmt},
    )
    return destination


# --- Bootstrap ---------------------------------------------------------------


def ensure_bootstrap_admin() -> None:
    """Create the initial administrator on an empty database."""
    from .security import hash_password

    settings = get_settings()
    if query_one("SELECT id FROM users LIMIT 1") is not None:
        return

    user_id = new_id("usr")
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, role, display_name, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                user_id,
                settings.bootstrap_email.lower(),
                hash_password(settings.bootstrap_password),
                "admin",
                "Administrator",
                now(),
            ),
        )
    log.warning(
        "Created bootstrap administrator %s. Change this password before any client "
        "board pack is uploaded.",
        settings.bootstrap_email,
    )
