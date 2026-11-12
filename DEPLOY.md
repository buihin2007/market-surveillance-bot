# Deploying the bot to a 24/7 machine

The server runs two Docker containers: `db` (Postgres + pgvector) and `bot` (`qltt bot`). Both
restart automatically when the machine boots or the bot crashes (`restart: unless-stopped`).

## 0. Choose a machine

| | VPS | Home machine |
| --- | --- | --- |
| Enough resources | 1 vCPU, 2 GB RAM, 20 GB disk | same |
| OS | Ubuntu 24.04 | Ubuntu (recommended) or Windows + Docker Desktop |
| Pros | always on, stable network | no rental cost |
| Cons | ~5 USD/month | power or network outage = bot offline; Windows must auto-login and never sleep |

The bot only makes outbound connections (Telegram, OpenRouter, Google). No inbound port needs to
be opened.

## 1. Install on the server

Ubuntu:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out and back in
sudo apt install -y git
```

Windows home machine: install Docker Desktop and enable *Start Docker Desktop when you sign in*;
enable automatic sign-in and set Sleep to Never in Power settings.

## 2. Get the code

```bash
git clone <repo> qltt-bot && cd qltt-bot
```

Without a Git remote, copy the whole folder, leaving out `.venv/`, `.git/` and `data/` (except
`data/raw/`).

## 3. Copy secrets by hand (never through git or chat)

From the dev machine to the server: `.env` and `secrets/google-sa.json`.

```powershell
scp .env user@server:~/qltt-bot/.env
scp secrets/google-sa.json user@server:~/qltt-bot/secrets/google-sa.json
```

Keep `.env` as on the dev machine. Compose overrides `DB_HOST` and `DB_PORT` for the container.

## 4. Move the data from the dev machine

This keeps the chat log, error reports and the embedding cache, so nothing has to be re-loaded or
re-embedded.

On the dev machine (PowerShell, in the repo folder):

```powershell
docker compose exec db pg_dump -U qltt -Fc -f /tmp/qltt.dump qltt
docker compose cp db:/tmp/qltt.dump ./qltt.dump
scp qltt.dump user@server:~/qltt-bot/
scp -r data/raw user@server:~/qltt-bot/data/
```

(Do not use `pg_dump ... > qltt.dump` in PowerShell: `>` corrupts binary output.)

On the server:

```bash
docker compose up -d db
docker compose cp qltt.dump db:/tmp/qltt.dump
docker compose exec db pg_restore -U qltt -d qltt --clean --if-exists --no-owner /tmp/qltt.dump
```

To start from scratch instead: `docker compose run --rm bot qltt db init`, then
`docker compose run --rm bot qltt dong-bo` (downloads everything from Drive and re-embeds it all;
the old chat log is lost).

## 5. Run

Stop the bot on the dev machine first (Ctrl+C). One token can only be polled from one place; two
running bots fail with `Conflict`.

```bash
docker compose up -d --build
docker compose logs -f bot      # done when you see "Bot chạy với N người được phép"; Ctrl+C stops following
```

Test in Telegram: `/vanban 98/2020/NĐ-CP`, then ask a situation.

## 6. Day-to-day operation

| Task | Command (on the server, in the repo folder) |
| --- | --- |
| Bot logs | `docker compose logs -f --tail 100 bot` |
| See what users ask | `docker compose exec bot qltt nhat-ky --theo-doi` |
| Sync by hand | `docker compose exec bot qltt dong-bo` (or `/dongbo` in Telegram) |
| Document status | `docker compose exec bot qltt van-ban 98/2020` |
| Restart the bot | `docker compose restart bot` |
| After editing `.env` | `docker compose up -d bot` |
| Update the code | `git pull && docker compose up -d --build bot` |

If an update changes `schema.sql`, also run `docker compose exec bot qltt db init`.

## 7. Backups

Weekly, and before every update:

```bash
docker compose exec db pg_dump -U qltt -Fc -f /tmp/qltt.dump qltt
mkdir -p sao_luu
docker compose cp db:/tmp/qltt.dump ./sao_luu/qltt-$(date +%F).dump
```

The document store can be rebuilt from Drive. What cannot be rebuilt is `chat_log` and `bao_sai`
(the officer's questions and error reports), so back them up.

After the move, the dev machine has its own database and does not follow the server. To test on
the dev machine with current data, run step 4 in the other direction.
