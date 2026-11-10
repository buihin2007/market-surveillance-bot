# qltt-bot

Chatbot tra cứu xử phạt vi phạm hành chính lĩnh vực quản lý thị trường, kênh Telegram.
Trạng thái: xong GĐ 0 (nền). Chưa có parse, tìm kiếm, /ask, bot.

## Cần cài

- uv: https://docs.astral.sh/uv/
- Docker Desktop

## Chạy lần đầu

```
uv sync
copy .env.example .env        (macOS / Linux: cp .env.example .env)
```

Mở `.env`, điền `POSTGRES_PASSWORD` (máy dev: chữ và số bất kỳ). Rồi:

```
docker compose up -d --wait db
uv run qltt db init
uv run pytest
```

`uv run qltt db init` in ra phiên bản Postgres, 3 extension (vector, unaccent, pg_trgm) và 10 bảng là xong.

Nếu Docker báo cổng 5432 đã có chương trình khác dùng: đổi `DB_PORT` trong `.env` (ví dụ 5433) rồi chạy lại.

Lưu ý: mật khẩu chỉ được áp vào Postgres ở lần chạy đầu tiên (lúc tạo volume). Đổi mật khẩu trong `.env` sau đó thì Postgres vẫn giữ mật khẩu cũ.

## Lệnh

| Lệnh | Việc |
|---|---|
| `uv run qltt db init` | tạo extension, bảng, index; chạy lại nhiều lần không sao |
| `uv run qltt db init --xoa-dan-xuat` | xóa các bảng dẫn xuất rồi tạo lại; bảng gốc và cache giữ nguyên |
| `uv run qltt google kiem-tra` | đọc thử sheet + thư mục Drive, đối chiếu mã TVPL giữa hai bên |
| `uv run pytest` | test; phần cần Postgres chạy trên database riêng `qltt_test`, tự bỏ qua nếu db chưa chạy |
| `uv run ruff check .` và `uv run ruff format .` | lint và format |

## Cấu trúc

```
src/qltt/
  config.py      đọc biến môi trường và .env
  db.py          kết nối, khởi tạo schema, danh sách 3 loại bảng
  schema.sql     toàn bộ bảng
  tvpl.py        mã TVPL từ link và từ tên file
  google_io.py   đọc Sheet, liệt kê Drive (chỉ đọc)
  cli.py         lệnh qltt
tests/
compose.yaml             Postgres 16 + pgvector
compose.override.yaml    chỉ cho máy dev: mở cổng Postgres ở 127.0.0.1
docs/, scripts/          số liệu và script khảo sát 49 văn bản (05/11/2026), không thuộc gói qltt
```

Không commit: `.env`, `secrets/`, `data/` (đã có trong `.gitignore`).

## Ba loại bảng

| Loại | Bảng | Quy tắc |
|---|---|---|
| Dẫn xuất | van_ban, chunk, sua_doi, chu_thich_vbhn, quan_he_van_ban, dan_chieu | dựng lại được từ Sheet + Drive; lệnh rebuild được xóa |
| Gốc | chat_log, xac_nhan, nhat_ky_dong_bo | không dựng lại được; không xóa tự động; phải có trong backup |
| Cache | embed_cache | dựng lại được nhưng tốn tiền API; giữ qua các lần rebuild |

Bảng gốc và cache không có khóa ngoại tới bảng dẫn xuất và không lưu id tự tăng của bảng dẫn xuất. Thêm bảng mới: khai báo trong `schema.sql` và xếp loại trong `db.py` (có test bắt nếu quên).

## Google Cloud (làm một lần, bằng tài khoản Google của chú)

1. Vào https://console.cloud.google.com, tạo một project.
2. Bật hai API cho project đó: Google Sheets API và Google Drive API (hướng dẫn: https://developers.google.com/workspace/guides/enable-apis).
3. Menu > IAM & Admin > Service Accounts > Create service account. Đặt tên, bấm Done. Không cần gán role.
4. Bấm vào email của service account > tab Keys > Add key > Create new key > JSON > Create. File tải về là bản duy nhất, không tải lại được.
5. Tạo thư mục `secrets` trong repo, đặt file vào đó với tên `google-sa.json`. Không gửi file này qua chat, email, git.
6. Trên Drive, share thư mục "Văn bản Quy phạm & Xử Phạt" cho email của service account, quyền Người xem.
7. Điền vào `.env`:
   - `SHEET_ID`: đoạn giữa `/d/` và `/edit` trong link của sheet.
   - `FOLDER_ID`: đoạn sau `/folders/` trong link của thư mục con "Văn bản".
8. Chạy `uv run qltt google kiem-tra`. Xong khi lệnh báo đủ 7 cột và số văn bản khớp bằng số dòng trên sheet.

Nếu bước 4 báo không được phép tạo key: tài khoản đang thuộc một tổ chức có chính sách chặn tạo key. Dừng ở đó và báo lại.
