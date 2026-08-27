"""Request authentication and authorisation.

Two independent checks guard every client-scoped route:

* ROLE  - what the user is allowed to do (director: read; secretary: upload and
          run; admin: administer).
* MEMBERSHIP - which client boards they may touch at all.

Both are required. An admin without a membership row for a client cannot read
that client's packs, which is what keeps per-client segregation true even for
privileged accounts.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..db import query, query_one
from ..security import decode_token

_bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {"director": 0, "secretary": 1, "admin": 2}


@dataclass
class CurrentUser:
    id: str
    email: str
    role: str
    client_ids: list[str]

    def may(self, minimum_role: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK[minimum_role]


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired.") from None
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session token.") from None

    # Memberships are re-read from the database rather than trusted from the
    # token, so revoking access takes effect immediately instead of at token
    # expiry.
    rows = query("SELECT client_id FROM user_clients WHERE user_id = ?", (payload["sub"],))
    user = query_one("SELECT id, email, role FROM users WHERE id = ?", (payload["sub"],))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account no longer exists.")

    return CurrentUser(
        id=user["id"],
        email=user["email"],
        role=user["role"],
        client_ids=[r["client_id"] for r in rows],
    )


def require_role(minimum_role: str):
    def guard(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not user.may(minimum_role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action requires the {minimum_role} role.",
            )
        return user

    return guard


def assert_client_access(user: CurrentUser, client_id: str) -> None:
    if client_id not in user.client_ids:
        # 404 rather than 403: confirming that a client board exists is itself
        # a disclosure across the segregation boundary.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client board not found.")


def client_for_pack(user: CurrentUser, pack_id: str) -> str:
    row = query_one("SELECT client_id FROM packs WHERE id = ?", (pack_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board pack not found.")
    assert_client_access(user, row["client_id"])
    return row["client_id"]


def client_for_briefing(user: CurrentUser, briefing_id: str) -> str:
    row = query_one("SELECT client_id FROM briefings WHERE id = ?", (briefing_id,))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Briefing not found.")
    assert_client_access(user, row["client_id"])
    return row["client_id"]
