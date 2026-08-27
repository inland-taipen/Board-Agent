"""Runtime configuration for BoardLens AI.

Everything is environment-driven so the same image can run in STAIR's cloud or
inside a client's own VPC without a rebuild.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BOARDLENS_",
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    # --- Model provider -----------------------------------------------------
    # "auto" uses whichever credential is present, preferring the provider best
    # suited to a 500-page board pack. Pin this in production so that adding an
    # unrelated key cannot change which model writes the board's briefing.
    provider: str = "auto"

    # Per-provider model IDs. Check these against the provider's own model list
    # before a pilot - they move faster than this file does.
    model: str = "claude-opus-5"          # anthropic
    gemini_model: str = "gemini-3.7-flash"
    groq_model: str = "openai/gpt-oss-120b"
    effort: str = "high"
    # Digest passes run over many chunks; keep effort lower there than on synthesis.
    digest_effort: str = "medium"

    # --- Storage ------------------------------------------------------------
    data_dir: Path = Path("./storage")
    encryption_key: str = ""

    # --- Auth ---------------------------------------------------------------
    jwt_secret: str = "change-me-in-production"  # noqa: S105 - default sentinel, checked at startup
    jwt_ttl_minutes: int = 480
    bootstrap_email: str = "admin@stairdigital.example"
    bootstrap_password: str = "change-me"  # noqa: S105 - default sentinel, checked at startup

    # --- Retrieval ----------------------------------------------------------
    dense_retrieval: bool = False
    dense_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_tokens: int = 700
    chunk_overlap_tokens: int = 100

    # --- Serving ------------------------------------------------------------
    # Explicit path to the built frontend. Left empty in development, where it
    # is discovered relative to the repository; set in the container image.
    web_dir: str = ""

    # --- Limits -------------------------------------------------------------
    max_upload_mb: int = 200
    cors_origins: str = "http://localhost:5173"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "boardlens.db"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "indexes"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.blob_dir, self.index_dir, self.export_dir):
            d.mkdir(parents=True, exist_ok=True)


def _load_dotenv_into_environ() -> None:
    """Put un-prefixed `.env` entries into the process environment.

    `pydantic-settings` reads only `BOARDLENS_*` keys into `Settings`. Provider
    credentials are deliberately un-prefixed - they are the names the Anthropic,
    Google and Groq SDKs look for - so without this they would sit in `.env`
    being read by nobody, which is exactly what `.env.example` invites people to
    do.

    `override=False` so a real environment variable always beats the file; a
    container's injected secret must win over a stale checkout.
    """
    from dotenv import load_dotenv

    here = Path(__file__).resolve()
    for candidate in (
        Path.cwd() / ".env",
        here.parents[2] / ".env",  # repository root, for an editable install
        here.parents[1] / ".env",  # backend/
    ):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


@lru_cache
def get_settings() -> Settings:
    _load_dotenv_into_environ()
    s = Settings()
    s.ensure_dirs()
    return s
