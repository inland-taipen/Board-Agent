# Deploying BoardLens on Render

The fastest route to a permanent, always-on `https://` link. About 15 minutes,
most of it waiting for the first build. No server administration, no SSH, no
certificate setup — Render handles TLS automatically.

## What it costs, and why it cannot be free

**$7/month** (Starter instance) **+ $2.50/month** (10 GB disk) = **~$9.50/month**.

Render's free tier will not work, and it is worth understanding why rather than
discovering it after an afternoon of setup. Free web services have an
**ephemeral filesystem** and cannot attach a disk. Render's own documentation is
explicit that *"local SQLite databases are lost every time the service
redeploys, restarts, or spins down"* — and free services spin down after 15
minutes of inactivity.

For BoardLens that means every quarter-hour of quiet destroys the database, the
user accounts you created, the uploaded board packs and the retrieval indexes. A
reviewer who signs in tomorrow finds their account gone.

The `disk:` in `render.yaml` is the entire reason a paid instance is needed. It
is not about CPU or memory: BoardLens idles at 87 MB and peaks around 95 MB
while parsing a pack, which is a fraction of Starter's 512 MB.

> If free is a hard constraint, use **GitHub Codespaces** instead — genuinely
> free, no card, persistent disk, but it stops after 30 minutes idle so the link
> only works while you have it running. See the main `README.md`.

---

## Before you start

- Your code pushed to GitHub (it is)
- A Google Gemini API key — [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- A Render account — [render.com](https://render.com/) (sign in with GitHub)

**Generate the two secrets now**, on your laptop, and keep them somewhere safe:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # BOARDLENS_ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                # BOARDLENS_JWT_SECRET
```

Keep `BOARDLENS_ENCRYPTION_KEY` somewhere separate and durable. It encrypts
every uploaded pack; if you lose it, existing packs become permanently
unreadable, and changing it has the same effect.

---

## 1 · Create the service (~3 min)

1. Go to [dashboard.render.com](https://dashboard.render.com/) → **New → Blueprint**
2. Connect your GitHub account and pick the **Board-Agent** repository
3. Render finds `render.yaml` at the repo root and shows one service, `boardlens`
4. It then prompts for the five secret values:

| Prompt | What to enter |
|---|---|
| `GEMINI_API_KEY` | Your Gemini key |
| `BOARDLENS_ENCRYPTION_KEY` | The Fernet key you generated |
| `BOARDLENS_JWT_SECRET` | The token you generated |
| `BOARDLENS_BOOTSTRAP_EMAIL` | Your email — this becomes the first admin |
| `BOARDLENS_BOOTSTRAP_PASSWORD` | A strong password you will use to sign in |

5. **Apply**

Everything else — region, plan, the disk, the provider settings — comes from
`render.yaml`, so there is nothing else to configure.

## 2 · Wait for the first build (~8 min)

Render builds the Docker image: Node compiles the frontend, then Python installs
the backend and all three provider SDKs. Subsequent deploys are faster because
layers are cached.

Watch **Logs**. You are waiting for:

```
BoardLens ready - provider=gemini / gemini-3.7-flash (pinned) ... data_dir=/data
```

If it says `provider=none`, the Gemini key did not reach the service — check
**Environment** in the dashboard.

## 3 · Open it

Render gives you `https://boardlens.onrender.com` (or similar — the exact
subdomain is shown at the top of the service page). HTTPS is automatic; there is
no certificate step.

Sign in with the bootstrap email and password from step 1.

## 4 · Set it up for your reviewers (~5 min)

1. **Add board** — the company name. It appears on every exported briefing.
2. **People → Add someone**, one entry per reviewer:
   - **Director** — reads briefings only. Correct for most people you are showing it to.
   - **Company secretary** — uploads packs and generates briefings.
   - **Administrator** — also manages people.
3. Set each person a password and pass it to them directly. Passwords are stored
   as one-way hashes and cannot be read back, so note it before leaving the page.

Send each reviewer three things: the URL, their email, and their password.

### Give them something to look at first

A reviewer landing on an empty screen has nothing to react to. Upload a pack and
generate a briefing **before** you send the link. To make a synthetic pack
locally:

```bash
cd backend && python scripts/make_sample_pack.py ../sample_pack
```

Upload those four files under a meeting, press **Generate briefing**, wait about
ninety seconds.

---

## Custom domain (optional)

Service → **Settings → Custom Domains → Add**. Render shows a CNAME to create
with your DNS provider, then issues a certificate automatically once it
resolves. `boardlens.stairdigital.com` reads better to a board than
`onrender.com`.

## Updating

Render redeploys automatically on every push to `main`:

```bash
git push
```

Your disk and environment variables are untouched by a deploy. Data survives.

## Backups

There is no automatic backup. Render's **Disks → Snapshots** covers the volume
on paid plans; take one before anything significant. To pull a copy down, use
the service **Shell** (paid plans include SSH access):

```bash
tar czf /tmp/backup.tar.gz -C /data .
```

Keep `BOARDLENS_ENCRYPTION_KEY` stored separately from the backup. The archive
is encrypted with it and is unreadable without it.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Build fails on the frontend step | Node ran out of memory | Rare on Render's builders; retry, then raise the plan if it repeats |
| `provider=none` in the logs | Gemini key missing or a placeholder | **Environment** tab → check `GEMINI_API_KEY` → **Save**, which redeploys |
| Sign-in rejected | Bootstrap account is created **only on first boot** | Changing `BOARDLENS_BOOTSTRAP_PASSWORD` afterwards has no effect. Use the Shell to reset, or wipe the disk and redeploy |
| "No model provider credentials" on a pack | Same as above | Same |
| Briefing fails partway | Gemini free-tier rate limit | The error is shown on the meeting. Wait a few minutes, press Generate again |
| Upload rejected as too large | Above the configured limit | Raise `BOARDLENS_MAX_UPLOAD_MB` in the Environment tab |
| Everything vanished after a restart | The service has no disk attached | Confirm **Disks** shows `boardlens-data` mounted at `/data`. Without it you are effectively on ephemeral storage |

---

## Before real board packs

This setup is right for testing with synthetic material. Before a genuine
client pack goes near it:

- **Move off the Gemini free tier.** Its data-handling terms are weaker than
  paid. Board packs are unpublished price-sensitive information.
- **Consider a regional endpoint** — Vertex AI or Bedrock in Mumbai — so
  content stays in-country. The provider layer in `backend/boardlens/providers/`
  is designed for this; it is one new adapter, not a rewrite.
- **Read `security.md`** in `docs/`, written for a client's infosec review.
- **Remove the test accounts** you created in People, and change the bootstrap
  password.
- **Set up disk snapshots** rather than relying on the manual command above.
- **Add rate limiting** in front of sign-in. There is none today.
