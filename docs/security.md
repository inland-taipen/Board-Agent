# Security posture

Written for a listed company's information-security review. It states what
BoardLens does, and — more usefully — what it does not do and what the deploying
team must supply.

---

## Data classification

Board packs are among the most sensitive documents a listed company produces:
unpublished price-sensitive information, draft results, litigation strategy,
acquisition proposals. Treat every deployment as handling UPSI.

Each pack carries a classification (`public` / `internal` / `confidential` /
`strictly_confidential`) chosen by the company secretary at creation. It is
stamped on **every page** of both exports and shown in the interface.

---

## What is protected, and how

| Control | Implementation | Notes |
|---|---|---|
| Encryption at rest | Fernet (AES-128-CBC + HMAC-SHA256) over every uploaded file and its parsed segments | Plaintext exists only in memory during parsing |
| File permissions | Blobs and the key file are `0600` | |
| Passwords | PBKDF2-HMAC-SHA256, 600,000 rounds, per-user salt | OWASP-current; never recoverable |
| Sessions | HS256 JWT, 8-hour default TTL | Memberships are re-read from the database on every request, so revocation takes effect immediately rather than at token expiry |
| Client segregation | `client_id` on every content row; per-client blob and index directories; explicit membership rows | See below |
| Audit trail | Append-only log of every mutation **and every briefing read** | Boards are asked who saw what and when |
| Authorisation | Role (`director` / `secretary` / `admin`) **and** membership, both required | |

### Segregation in detail

Role grants capability; membership grants access. These are independent, and
both are checked:

- A **director** can read briefings for boards they are a member of, and cannot
  upload or generate.
- A **secretary** can upload packs and run briefings for their boards.
- An **admin** can create boards and add members — and still cannot read a
  client's content without a membership row of their own.

Cross-client requests return **404, not 403**. Confirming that a board or pack
exists is itself a disclosure across the segregation boundary.

There is no "all packs" query anywhere in the codebase. Every service function
takes an explicit `client_id`.

Segregation is tested from the outside, through HTTP, in
`backend/tests/test_api.py` — not just at the service layer.

---

## What the deploying team must supply

**These are not optional for a production deployment.**

1. **TLS termination.** BoardLens speaks plain HTTP. Encryption *in transit* is
   an ingress concern — put a reverse proxy or load balancer in front of it. The
   supplied `docker-compose.yml` binds to `127.0.0.1` so it cannot be reached
   directly by accident.

2. **`BOARDLENS_ENCRYPTION_KEY` from a secrets manager.** If unset, a key is
   generated and written to `$BOARDLENS_DATA_DIR/.master.key` at `0600`. That
   protects a stolen disk image; it does **not** protect against a compromised
   host, because the key sits beside the ciphertext. Supply it from a vault, and
   note that **changing it makes existing packs undecryptable**.

3. **`BOARDLENS_JWT_SECRET`, at least 32 bytes.** The default value is a
   sentinel; anyone who knows it can mint a valid session for any board. The
   application logs a loud warning at startup if it is still the default or too
   short, but does not refuse to start — a pilot team running a demo should not
   be blocked, and nobody should be able to say afterwards that they were not
   told.

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

4. **Change the bootstrap administrator password** before any client board pack
   is uploaded. It is created once, on an empty database, from
   `BOARDLENS_BOOTSTRAP_*`.

5. **Backups of the data volume**, and a decision about retention. Deleting a
   pack removes its blobs and parsed segments; the audit log is deliberately
   append-only and is not purged with it.

---

## Data leaving the deployment

**Board pack content is sent to whichever model provider is configured.** That
is the whole mechanism, and it is the fact a client's security review will focus
on.

- Passes send parsed text (never the original files) over TLS to the active
  provider: `api.anthropic.com`, `generativelanguage.googleapis.com` (Gemini),
  or `api.groq.com`.
- **Know which one is active.** `BOARDLENS_PROVIDER=auto` picks whichever key is
  present, so a stray key in the environment can change where board content is
  sent. Pin the provider explicitly in any deployment handling real packs. The
  active provider is logged at startup and reported by `GET /api/meta`.
- No other outbound network calls are made. No telemetry, no analytics, no CDN —
  the interface is served from the same container.
- The provider's data-retention and training commitments are the governing
  terms, and **they differ between providers**. Obtain the ones that apply to
  the tier you are on — free tiers in particular may carry weaker guarantees
  than paid ones — before onboarding a board.
- For clients who cannot send content to any third-party API, this architecture
  does not fit as-is. The model call is isolated behind `boardlens/llm.py` and
  `boardlens/providers/`, so a self-hosted backend is a new adapter rather than
  a rewrite.

The API key is read from the environment and never written to disk, logged, or
returned by any endpoint.

---

## Deployment shape

One container, one volume, one port:

```
  ingress (TLS)  ──►  boardlens:8000  ──►  /data volume
                            │                 ├── boardlens.db
                            │                 ├── blobs/{client_id}/*.enc
                            │                 ├── indexes/{client_id}/{pack_id}/
                            └──► the configured model provider (TLS)
                                              └── exports/{client_id}/
```

The image runs as an unprivileged user (uid 10001) with the data volume as the
only writable path. This shape is deliberate: a single container with one open
port is far easier to get through an information-security review than a
multi-service topology, and it makes client-side hosting practical.

---

## Residual risks

Stated plainly rather than omitted:

- **Exported files are unencrypted** once written to `exports/` and once
  downloaded. They carry the classification banner, but circulation control
  after download is a process control, not a technical one.
- **The `.master.key` fallback** is convenience for pilots, not a production
  control. See item 2 above.
- **Background jobs run in-process.** A restart mid-run loses that run; the pack
  is left in `processing` and must be regenerated.
- **No rate limiting on authentication.** Put it at the ingress, or add it
  before exposing the service beyond a trusted network.
- **No multi-factor authentication.** For a director-facing production rollout,
  front the service with an SSO provider rather than relying on the built-in
  password flow.
- **Model output is not authoritative.** Every briefing is reviewed by the
  company secretary before circulation; the interface and both exports flag
  findings whose citations did not resolve, and the coverage note states what
  could not be assessed. The verification pass reduces unsupported claims — it
  does not eliminate the need for review.
