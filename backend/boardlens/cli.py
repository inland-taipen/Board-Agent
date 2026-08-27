"""Command-line entry point.

`boardlens brief` runs the whole pipeline over a folder of files without the
web interface. It is what the pilot team uses to test a real pack quickly, and
what CI uses to exercise the pipeline end to end.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import service
from .config import get_settings
from .db import execute, init_db, new_id, now, query_one
from .ingest import SUPPORTED_EXTENSIONS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="boardlens", description="BoardLens AI")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    brief = sub.add_parser("brief", help="Generate a briefing from a folder of documents")
    brief.add_argument("--client", required=True, help="Board / company name")
    brief.add_argument("--meeting", required=True, help="Meeting label, e.g. 'Q3 FY26 Board Meeting'")
    brief.add_argument("--dir", required=True, type=Path, help="Folder containing the board pack")
    brief.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    brief.add_argument(
        "--classification",
        default="confidential",
        choices=["public", "internal", "confidential", "strictly_confidential"],
    )
    brief.add_argument("--out", type=Path, default=None, help="Where to write DOCX and PDF")

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "boardlens.main:app", host=args.host, port=args.port, reload=args.reload
        )
        return 0

    return _brief(args)


def _brief(args) -> int:
    init_db()
    settings = get_settings()

    client_id = _ensure_client(args.client)
    pack_id = service.create_pack(
        client_id=client_id,
        meeting_label=args.meeting,
        meeting_date=args.date,
        classification=args.classification,
        user_id="cli",
    )

    files = sorted(
        p
        for p in args.dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not files:
        print(
            f"No supported documents found in {args.dir}. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
            file=sys.stderr,
        )
        return 1

    print(f"Ingesting {len(files)} document(s) for {args.client} / {args.meeting}")
    for path in files:
        try:
            info = service.add_document(
                client_id=client_id,
                pack_id=pack_id,
                filename=path.name,
                data=path.read_bytes(),
                doc_kind=None,
                classification=args.classification,
                user_id="cli",
            )
        except service.ServiceError as exc:
            print(f"  skipped {path.name}: {exc}", file=sys.stderr)
            continue
        note = (
            f", {len(info['unreadable_pages'])} unreadable page(s)"
            if info["unreadable_pages"]
            else ""
        )
        print(
            f"  {info['filename']}  ->  {info['doc_kind']}  "
            f"({info['pages']} pages, {info['segments']} segments{note})"
        )

    # Name the provider that will actually run, not the Anthropic model setting -
    # which model wrote a briefing is a governance question, not a detail.
    from .main import _describe_provider

    print(f"\nGenerating briefing with {_describe_provider()} at effort '{settings.effort}'...\n")
    try:
        briefing_id = service.run_briefing(
            client_id=client_id, pack_id=pack_id, user_id="cli"
        )
    except Exception as exc:
        print(f"\nBriefing failed: {exc}", file=sys.stderr)
        return 1

    record = service.get_briefing(client_id, briefing_id)
    verification = record["verification"]
    print(
        f"\nBriefing {briefing_id}\n"
        f"  findings grounded : {verification['grounded_items']}/{verification['total_items']}\n"
        f"  citations resolved: {verification['resolved_citations']}/{verification['total_citations']}\n"
        f"  unresolved issues : {len(verification['issues'])}"
    )

    for fmt in ("docx", "pdf"):
        path = service.export_briefing(client_id, briefing_id, fmt, user_id="cli")
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            target = args.out / path.name
            target.write_bytes(path.read_bytes())
            path = target
        print(f"  {fmt.upper():4} -> {path}")

    return 0


def _ensure_client(name: str) -> str:
    row = query_one("SELECT id FROM clients WHERE name = ?", (name,))
    if row:
        return row["id"]
    client_id = new_id("cli")
    execute(
        "INSERT INTO clients (id, name, created_at) VALUES (?,?,?)",
        (client_id, name, now()),
    )
    return client_id


if __name__ == "__main__":
    raise SystemExit(main())
