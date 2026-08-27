# Deploying BoardLens on Render

The fastest route to a public `https://` link. About 15 minutes, most of it
waiting for the first build. No server administration, no SSH, no certificate
setup — Render handles TLS automatically.

## What you get on the free tier

**Free. No credit card.** `render.yaml` is configured for the free plan.

Free web services have an **ephemeral filesystem** — no disk can be attached —
and they **sleep after 15 minutes without traffic**. When the service wakes, the
database, user accounts, uploaded packs, retrieval indexes and generated
briefings are gone.

Tested against the real image, this is what that actually means:

| | |
|---|---|
| ✅ A live session | The service stays warm while in use. Sign in, upload, generate, review, export — all normal |
| ✅ Signing in after a sleep | The bootstrap administrator is recreated on every cold start, so the login always works |
| ⚠️ First click after a sleep | ~1 minute cold start; Render shows a loading page |
| ❌ Returning later | Anything uploaded in an earlier session is gone |
| ❌ People you add | Accounts created in the People screen vanish on sleep — share the bootstrap login instead |

**So it works for a live demo, not for a link people dip into over a week.**

Memory is not the constraint: BoardLens idles at 87 MB and peaks around 95 MB
parsing a pack, against free tier's 512 MB. Only storage is.

### Making it permanent later

Three changes, about **$9.50/month** ($7 Starter + $2.50 for 10 GB):

1. `plan: starter` in `render.yaml`
2. Uncomment the `disk:` block
3. Push — Render redeploys

Data then survives restarts, and accounts you create in People persist.

## Before you start

- Your code pushed to GitHub (it is)
- A Google Gemini API key — [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- A Render account — [render.com](https://render.com/) (sign in with GitHub)

**Generate the two secrets now**, on your laptop, and keep them somewhere safe.
You will paste them into Render's dashboard, not into the repository:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # BOARDLENS_ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                # BOARDLENS_JWT_SECRET
```

Keep `BOARDLENS_ENCRYPTION_KEY` somewhere durable. On the free tier it only
protects packs within a single session, since nothing survives a sleep — but
once you move to a paid plan, losing or changing it makes every already-uploaded
pack permanently unreadable.

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

Everything else — region, plan and the provider settings — comes from
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

> **On the free tier, skip the People screen.** Accounts created there are lost
> on the next sleep. Share the bootstrap email and password from step 1 with your
> reviewers instead — it is recreated on every cold start, so it always works.
> Per-person logins become worthwhile once you move to a paid plan.

1. **Add board** — the company name. It appears on every exported briefing.
2. **People → Add someone**, one entry per reviewer (paid plans):
   - **Director** — reads briefings only. Correct for most people you are showing it to.
   - **Company secretary** — uploads packs and generates briefings.
   - **Administrator** — also manages people.
3. Set each person a password and pass it to them directly. Passwords are stored
   as one-way hashes and cannot be read back, so note it before leaving the page.

Send each reviewer three things: the URL, their email, and their password.

### Give them something to look at first

A reviewer landing on an empty screen has nothing to react to. Upload a pack and
generate a briefing **before** you send the link — and on the free tier, do it
shortly before, since a sleep wipes it. To make a synthetic pack
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

Environment variables are untouched by a deploy. On a paid plan the disk is too,
so data survives; on the free tier a deploy wipes it like any other restart.

## Backups

Not applicable on the free tier — there is nothing persistent to back up. On a
paid plan:

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
| Sign-in rejected | Bootstrap account is created on first boot of an empty database | On the free tier just change the value and redeploy — the database is empty each time, so it takes effect. On a paid plan the account already exists, so use the Shell or wipe the disk |
| "No model provider credentials" on a pack | Same as above | Same |
| Briefing fails partway | Gemini free-tier rate limit | The error is shown on the meeting. Wait a few minutes, press Generate again |
| Upload rejected as too large | Above the configured limit | Raise `BOARDLENS_MAX_UPLOAD_MB` in the Environment tab |
| Everything vanished after a restart | Expected on the free tier | This is the ephemeral filesystem, not a fault. Move to Starter with a disk to fix it |
| First load takes ~1 minute | Free tier cold start after a sleep | Expected. Open the link yourself a minute before sending it to anyone |

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
