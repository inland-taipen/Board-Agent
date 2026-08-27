# Putting BoardLens on a link you can send

Written to be followed start to finish. Roughly 40 minutes, most of it waiting.
The result is a permanent `https://…` address that works whether or not your
laptop is on, with a separate login for each person you invite.

**Cost: nothing.** Oracle Cloud's "Always Free" tier is free permanently, not a
trial. Card verification is required at signup; it is not charged.

> **Before you start — what may be uploaded.** Anything put on this instance is
> sent to Google's Gemini API for processing. On the free tier, Google's terms
> for data handling are weaker than on paid plans. Use synthetic or anonymised
> packs while testing. Before a genuine client board pack goes anywhere near it,
> move to a paid tier and read `../docs/security.md` § Data leaving the
> deployment.

---

## 1. Create the server (~15 min)

1. Sign up at [cloud.oracle.com](https://cloud.oracle.com/) — choose **Mumbai**
   or the region closest to your users.
2. **Compute → Instances → Create instance.**
3. Change the image and shape:
   - Image: **Ubuntu 22.04**
   - Shape: **Ampere / VM.Standard.A1.Flex**, set to **2 OCPU, 12 GB memory**
     (well inside the always-free allowance)
4. Under **Networking**, keep "Assign a public IPv4 address".
5. Under **Add SSH keys**, choose **Generate a key pair** and download the
   private key. You need it to log in.
6. Click **Create**, then note the **Public IP address**.

> If Oracle says the shape is out of capacity, try a different availability
> domain, or an `E2.1.Micro` shape — smaller but also always free, and enough
> for testing.

### Open the ports

**Networking → Virtual Cloud Networks →** your VCN **→ Security Lists →**
Default. Add two **Ingress Rules**, both with source `0.0.0.0/0`, IP protocol
TCP, destination port `80` and `443`.

Oracle's Ubuntu images also run a local firewall, which the setup script below
handles.

---

## 2. Point a domain at it (~5 min)

Caddy needs a hostname to get an HTTPS certificate. Any of these works:

- A subdomain of a domain you own — add an **A record** to the server's public IP.
- Free: [duckdns.org](https://www.duckdns.org/) gives you
  `something.duckdns.org` in about two minutes.

Wait until `ping your-hostname` returns the server's IP before continuing.
Certificates fail if DNS has not propagated.

---

## 3. Copy the code up and start it (~15 min)

**On your laptop**, package the source and send it over. The project is not in
git, and at 150 KB a tarball is simpler than setting one up. Secrets, uploaded
packs and exports are excluded automatically.

```bash
cd ~/BoardAgent
bash deploy/package.sh
scp -i ~/Downloads/ssh-key-*.key /tmp/boardlens-deploy.tar.gz ubuntu@YOUR_SERVER_IP:~/
```

**Then log in to the server:**

```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@YOUR_SERVER_IP
```

**Run the setup script.** It installs Docker, opens the firewall, adds swap if
the instance is small, and unpacks the code:

```bash
tar xzf boardlens-deploy.tar.gz -O deploy/server-setup.sh > setup.sh
bash setup.sh
```

If it says to log out and back in, do that — your user needs to pick up the
`docker` group — then continue.

**Configure and start:**

```bash
cd ~/BoardAgent/deploy
cp .env.prod.example .env
nano .env
```

Fill in all six values. Generate the two secrets with:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # ENCRYPTION_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                # JWT_SECRET
```

Save (Ctrl-O, Enter, Ctrl-X), then:

```bash
bash start.sh
```

It checks your settings and DNS before building, so a missing value fails in
two seconds rather than after a five-minute build. The first build takes 3–6
minutes. When it finishes it prints your URL.

Open `https://your-hostname`. The certificate is issued on the first request,
so the very first load can take a few seconds.

## 4. Set it up for your reviewers (~5 min)

1. Sign in with the bootstrap email and password from `.env`.
2. **Add board** — the company name. It appears on every exported briefing.
3. **People → Add someone** — one entry per reviewer:
   - **Director** — reads briefings. Cannot upload or generate. This is the
     right role for most people you are showing it to.
   - **Company secretary** — uploads packs and generates briefings.
   - **Administrator** — also manages people.
4. Set each person a password and send it to them directly. It is stored as a
   one-way hash and cannot be read back, so note it before leaving the screen.

Send each reviewer three things: the address, their email, and their password.

### Give them something to look at

A reviewer handed an empty screen has nothing to react to. Either upload the
sample pack yourself first so a finished briefing is waiting for them, or
generate one from a pack of your own. To create the sample pack locally:

```bash
cd backend && python scripts/make_sample_pack.py ../sample_pack
```

Then upload those four files under a meeting and press **Generate briefing**.
It takes about ninety seconds.

---

## Running it

```bash
cd ~/BoardAgent/deploy

docker compose -f docker-compose.prod.yml ps         # what is running
docker compose -f docker-compose.prod.yml logs -f    # follow the logs
docker compose -f docker-compose.prod.yml restart    # restart
docker compose -f docker-compose.prod.yml down       # stop (data is kept)
```

**Update after changing the code on your laptop:**

```bash
# on your laptop
bash deploy/package.sh
scp -i <key> /tmp/boardlens-deploy.tar.gz ubuntu@YOUR_SERVER_IP:~/

# on the server
tar xzf ~/boardlens-deploy.tar.gz -C ~/BoardAgent
cd ~/BoardAgent/deploy && bash start.sh
```

Your `.env` and all uploaded data are untouched by this — the archive excludes
both, and the data lives in a Docker volume rather than the source tree.

**Back up everything** — database, uploaded packs, indexes:

```bash
docker run --rm -v deploy_boardlens-data:/data -v $(pwd):/backup alpine \
  tar czf /backup/boardlens-backup-$(date +%F).tar.gz -C /data .
```

Keep a copy of `BOARDLENS_ENCRYPTION_KEY` somewhere safe and separate. The
backup is encrypted with it; without the key the archive is unreadable.

---

## If it does not come up

| Symptom | Cause | Fix |
|---|---|---|
| Browser cannot connect | Ports 80/443 closed | Check the Oracle Security List rules **and** the `iptables` lines above |
| Certificate warning, or Caddy retrying | DNS not pointing at the server yet | `ping your-hostname` should return the server IP; wait, then `docker compose restart caddy` |
| Sign-in rejected | Password mismatch | The bootstrap account is created **only on first start**. If you changed `.env` afterwards, it did not take effect |
| "No model provider credentials" on the pack | Key missing or a placeholder | Check `GEMINI_API_KEY` in `.env`, then `docker compose up -d` |
| Briefing fails partway | Free-tier rate limit | The error is shown on the meeting. Wait a few minutes and press Generate again |
| Upload rejected as too large | Above the limit | Raise `BOARDLENS_MAX_UPLOAD_MB`, and `max_size` in the `Caddyfile` to match |

---

## Before real board packs

This setup is fine for testing with synthetic material. Before a genuine pack:

- Move off the free model tier and read `../docs/security.md`
- Consider a regional endpoint (Vertex AI / Bedrock, Mumbai) so content stays
  in-country
- Change the bootstrap password, and remove any test accounts from **People**
- Set up automated backups rather than the manual command above
- Put rate limiting in front of sign-in — there is none today
