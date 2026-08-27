# BoardLens AI — Board Intelligence Agent

Implementation of **BRD 01, STAIR Digital Private Limited**.

BoardLens ingests a complete board pack — prior minutes, board deck, financial
MIS, risk register, internal audit reports — and produces a structured **Board
Briefing**: three critical risks, five unresolved actions carried over from
prior meetings, material performance changes, questions to put to management,
and the decisions the meeting must take. Every statement carries a reference
back to the source document and page it was drawn from.

---

## Quick start

```bash
make setup                       # venv + backend + frontend, creates .env
$EDITOR .env                     # add one provider key (see below)
make sample                      # generate a synthetic board pack to try it on
make brief                       # run the whole pipeline from the command line
```

For the web interface, run the two halves in separate terminals:

```bash
make backend                     # API on :8000
make frontend                    # interface on :5173
```

Sign in with the bootstrap credentials from `.env`
(`BOARDLENS_BOOTSTRAP_EMAIL` / `BOARDLENS_BOOTSTRAP_PASSWORD`) and change the
password before any real board pack is uploaded.

For a production-shaped run, `make build && make up` serves the API and the
interface from one container on `:8000`.

**You need one model provider key** — Anthropic, Gemini or Groq. Without any,
the pipeline fails immediately with an instruction rather than a stack trace.

| Provider | Key | Install | Notes |
|---|---|---|---|
| [Anthropic](https://console.anthropic.com/settings/keys) | `ANTHROPIC_API_KEY` | included | Reference implementation. 1M context, prompt caching, effort control |
| [Gemini](https://aistudio.google.com/apikey) | `GEMINI_API_KEY` | `pip install -e '.[gemini]'` | Closest substitute. Long context, native Pydantic schemas. Free tier |
| [Groq](https://console.groq.com/keys) | `GROQ_API_KEY` | `pip install -e '.[groq]'` | Fastest and cheapest. **131K context** and open models — see the caveat below |

`BOARDLENS_PROVIDER=auto` (the default) uses whichever key is present. **Pin it
explicitly in production** — under `auto`, adding an unrelated key to the
environment silently changes which model writes the board's briefing.

Keys go in `.env`, which is loaded into the process environment at startup.
Placeholder values left over from `.env.example` (`sk-ant-...`) are recognised
and ignored with a warning, so a half-filled `.env` does not select a provider
you have no key for.

> `BOARDLENS_DATA_DIR` defaults to the relative `./storage`, so the database
> lands beside whichever directory you run from. Set an absolute path for
> anything other than a quick trial.

---

## What it does, in order

```
  upload  ──►  parse  ──►  chunk + index  ──►  5-pass pipeline  ──►  verify  ──►  export
  PDF/DOCX     page-       BM25 (+optional     digest, extract,      resolve      DOCX
  PPTX/XLSX    accurate    dense) retrieval    reconcile,            every        PDF
               segments                        synthesise            citation
```

| # | Pass | What it does | Why it is separate |
|---|------|--------------|--------------------|
| 1 | **Digest** | Reads every document in windows, produces a structured digest | The only pass that sees all 500+ pages; lets the whole pack reach synthesis without truncation |
| 2 | **Extract** | Re-reads prior minutes for action items, exhaustively | Exhaustive extraction and executive summarisation pull in opposite directions — one prompt cannot do both well |
| 3 | **Reconcile** | Checks each carried-forward action against the *current* pack | Produces the `unclear` verdict: the board directed something and this pack is silent on it |
| 4 | **Synthesise** | Reasons across digests, register and section evidence | The best findings are the ones no single document states |
| 5 | **Verify** | Resolves every cited chunk ID against the index | An audit trail nothing checks is not an audit trail |

Passes 1 and 2 fan out across documents in parallel. If verification finds an
unsupported citation, one repair pass is attempted; anything still unresolved
is surfaced to the reviewer rather than hidden.

---

## Design decisions worth knowing

**Citations are chunk IDs, not prose.** The model emits `evidence: ["c0042"]`,
never a sentence naming a page. IDs are checked against the index, so an
invented reference is caught rather than published. A chunk never spans two
pages or two documents — otherwise a citation could not resolve to one source
page.

**Absence is treated as a finding.** An action the board directed that the
current pack does not mention is reported as *not addressed*, with an empty
evidence list, and verification explicitly does not penalise that. This is the
single most valuable output of the pipeline and the one a model will avoid
producing unless told to.

**Lexical retrieval is the primary channel.** Board packs are dense with proper
nouns and figures — "Ind AS 116", "DSCR", "Q3 FY26" — where BM25 beats
embeddings, and it adds no model download to a client-hosted install. Dense
retrieval is optional (`pip install -e '.[dense]'`,
`BOARDLENS_DENSE_RETRIEVAL=true`) and fuses with BM25 by Reciprocal Rank Fusion.

**The action register outlives the meeting.** It is a persistent table keyed by
a stemmed fingerprint of the action text, so an item reworded between cycles
does not duplicate, and an item nobody has mentioned for three meetings still
appears. That is what makes the BRD's 100%-of-unresolved-actions objective
achievable rather than aspirational.

**Segregation is structural.** Every content row carries `client_id`, blobs
live in per-client directories, and access requires an explicit membership row
— an admin without one cannot read a client's packs. Cross-client requests
return 404, not 403, because confirming a board exists is itself a disclosure.

---

## Layout

```
backend/
  boardlens/
    ingest/        PDF, DOCX, PPTX, XLSX parsers -> located segments
    rag/           chunking, BM25 + optional dense index, section retrieval
    brief/         output schema, prompts, the 5-pass pipeline, verification
    actions/       cross-cycle action-item store
    export/        shared layout -> DOCX and PDF renderers
    api/           auth, RBAC, HTTP routes
    llm.py         the pipeline's single point of contact with a model
    providers/     anthropic, gemini and groq adapters behind one interface
    service.py     ingestion, indexing, briefing runs, exports
    db.py          SQLite schema and audit log
    security.py    PBKDF2 passwords, JWT sessions, Fernet encryption at rest
  scripts/         synthetic board pack generator
  tests/           64 tests, no API key required
frontend/          React + Vite review interface
deploy/            production compose, Caddy TLS, step-by-step guide
docs/              architecture, security, briefing template
```

---

## Formats and limits

| | |
|---|---|
| Accepted | PDF, DOCX, PPTX, XLSX/XLSM |
| Per-file limit | 200 MB (`BOARDLENS_MAX_UPLOAD_MB`) |
| Pack size | Designed for 500+ pages per meeting cycle |
| Providers | Anthropic, Gemini, Groq (`BOARDLENS_PROVIDER`) |
| Storage | SQLite + encrypted blob store on one volume |

Locator precision differs by format, and the briefing says so rather than
pretending otherwise: PDF pages and PPTX slides are exact, XLSX cites sheet and
row range, and DOCX cites an approximate page with a paragraph range — Word
pagination is a rendering decision no parser can read.

Pages with no extractable text (scans) are reported at upload and named in the
briefing's coverage note. They are never silently dropped.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — how the pipeline works and why
- [`docs/security.md`](docs/security.md) — the security posture, and its limits
- [`docs/briefing-template.md`](docs/briefing-template.md) — the briefing structure (BRD Phase 1)
- [`deploy/README.md`](deploy/README.md) — putting it on a shareable HTTPS link, free

## Development

```bash
make test      # 64 backend tests + frontend typecheck
make lint      # ruff
make clean     # remove local state (destroys uploaded packs)
```

The test suite runs without any API key: the model call is the only part that
needs one, and everything around it — parsing, chunking, retrieval, the action
register, verification, both exports, auth, segregation and provider selection
— is tested directly.

## Choosing a provider

The pipeline is provider-agnostic above `boardlens/llm.py`, but the providers
are not equivalent for this task:

**Context.** Groq caps at 131K tokens against 1M elsewhere. BoardLens already
windows every pass, so this fits — but synthesis is the pass that grows with
pack size, and a very large pack can approach the ceiling. If it does, lower
`SECTION_EVIDENCE_CHARS` and `DIGEST_WINDOW_CHARS` in `brief/generator.py`.

**Schema adherence.** On Groq, only specific models support `strict: true`
constrained decoding (`STRICT_MODELS` in `providers/groq_provider.py`).
Anything else returns best-effort JSON that will eventually fail validation
mid-run. The provider reports which mode it is in at startup — check that line.

**Judgment.** This is the one that matters and the one a benchmark will not
tell you. The briefing depends on the model being willing to write "the pack
gives no explanation for the 360bp margin decline" and to mark an action *not
addressed* rather than inventing progress. Smaller open models are markedly
more prone to filling those gaps plausibly. Whichever provider you pick, run a
real pack through it and read the output against the source before a board
sees it.
