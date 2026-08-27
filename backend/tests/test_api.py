"""API tests, concentrated on segregation and role enforcement.

Per-client segregation with no commingling is a hard BRD requirement and the
one a client's information-security review will probe first, so it is tested
from the outside, through HTTP, rather than at the service layer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boardlens.config import get_settings
from boardlens.db import execute, init_db, new_id, now
from boardlens.security import hash_password


@pytest.fixture
def client():
    from boardlens.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def _user(email: str, role: str, client_ids: list[str], password: str = "pw-123456") -> str:
    user_id = new_id("usr")
    execute(
        """
        INSERT INTO users (id, email, password_hash, role, display_name, created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (user_id, email, hash_password(password), role, email, now()),
    )
    for client_id in client_ids:
        execute(
            "INSERT INTO user_clients (user_id, client_id) VALUES (?,?)", (user_id, client_id)
        )
    return user_id


def _board(name: str) -> str:
    client_id = new_id("cli")
    execute(
        "INSERT INTO clients (id, name, created_at) VALUES (?,?,?)", (client_id, name, now())
    )
    return client_id


def _token(client: TestClient, email: str, password: str = "pw-123456") -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_needs_no_authentication(client):
    assert client.get("/health").json()["status"] == "ok"


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/clients").status_code == 401


def test_login_does_not_reveal_whether_an_account_exists(client):
    init_db()
    _user("director@meridian.example.com", "director", [])

    unknown = client.post(
        "/api/auth/login", json={"email": "nobody@nowhere.example.com", "password": "x"}
    )
    wrong = client.post(
        "/api/auth/login", json={"email": "director@meridian.example.com", "password": "wrong"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_a_user_sees_only_their_own_boards(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    northwind = _board("Northwind Chemicals Limited")
    _user("secretary@meridian.example.com", "secretary", [meridian])

    token = _token(client, "secretary@meridian.example.com")
    boards = client.get("/api/clients", headers=_auth(token)).json()

    assert [b["id"] for b in boards] == [meridian]
    assert northwind not in [b["id"] for b in boards]


def test_cross_client_pack_access_returns_not_found(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    northwind = _board("Northwind Chemicals Limited")
    _user("sec.meridian@example.com", "secretary", [meridian])
    _user("sec.northwind@example.com", "secretary", [northwind])

    northwind_token = _token(client, "sec.northwind@example.com")
    created = client.post(
        f"/api/clients/{northwind}/packs",
        json={"meeting_label": "Q1 FY27", "meeting_date": "2026-08-21"},
        headers=_auth(northwind_token),
    )
    assert created.status_code == 201
    pack_id = created.json()["id"]

    # Meridian's secretary must not be able to confirm the pack even exists.
    meridian_token = _token(client, "sec.meridian@example.com")
    assert client.get(f"/api/packs/{pack_id}", headers=_auth(meridian_token)).status_code == 404
    assert (
        client.get(f"/api/clients/{northwind}/packs", headers=_auth(meridian_token)).status_code
        == 404
    )


def test_directors_may_read_but_not_upload_or_generate(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("director@meridian.example.com", "director", [meridian])
    _user("secretary@meridian.example.com", "secretary", [meridian])

    director = _token(client, "director@meridian.example.com")
    secretary = _token(client, "secretary@meridian.example.com")

    # A director can list packs...
    assert client.get(f"/api/clients/{meridian}/packs", headers=_auth(director)).status_code == 200

    # ...but cannot create one.
    forbidden = client.post(
        f"/api/clients/{meridian}/packs",
        json={"meeting_label": "Q1 FY27"},
        headers=_auth(director),
    )
    assert forbidden.status_code == 403

    pack_id = client.post(
        f"/api/clients/{meridian}/packs",
        json={"meeting_label": "Q1 FY27"},
        headers=_auth(secretary),
    ).json()["id"]

    assert (
        client.post(f"/api/packs/{pack_id}/briefing", headers=_auth(director)).status_code == 403
    )


def test_only_admins_create_boards(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("secretary@meridian.example.com", "secretary", [meridian])
    _user("admin@meridian.example.com", "admin", [meridian])

    secretary = _token(client, "secretary@meridian.example.com")
    admin = _token(client, "admin@meridian.example.com")

    assert client.post("/api/clients", json={"name": "New Board"}, headers=_auth(secretary)).status_code == 403
    assert client.post("/api/clients", json={"name": "New Board"}, headers=_auth(admin)).status_code == 201


def test_upload_indexes_the_pack_and_reports_document_kinds(client, sample_pack):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("secretary@meridian.example.com", "secretary", [meridian])
    token = _token(client, "secretary@meridian.example.com")

    pack_id = client.post(
        f"/api/clients/{meridian}/packs",
        json={"meeting_label": "119th Board Meeting", "classification": "strictly_confidential"},
        headers=_auth(token),
    ).json()["id"]

    files = [
        ("files", (path.name, path.read_bytes(), "application/octet-stream"))
        for path in sorted(sample_pack.iterdir())
    ]
    response = client.post(f"/api/packs/{pack_id}/documents", files=files, headers=_auth(token))

    assert response.status_code == 201, response.text
    accepted = response.json()["accepted"]
    assert len(accepted) == 4
    assert response.json()["rejected"] == []

    kinds = {a["doc_kind"] for a in accepted}
    assert {"prior_minutes", "board_deck", "financial_pack"} <= kinds

    pack = client.get(f"/api/packs/{pack_id}", headers=_auth(token)).json()
    assert len(pack["documents"]) == 4
    assert pack["classification"] == "strictly_confidential"


def test_unsupported_formats_are_rejected_with_a_reason(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("secretary@meridian.example.com", "secretary", [meridian])
    token = _token(client, "secretary@meridian.example.com")

    pack_id = client.post(
        f"/api/clients/{meridian}/packs",
        json={"meeting_label": "119th"},
        headers=_auth(token),
    ).json()["id"]

    response = client.post(
        f"/api/packs/{pack_id}/documents",
        files=[("files", ("notes.txt", b"not a board pack", "text/plain"))],
        headers=_auth(token),
    )

    assert response.status_code == 400
    assert "not supported" in str(response.json()["detail"]).lower()


def test_briefing_cannot_start_without_documents(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("secretary@meridian.example.com", "secretary", [meridian])
    token = _token(client, "secretary@meridian.example.com")

    pack_id = client.post(
        f"/api/clients/{meridian}/packs", json={"meeting_label": "119th"}, headers=_auth(token)
    ).json()["id"]

    response = client.post(f"/api/packs/{pack_id}/briefing", headers=_auth(token))
    assert response.status_code == 400
    assert "Upload the board pack" in response.json()["detail"]


def test_meta_reports_supported_formats_and_the_active_provider(monkeypatch):
    from boardlens.main import create_app

    monkeypatch.setenv("BOARDLENS_PROVIDER", "gemini")
    monkeypatch.setenv("BOARDLENS_GEMINI_MODEL", "gemini-3.1-pro-preview")
    get_settings.cache_clear()

    with TestClient(create_app()) as test_client:
        meta = test_client.get("/api/meta").json()

    assert set(meta["supported_extensions"]) >= {".pdf", ".docx", ".pptx", ".xlsx"}
    # Which model wrote a briefing is a governance question, so the interface
    # must be able to state it rather than infer it.
    assert meta["provider"] == "gemini"
    assert meta["provider_pinned"] is True
    assert meta["model"] == "gemini-3.1-pro-preview"


def test_meta_reports_no_provider_when_no_key_is_present(monkeypatch):
    from boardlens.main import create_app

    monkeypatch.setenv("BOARDLENS_PROVIDER", "auto")
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY",
                "GOOGLE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    with TestClient(create_app()) as test_client:
        meta = test_client.get("/api/meta").json()

    assert meta["provider"] is None
    assert meta["model"] is None


def test_only_admins_can_enumerate_or_change_membership(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("admin@meridian.example.com", "admin", [meridian])
    _user("secretary@meridian.example.com", "secretary", [meridian])
    _user("director@meridian.example.com", "director", [meridian])

    admin = _token(client, "admin@meridian.example.com")
    secretary = _token(client, "secretary@meridian.example.com")

    # The membership list is the segregation boundary made visible; a secretary
    # has no business enumerating the directors' accounts.
    assert client.get(f"/api/clients/{meridian}/members", headers=_auth(secretary)).status_code == 403

    listed = client.get(f"/api/clients/{meridian}/members", headers=_auth(admin))
    assert listed.status_code == 200
    assert {m["email"] for m in listed.json()} == {
        "admin@meridian.example.com",
        "secretary@meridian.example.com",
        "director@meridian.example.com",
    }


def test_adding_a_member_creates_a_usable_login(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("admin@meridian.example.com", "admin", [meridian])
    admin = _token(client, "admin@meridian.example.com")

    created = client.post(
        f"/api/clients/{meridian}/members",
        json={
            "email": "new.director@example.com",
            "role": "director",
            "display_name": "A. Desai",
            "password": "a-long-enough-password",
        },
        headers=_auth(admin),
    )
    assert created.status_code == 201

    # The new account must actually be able to sign in and see the board.
    token = _token(client, "new.director@example.com", "a-long-enough-password")
    boards = client.get("/api/clients", headers=_auth(token)).json()
    assert [b["id"] for b in boards] == [meridian]


def test_a_new_member_cannot_see_other_boards(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    northwind = _board("Northwind Chemicals Limited")
    _user("admin@meridian.example.com", "admin", [meridian, northwind])
    admin = _token(client, "admin@meridian.example.com")

    client.post(
        f"/api/clients/{meridian}/members",
        json={
            "email": "scoped@example.com",
            "role": "director",
            "display_name": "Scoped",
            "password": "a-long-enough-password",
        },
        headers=_auth(admin),
    )

    token = _token(client, "scoped@example.com", "a-long-enough-password")
    assert [b["id"] for b in client.get("/api/clients", headers=_auth(token)).json()] == [meridian]
    assert client.get(f"/api/clients/{northwind}/packs", headers=_auth(token)).status_code == 404


def test_removing_a_member_revokes_access_immediately(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    _user("admin@meridian.example.com", "admin", [meridian])
    removed_id = _user("temp@meridian.example.com", "director", [meridian])

    admin = _token(client, "admin@meridian.example.com")
    victim = _token(client, "temp@meridian.example.com")

    assert client.get(f"/api/clients/{meridian}/packs", headers=_auth(victim)).status_code == 200

    assert (
        client.delete(
            f"/api/clients/{meridian}/members/{removed_id}", headers=_auth(admin)
        ).status_code
        == 204
    )

    # Memberships are re-read per request, so the still-valid token stops working
    # at once rather than at expiry.
    assert client.get(f"/api/clients/{meridian}/packs", headers=_auth(victim)).status_code == 404


def test_an_admin_cannot_lock_themselves_out(client):
    init_db()
    meridian = _board("Meridian Industries Limited")
    admin_id = _user("admin@meridian.example.com", "admin", [meridian])
    admin = _token(client, "admin@meridian.example.com")

    response = client.delete(
        f"/api/clients/{meridian}/members/{admin_id}", headers=_auth(admin)
    )
    assert response.status_code == 400
