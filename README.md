# qltt-bot

A Telegram bot that helps a Vietnamese market-surveillance officer (QLTT) look up administrative
penalties. The officer types a situation in plain Vietnamese; the bot answers with the violation,
the fine (by value / quantity, individual vs. organisation), aggravating circumstances, additional
penalties, remedial measures, and the legal basis cited down to the point (điểm), in the wording
used in official violation reports.

Documents come from thuvienphapluat.vn (TVPL). The officer maintains the document list in a Google
Sheet and the .docx files in a Google Drive folder; the bot reads both (read-only) and keeps
everything else in Postgres.

## How it works

1. **Sync** (`qltt dong-bo`, `/dongbo`): read the Sheet and Drive, download new or changed files,
   parse each .docx into articles (Điều), clauses (khoản) and points (điểm), run sanity checks
   (gate), store chunks, then recompute the whole store: which documents are in force, which are
   superseded by a consolidated text (VBHN) or a replacing decree, amendment relations, fine
   tables, cross-references, and embeddings.
2. **Answer** (LangGraph pipeline): classify and rewrite the question with an LLM, hybrid search
   (pgvector + Postgres full-text, merged with RRF), let the LLM pick the matching violation(s),
   then read fines and measures from parsed tables, not from the LLM.
3. **Cite**: the "📋 Quy định tại" button builds the full legal basis from VBHN footnotes and
   amendment records, e.g. "điểm b khoản 1 Điều 31 Nghị định số 119/2017/NĐ-CP … được sửa đổi,
   bổ sung tại khoản 48 Điều 2 Nghị định số 126/2021/NĐ-CP …", with links to every related
   document.
4. **Warn**: amendments not yet consolidated, repeals and temporary suspensions (resolutions) are
   shown as ⚠️ lines.
5. **Feedback**: the "⚠️ Báo sai" button records what was wrong and the correct basis; the admin
   gets a copy and can turn it into an eval case.

## Requirements

- uv: https://docs.astral.sh/uv/
- Docker (Docker Desktop on Windows / macOS)
- An OpenRouter API key (LLM + embeddings), a Google service account, a Telegram bot token

## First run (development)

```
uv sync
copy .env.example .env        (macOS / Linux: cp .env.example .env)
```

Fill in `.env` (at least `POSTGRES_PASSWORD`, `LLM_API_KEY`, `SHEET_ID`, `FOLDER_ID`; Telegram
settings for the bot). Then:

```
docker compose up -d --wait db
uv run qltt db init
uv run pytest
uv run qltt dong-bo
uv run qltt hoi "bán bánh kẹo trị giá 7 triệu không có nhãn"
```

If port 5432 is taken, set `DB_PORT` in `.env` (e.g. 5433). The Postgres password is applied only
when the volume is first created; changing it in `.env` later does not change it in Postgres.

Never commit `.env`, `secrets/` or `data/` (all in `.gitignore`). Never paste keys or tokens into
chat.

## Telegram bot

```
uv run qltt bot
```

`.env`:

| Variable | Meaning |
|---|---|
| `TELEGRAM_TOKEN` | from @BotFather |
| `TELEGRAM_CHO_PHEP` | comma-separated chat_ids allowed to use the bot; others are ignored and their chat_id is logged |
| `TELEGRAM_ADMIN` | chat_id that receives errors, error reports, `/dongbo` reports and copies of questions (empty: none) |
| `TELEGRAM_THEO_DOI` | `true` (default): admin gets a copy of every question and answer from other users |
| `TELEGRAM_PROXY` | optional proxy if api.telegram.org is blocked |

Bot commands: `/start`, `/help`, `/dongbo` (sync), `/vanban <document number>` (status of a
document, e.g. `/vanban 98/2020/NĐ-CP`). Buttons under each answer: "📋 Quy định tại" (full legal
basis, tap to copy) and "⚠️ Báo sai" (report an error).

To run it 24/7 on a VPS or a home server, see [DEPLOY.md](DEPLOY.md).

## CLI

| Command | What it does |
|---|---|
| `qltt db init [--xoa-dan-xuat]` | create extensions, tables, indexes (idempotent); `--xoa-dan-xuat` drops derived tables first |
| `qltt google kiem-tra` | test access to the Sheet and Drive folder, match TVPL ids on both sides |
| `qltt google tai` | download .docx files that have no local copy (`data/raw/{id}/{md5}.docx`) |
| `qltt parse kiem-tra` | parse downloaded files, run the gate, write `data/parse/{id}.json` |
| `qltt nap [--lam-lai]` | sync without embeddings; `--lam-lai` re-parses unchanged files |
| `qltt dong-bo [--full] [--khong-embed]` | full sync: plan, load changes, recompute, embed, report |
| `qltt embed` | embed chunks that have no vector yet (cache first, pay only for misses) |
| `qltt van-ban [query]` | list documents: in use or why not, amended / suspended by which documents |
| `qltt hoi "question"` | ask like the officer would; prints answer, timing, cost; logs to chat_log |
| `qltt nhat-ky [--so N] [--theo-doi] [--tat-ca]` | show what users asked and what the bot answered; `--theo-doi` follows live |
| `qltt bot` | run the Telegram bot (long polling) |
| `qltt tim "question"` | show search candidates for one question |
| `qltt sua-doi [--van-ban]` | rebuild amendment relations; report amendments not in any VBHN |
| `qltt dan-chieu [--tat-ca]` | rebuild cross-references; report referenced documents missing from the store |
| `qltt muc-phat` | rebuild fine and measure tables; report coverage |
| `qltt do-thi` | print the answer graph (Mermaid) |
| `qltt bao-sai them / ds / xu-ly / thanh-case` | record, list, close error reports; turn them into eval cases |
| `qltt eval kiem-tra / tim-kiem / phan-loai / tra-loi / quy-dinh / tong` | evaluation (see `eval/README.md`) |
| `uv run pytest` | tests; DB tests use a separate `qltt_test` database and are skipped if Postgres is down |
| `uv run ruff check .` / `uv run ruff format .` | lint and format |

## Layout

```
src/qltt/
  config.py      settings from environment / .env
  db.py          connection, schema init, table categories
  schema.sql     all tables
  tvpl.py        TVPL document id from links and file names
  google_io.py   read the Sheet, list and download Drive files (read-only)
  kho_file.py    local copies of .docx files
  parse.py       .docx → header, articles, clauses, points, appendices, VBHN footnotes
  gate.py        post-parse sanity checks
  chunk.py       article / clause chunks and their roles
  nap.py         load one document; recompute status for the whole store
  dong_bo.py     Sheet + Drive → DB sync, report, document status
  sua_doi.py     amendment relations and per-clause amendment details, warnings
  dan_chieu.py   cross-references to other documents
  muc_phat.py    fine table (tiers by value / quantity, multipliers)
  bien_phap.py   additional penalties and remedial measures
  can_cu.py      "Quy định tại" legal-basis strings in report style
  embed.py       embeddings via an OpenAI-compatible API (OpenRouter)
  tim_kiem.py    hybrid search (vector + full-text, RRF)
  viet_lai.py    question rewriting and classification (LLM)
  ngu_canh.py    context for the selection step
  tra_loi.py     answer one question (violation flow, plain-text output)
  quy_dinh.py    answer questions about regulations, verify quotes
  do_thi.py      LangGraph wiring
  llm.py         LLM calls with cache, token and cost tracking
  hien_thi.py    Telegram HTML answer and the "Quy định tại" message
  nhat_ky.py     chat_log and error reports
  bot.py         Telegram bot
  cli.py         `qltt` command
tests/
eval/                    evaluation cases (see eval/README.md)
compose.yaml             Postgres 16 + pgvector, and the bot service for servers
compose.override.yaml    dev only: expose Postgres on 127.0.0.1
Dockerfile               bot image
docs/, scripts/          survey data and scripts (Nov 2026), not part of the package
```

## Table categories

| Category | Tables | Rule |
|---|---|---|
| Derived | van_ban, chunk, sua_doi, sua_doi_chi_tiet, chu_thich_vbhn, quan_he_van_ban, dan_chieu, muc_phat, bien_phap | rebuilt from Sheet + Drive; rebuild commands may drop them |
| Source | chat_log, bao_sai, xac_nhan, nhat_ky_dong_bo | cannot be rebuilt; never dropped automatically; must be backed up |
| Cache | embed_cache, llm_cache | rebuildable but costs API money; kept across rebuilds |

Source and cache tables have no foreign keys to derived tables and do not store their
auto-increment ids. When adding a table, declare it in `schema.sql` and categorise it in `db.py`
(a test fails if you forget).

## Google Cloud (one-time, with the officer's Google account)

1. Go to https://console.cloud.google.com and create a project.
2. Enable the Google Sheets API and Google Drive API for it
   (https://developers.google.com/workspace/guides/enable-apis).
3. IAM & Admin > Service Accounts > Create service account. Name it, click Done. No role needed.
4. Open the service account > Keys > Add key > Create new key > JSON. The downloaded file is the
   only copy.
5. Save it as `secrets/google-sa.json` in the repo. Never send it by chat, email or git.
6. In Drive, share the documents folder with the service account email as Viewer.
7. In `.env`, set `SHEET_ID` (between `/d/` and `/edit` in the sheet link) and `FOLDER_ID` (after
   `/folders/` in the link of the "Văn bản" subfolder).
8. Run `uv run qltt google kiem-tra`. Done when it reports all 7 columns and the file count matches
   the sheet rows.

If step 4 says key creation is not allowed, the account belongs to an organisation that blocks
service-account keys; stop and ask for help.
