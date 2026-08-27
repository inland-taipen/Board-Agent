"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .config import get_settings
from .db import init_db
from .service import ServiceError, ensure_bootstrap_admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("boardlens")


def _describe_provider() -> str:
    """Name the active provider without constructing a client.

    Startup must not fail because a key is missing - the operator should reach
    the interface and see the problem reported on the pack, not a container
    that will not boot.
    """
    from .providers import detect_provider, model_for

    configured = (get_settings().provider or "auto").strip().lower()
    if configured != "auto":
        return f"{configured} / {model_for(configured)} (pinned)"

    detected = detect_provider()
    if detected is None:
        return "none - no ANTHROPIC_API_KEY, GEMINI_API_KEY or GROQ_API_KEY found"
    return f"{detected} / {model_for(detected)} (auto-detected)"


def _check_secrets(settings) -> None:
    """Warn loudly about credentials that are fine for a laptop and not for a board.

    Deliberately a warning rather than a hard failure: a pilot team running the
    demo should not be blocked, but nobody should be able to say afterwards that
    the deployment never told them.
    """
    if settings.jwt_secret == "change-me-in-production":  # noqa: S105 - sentinel, not a secret
        log.warning(
            "BOARDLENS_JWT_SECRET is still the default value. Anyone who knows it can "
            "mint a valid session for any board. Set it before this instance sees a "
            "real board pack."
        )
    elif len(settings.jwt_secret.encode()) < 32:
        log.warning(
            "BOARDLENS_JWT_SECRET is shorter than the 32 bytes recommended for HS256 "
            "(RFC 7518). Generate one with: python -c \"import secrets; "
            'print(secrets.token_urlsafe(48))"'
        )

    if not settings.encryption_key:
        log.warning(
            "BOARDLENS_ENCRYPTION_KEY is not set, so packs are encrypted with a "
            "key kept at %s/.master.key (created on first use). A key stored "
            "beside the ciphertext protects a stolen disk image, not a compromised "
            "host - supply it from a secrets manager in production.",
            settings.data_dir,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    ensure_bootstrap_admin()
    _check_secrets(settings)
    log.info(
        "BoardLens ready - provider=%s dense_retrieval=%s data_dir=%s",
        _describe_provider(),
        settings.dense_retrieval,
        settings.data_dir.resolve(),
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="BoardLens AI",
        description=(
            "Board Intelligence Agent - ingests a board pack and produces a cited "
            "Board Briefing. STAIR Digital, BRD 01."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict:
        # Deliberately cheap and dependency-free - the container healthcheck
        # calls it, and it must not fail because a model key is absent.
        return {"status": "ok", "version": app.version}

    _mount_web_interface(app)
    return app


def _mount_web_interface(app: FastAPI) -> None:
    """Serve the built frontend from the same origin, when it is present.

    A single container serving both the API and the interface is what makes
    client-side hosting practical: one image to review, one port to open, and
    no CORS configuration for the client's platform team to get wrong. In
    development the frontend runs under Vite instead and this does nothing.
    """
    from fastapi.staticfiles import StaticFiles

    dist = _find_web_dist()
    if dist is None:
        log.info("No built frontend found - serving the API only.")
        return

    # html=True makes StaticFiles fall back to index.html, so the app's own
    # in-memory view state survives a page reload on any path.
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    log.info("Serving the web interface from %s", dist)


def _find_web_dist() -> Path | None:
    """Locate the built frontend across both layouts we ship.

    In development the package is an editable install and the build sits at
    `<repo>/frontend/dist`, two levels above this file. In the container the
    package lives in site-packages, so that relative walk lands in the Python
    installation instead - there the build is beside the working directory.
    `BOARDLENS_WEB_DIR` overrides both, and the image sets it explicitly.
    """
    settings = get_settings()
    candidates = [
        Path(settings.web_dir) if settings.web_dir else None,
        Path.cwd() / "frontend" / "dist",
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
    ]
    for candidate in candidates:
        if candidate and (candidate / "index.html").exists():
            return candidate
    return None


app = create_app()
