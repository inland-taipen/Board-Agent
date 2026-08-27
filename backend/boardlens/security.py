"""Authentication, authorisation and encryption at rest.

Scope of what this module guarantees, so it is not over-read:

* Board packs are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).
  Plaintext exists only in memory during parsing and in the parsed index.
* Passwords are stored as PBKDF2-HMAC-SHA256 derivations, never recoverable.
* Sessions are short-lived signed JWTs carrying the user's role and client
  memberships.

Encryption *in transit* is a deployment concern - terminate TLS at the ingress
in front of this service. See docs/security.md.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_PBKDF2_ROUNDS = 600_000
_ALGO = "HS256"


# --- Passwords ---------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# --- Sessions ----------------------------------------------------------------


def issue_token(*, user_id: str, email: str, role: str, client_ids: list[str]) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "clients": client_ids,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGO])


# --- Encryption at rest ------------------------------------------------------


def _master_key() -> bytes:
    settings = get_settings()
    if settings.encryption_key:
        return settings.encryption_key.encode()

    # No key configured: generate one and persist it with restrictive
    # permissions so a laptop pilot is still encrypted. Production deployments
    # should supply BOARDLENS_ENCRYPTION_KEY from a secrets manager instead -
    # a key sitting beside the ciphertext protects against a stolen disk image,
    # not against a compromised host.
    key_path = settings.data_dir / ".master.key"
    if key_path.exists():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


def _fernet() -> Fernet:
    return Fernet(_master_key())


def encrypt_blob(data: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_fernet().encrypt(data))
    destination.chmod(0o600)


def decrypt_blob(source: Path) -> bytes:
    try:
        return _fernet().decrypt(source.read_bytes())
    except InvalidToken as exc:
        raise RuntimeError(
            f"Could not decrypt {source.name}. The encryption key has changed since "
            "this pack was uploaded - restore BOARDLENS_ENCRYPTION_KEY to its "
            "original value."
        ) from exc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_path_for(client_id: str, document_id: str, suffix: str) -> Path:
    """Per-client directory - segregation is visible on the filesystem too."""
    settings = get_settings()
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return settings.blob_dir / client_id / f"{document_id}{safe_suffix}.enc"


def safe_filename(name: str) -> str:
    """Strip path components from an uploaded filename.

    Board packs arrive from company secretaries via whatever their mail client
    produced; a filename is untrusted input.
    """
    base = Path(name).name
    cleaned = "".join(c for c in base if c.isalnum() or c in " ._-()[]&,+").strip()
    return cleaned[:180] or "document"
