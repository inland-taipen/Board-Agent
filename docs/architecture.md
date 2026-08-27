# Architecture

How BoardLens turns a 500-page board pack into a cited briefing, and the
reasoning behind the choices that are not obvious.

---

## 1. Ingestion — parsing for citability

Every parser reduces a file to an ordered list of `Segment`s. A segment is the
smallest region that still carries a *locator* a director could follow.

| Format | Locator | Precision | Notes |
|---|---|---|---|
| PDF | `p. 14` | Exact | Tables extracted separately; linear text extraction scrambles financial columns |
| PPTX | `Slide 7` | Exact | Speaker notes indexed separately — they hold the caveats the slide omits |
| XLSX | `Sheet 'P&L', rows 1-40` | Exact | Header row repeated on every band, or a retrieved band loses its column meaning |
| DOCX | `p. ~3 (paras 41-58)` | Approximate | Word pagination is a rendering decision; explicit page breaks are counted, volume approximates the rest |

The DOCX case is the interesting one. python-docx cannot tell you what page a
paragraph falls on, because Word decides that at render time. Inventing exact
page numbers would produce citations that do not match the printed pack, so the
locator is explicitly approximate and pairs the estimate with an exact paragraph
range. A director following `p. ~3 (paras 41-58)` finds the passage; a director
following a fabricated `p. 3` might not.

**Pages with no extractable text are recorded, not dropped.** A scanned annexure
that silently vanishes from the index produces a briefing with an invisible
blind spot. These pages are reported at upload, counted on the document row, and
named in the briefing's coverage note.

Parsing happens **at upload**, not at briefing time, so the operator learns
immediately that a file is a scan. Parsed segments are cached (encrypted)
alongside the blob, so the pipeline never re-parses.

---

## 2. Chunking and indexing

Chunks are the unit the model cites, which forces two rules:

1. **A chunk never spans two pages or two documents.** If it did, a citation
   could not resolve to a single source page.
2. **Chunk IDs are short and stable** (`c0041`). The model repeats them dozens
   of times per briefing; verbose IDs cost real tokens and invite typos.

IDs are numbered continuously across the whole pack, so one ID identifies one
passage unambiguously.

Splitting tries paragraph boundaries, then line boundaries, then hard character
limits. Tables are line-oriented and prose is paragraph-oriented; falling
through keeps risk-register rows intact instead of slicing one in half. A
configurable overlap carries trailing units forward so a split never orphans
context.

### Retrieval

**BM25 is the primary channel and is always available.** Board packs are dense
with proper nouns, statute references and covenant names where exact-term
matching outperforms embeddings, and it adds no model download to a
client-hosted deployment.

**Dense retrieval is optional** (`[dense]` extra). It catches the paraphrase
cases lexical search misses — "attrition in the sales organisation" against
"headcount churn, commercial function". The two rankings fuse with **Reciprocal
Rank Fusion**, which is rank-based and so needs no score calibration between two
very different scoring scales.

Document name, kind and heading are folded into each chunk's indexed text, so a
query for "internal audit findings" retrieves audit-report chunks even where the
body never repeats the word "audit".

### Section plans

Each briefing section has a different notion of relevance, so each fans out
across several query phrasings and biases toward the document kinds that carry
that answer — unresolved actions live in minutes, not in the deck. A chunk is
ranked by the *best* rank it achieved across the section's queries, so a chunk
that is the top hit for one phrasing outranks one that is mediocre for several.

---

## 3. The five passes

```
   ┌─ digest(doc 1) ─┐
   ├─ digest(doc 2) ─┤                                        ┌─ verify ─┐
   ├─ digest(doc 3) ─┼─► synthesise ──────────────────────────┤          │
   ├─ digest(doc 4) ─┤        ▲                               └─ repair ─┘
   └─ extract(minutes) ──► reconcile ──► action register ──────┘
        (parallel)          (batched)     (persists across cycles)
```

### Pass 1 — Digest

Each document is read in windows and reduced to a structured digest: key points
with citations, risks flagged, decisions sought, figures of note, and anomalies.
This is the only pass that sees every page. Anything it omits is lost to the
board, so it is instructed to prioritise quantified movements, decisions,
control failures and unsupported claims — and to skip boilerplate, agendas and
attendance lists.

Runs at lower effort than synthesis, in parallel across documents.

### Pass 2 — Extract

Prior minutes are read *again*, separately, purely for action items. A dedicated
pass beats asking the digest to do double duty, because exhaustive extraction
and executive summarisation pull in opposite directions.

The prompt errs heavily toward over-collection: a false positive is removed in
seconds at review; a missed item resurfaces as a governance failure months
later. It collects explicit action points, directions to management,
undertakings, deferrals, and conditional approvals whose condition creates
future work — and preserves the board's own wording, so directors recognise
their own minute.

### Pass 3 — Reconcile

Every carried-forward action is checked against evidence retrieved from the
**current** pack, using the action's own text as the query.

The important verdict is **`unclear`** — the current pack is silent on an item
the board directed. That silence is the finding: it means the item was directed
and has not been reported back. The prompt says so explicitly, because a model
will otherwise reclassify silence as "open" or infer progress from an unrelated
update touching the same subject area.

Statuses are written back to the persistent register.

### Pass 4 — Synthesise

Digests, the reconciled register, and section-targeted evidence go in; the
briefing comes out as a strict structured output. The prompt directs
cross-document reasoning explicitly — a risk the financials now quantify, an
audit finding that recurs and was already actioned once, a movement the deck and
the MIS attribute to different causes, a figure that differs between two
documents in the same pack.

### Pass 5 — Verify

Every cited chunk ID is resolved against the index. Two failure kinds are
separated because they mean different things:

- **`invalid`** — the ID is not in the pack. The statement has no traceable
  source.
- **`uncited`** — the item cites nothing. A defect for most fields, but *not*
  for an action correctly marked `unclear`, which by definition has nothing in
  the current pack to cite.

If anything fails, one repair pass runs: the model gets its own draft plus the
specific failures, and is told that **withdrawing an unsupported claim is the
correct outcome** — otherwise it invents a different wrong ID to fill the slot.
Anything still unresolved is shown to the reviewer, flagged, never hidden.

---

## 4. The action register

A persistent table, keyed by client, that outlives any single meeting.

Deduplication uses a fingerprint over the *stemmed* significant words of the
action text. Minutes reword standing items between cycles — "management to place
the IT security roadmap before the Board" becomes "the IT security roadmap to be
placed before the Board" — and treating those as two items would inflate the
register until directors stopped reading it. Retrieval deliberately does **not**
stem; exact-term matching is what makes "Ind AS 116" findable.

Ageing advances only when an item reappears in a *later* pack, so re-running a
briefing for the same meeting does not age the register.

The briefing carries the five actions that most need board time; the complete
register is annexed to every export and available in the interface.

---

## 5. Model integration

Everything above `boardlens/llm.py` is provider-agnostic. That file exposes one
function — `generate_structured(system, user, output_model, effort, max_tokens)`
— and `boardlens/providers/` holds one adapter per backend (Anthropic, Gemini,
Groq). Adding a provider means implementing one method.

Two invariants hold whichever backend is active:

**Every pass is structured.** A JSON schema derived from the Pydantic models in
`brief/schema.py` constrains the response, so the pipeline never parses prose
and a malformed briefing fails at the provider boundary rather than halfway
through a DOCX export. Schemas are flattened (no `$ref`) and hardened —
`additionalProperties: false`, every property required. That hardening is not
stylistic: it is exactly what Anthropic's `json_schema` format and Groq's
`strict: true` mode both demand, and optional fields in a strict schema invite
the model to omit the awkward ones. The awkward field here is always `evidence`.
Gemini takes the Pydantic model directly, so no second schema dialect is needed.

**Every failure is an `LLMError` written for a company secretary**, because it
surfaces on the pack row in the web interface. "No Gemini API credentials are
configured. Set GEMINI_API_KEY…" rather than a stack trace.

### What differs between providers

| | Anthropic | Gemini | Groq |
|---|---|---|---|
| Context | 1M | 1M | **131K** |
| Prompt caching | Yes | No | No |
| Effort control | `low`–`max` | Ignored — pick the model tier | `low`/`medium`/`high` |
| Schema guarantee | `json_schema` | `response_schema` | `strict: true` on specific models only |
| Streaming | Yes | No | No |

Anthropic is the reference implementation and the quality bar the briefing
template was written against. It is the only one supporting prompt caching, so
only there does the stable system-prefix design pay off: prompts are treated as
a cache prefix, system first and volatile pack content last, and any byte change
to `prompts.py` invalidates that cache for every in-flight pack.

Effort is tiered by pass — `medium` for the digest fan-out, `high` for
extraction (where exhaustiveness is the point) and synthesis. On Gemini this is
ignored rather than mapped onto a thinking budget, because a wrong mapping is
worse than none.

Groq's 131K ceiling is workable because every pass is already windowed, but
synthesis is the pass that grows with pack size. If a large pack approaches the
limit, lower `SECTION_EVIDENCE_CHARS` and `DIGEST_WINDOW_CHARS` in
`brief/generator.py`. The provider reports at startup whether the configured
model supports strict mode; anything else returns best-effort JSON that will
eventually fail validation mid-run rather than at configuration time.

`BOARDLENS_PROVIDER=auto` selects whichever credential is present, preferring
the provider best suited to a board pack. That exists so a pilot can start with
whatever key is to hand — a production deployment should pin it, so that adding
an unrelated key cannot change which model writes the board's briefing.

## 6. Storage and segregation

SQLite for metadata, an encrypted blob store for board packs, a per-pack index
directory — all on one volume. No database server, no object store. That is what
makes a client-hosted install a matter of running one container with one mount.

Segregation is structural, not a filter applied at query time:

- Every content row carries `client_id`.
- Blobs live under `blobs/{client_id}/`.
- Indexes live under `indexes/{client_id}/{pack_id}/`.
- Access requires a `user_clients` membership row. **Role grants capability;
  membership grants access.** An admin without a membership row cannot read that
  client's packs.
- Cross-client requests return **404, not 403** — confirming a board exists is
  itself a disclosure across the boundary.
- Reconciliation writes are scoped by `client_id`, so a reconciliation naming
  another client's action silently does nothing.

Every mutation and every briefing read is written to an append-only audit log.

---

## 7. Known limits

- **Verification proves a citation *resolves*, not that it *supports* the claim.**
  This is the most important limit to understand. An invented chunk ID is caught;
  a real chunk ID attached to the wrong statement is not — it resolves cleanly and
  passes. The check raises the floor (no untraceable claims) rather than
  guaranteeing correctness, which is why the company secretary's review before
  circulation is part of the design and not a formality. Annexure B exists partly
  so a reviewer can scan every cited passage against its finding in one place.
  Closing this properly needs an entailment pass — a cheap per-claim check asking
  whether the cited passage actually supports the sentence — and that is the
  highest-value accuracy increment after the pilot.

- **No OCR.** Scanned pages are reported, not read. Adding OCR is the highest-value
  next increment for packs that arrive as scans.
- **DOCX page numbers are approximate**, as described above.
- **Background jobs run in-process.** Fine for the pilot's two boards; a
  multi-tenant rollout wants a real queue so a restart does not lose a run in
  flight.
- **`grounding_rate` is a coverage statistic, not a pass/fail signal.** Actions
  correctly marked `unclear` cite nothing, so a perfectly correct briefing
  reports below 100%. `passed` is the signal.
- **Dense retrieval is untested at pilot scale** — it is off by default, and
  turning it on should be an explicit pilot decision with a recall comparison.
