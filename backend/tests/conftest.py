"""Test fixtures.

Every test runs against a throwaway data directory so no test can touch a real
board pack, and the settings cache is cleared so the redirect actually takes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    import boardlens.config as config
    from boardlens.config import get_settings

    # The suite must not read the developer's .env. Without this, whichever
    # provider keys happen to be on the machine leak into tests that assert
    # what happens when none are present.
    monkeypatch.setattr(config, "_load_dotenv_into_environ", lambda: None)

    monkeypatch.setenv("BOARDLENS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BOARDLENS_JWT_SECRET", "test-secret-not-for-production-at-least-32-bytes-long")
    monkeypatch.setenv("BOARDLENS_DENSE_RETRIEVAL", "false")
    monkeypatch.setenv("BOARDLENS_BOOTSTRAP_EMAIL", "admin@test.local")
    monkeypatch.setenv("BOARDLENS_BOOTSTRAP_PASSWORD", "test-password")
    get_settings.cache_clear()

    import boardlens.db as db

    if hasattr(db._local, "conn"):
        db._local.conn.close()
        del db._local.conn

    yield get_settings()

    if hasattr(db._local, "conn"):
        db._local.conn.close()
        del db._local.conn
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def sample_pack(tmp_path_factory) -> Path:
    """Build the synthetic board pack once and share it across tests."""
    import make_sample_pack

    destination = tmp_path_factory.mktemp("pack")
    make_sample_pack.main(destination)
    return destination
