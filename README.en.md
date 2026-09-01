# XGlow (X拾光)

[简体中文](README.md)

A self-hosted **local reader and incremental archive** for X / Twitter. Posts, media, and access control stay on hardware you operate. The public site and the admin console are separate surfaces.

XGlow does not call the official paid X API. It uses your own web-session cookies and [twscrape](https://github.com/vladkens/twscrape) to read timelines, then stores text, profiles, images, video, and GIFs in SQLite and on disk.

> Unofficial web endpoints can break when the platform changes, rate-limits, or re-validates login. They may also conflict with X’s current terms. Use only your own session, archive content you are allowed to keep, at a modest cadence, and never share the `data/` directory.

License: [GNU Affero General Public License v3.0](LICENSE)

Source: https://github.com/realjuemie/XGlow

---

## Capabilities

**Reading**

- Account directory (banner or compact cards) and per-account timelines
- Simplified Chinese / English; preference is stored in the browser
- Desktop, tablet, phone, and Telegram Mini App layouts; light/dark follows the OS or client, with a manual toggle
- Filters for original posts, replies, reposts, media, year/month, plus local full-text search
- Replies render as a conversation card (parent context + current reply); `@handles` open X
- Image lightbox and local video playback

**Access control**

- Dedicated admin console (no public entry point); password is set on first visit
- Accounts may be public or hidden; hidden accounts are visible only to the admin and granted members
- Member accounts, per-member readable sets, personal Bark / Telegram notification subscriptions
- Read-only share links from 5 minutes to 90 days (the server stores only a hash of the token)

**Ingest and notifications**

- Cookie paste, live validation, multiple sessions; the pool prefers the **least-recently-used** session so traffic is not stacked on one account
- HTTP / HTTPS / SOCKS5 proxy
- Manual sync for one account or all accounts; failed items can be retried without touching healthy ones
- Scheduled incremental sync (5 minutes–7 days)
- Bark and a Telegram bot / Mini App for new-content alerts, credential failure alerts, and membership commands

**Deployment**

- Windows setup scripts (venv, optional LAN-only firewall rule)
- Docker / NAS via `compose.yaml`, with a dedicated data volume

---

## Requirements

- Python **3.10+** (3.12 recommended)
- Egress to X (a proxy is typical)
- For Docker: image builds, and a persistent `./data` directory

---

## Windows

1. Install Python with **Add Python to PATH**.
2. Run `setup-windows.ps1` from the project root (creates `.venv`, installs `requirements.txt`).
3. Double-click `start-windows.cmd`. The public site defaults to:

```text
http://127.0.0.1:8787
```

Leave the terminal running; `Ctrl+C` stops the server. The process listens on all interfaces. Other devices on the LAN can use the address printed at startup, for example `http://192.168.1.20:8787`. Running setup as Administrator adds a Windows firewall rule that allows TCP 8787 from the local subnet only.

| Path | Role |
| --- | --- |
| `/` | Account directory |
| `/reader?account=1` | Reader for one account |
| `/login` | Member sign-in |
| `/admin` | Administration |

---

## Docker

```yaml
# compose.yaml is included
services:
  reader:
    build: .
    ports:
      - "8787:8787"
    volumes:
      - ./data:/data
```

```bash
docker compose up -d --build
```

The image **COPY**s application code; only `./data` is bind-mounted. After changing Python or front-end files, **rebuild** and `--force-recreate`. A plain `restart` will not pick up those changes. Inside the container, `127.0.0.1` is the container itself—point the proxy at the host or gateway LAN address.

---

## Configuration

Open `/admin` once and set an administrator password of at least 10 characters (stored as a one-way hash in `data/admin-auth.json`).

**Proxy**  
Enter an `http://`, `https://`, or `socks5://` URL, test, then save. Cookie checks, timelines, and media downloads all use it.

**Scrape sessions (cookies)**  
While logged into `https://x.com`, copy cookies, request headers, cURL, or JSON. The console extracts `auth_token` and `ct0` into `data/scraper-sessions.db` and never echoes the raw secret. You may keep several sessions; requests rotate by last-used time. Protected accounts require **at least one cookie whose X user follows the target**. Otherwise the timeline fails instead of succeeding empty.

**Reading accounts**  
These are distinct from scrape sessions: the former are profiles you archive (many), the latter is your own login. Public listing, replies, and reposts are per-account toggles.

**Members and shares**  
Members sign in at `/login` and see assigned accounts (plus public ones unless they hide that list). A temporary share grants read-only access to a single account and expires on its own.

**Bark / Telegram**  
Bark fires only when an incremental cursor already exists and the round actually inserted posts—the first full archive does not flood the phone. The Telegram Mini App needs an HTTPS origin and a bot token; the token and webhook secret are not returned by the admin API.

---

## Incremental sync

- **Initial fetch limit**: cap for the first archive, before a cursor exists.
- **Incremental scan limit**: maximum timeline items pulled from X in this round (not “max rows to save”). The UI minimum is 40.
- The crawler stops after a streak of tweets **already in the database**, not when `id <= max(id)`. A same-second burst can omit one post; a high-water snowflake would skip that hole forever. Reposts that are not stored do not advance the cursor.
- Extra cookies are spare credentials for the same serial scan, not a second crawler. When quota is exhausted, the rest of the batch is skipped so the second session is not burned in the same pass.

---

## Data and security

| Path | Contents |
| --- | --- |
| `data/reader.db` | Accounts, tweets, members, hashed share tokens |
| `data/scraper-sessions.db` | Scrape sessions |
| `data/settings.json` | Proxy, schedule, notifications |
| `data/admin-auth.json` | Admin password hash |
| `data/media/`, `data/profiles/` | Media and avatars |

Do not commit or share `data/`. Authorization applies to listings, tweet APIs, and on-disk file paths.

---

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
python -m unittest tests.test_core
```

Environment: `HOST`, `PORT` (default `0.0.0.0:8787`), `DATA_DIR`, `NO_BROWSER=1`.

---

## Acknowledgements

Ingest is built on [twscrape](https://github.com/vladkens/twscrape). This project is not affiliated with X Corp. You are responsible for compliance and account risk.
