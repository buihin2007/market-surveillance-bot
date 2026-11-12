# Triển khai bot lên máy chạy 24/24

Máy chủ chạy 2 container bằng Docker: `db` (Postgres + pgvector) và `bot` (`qltt bot`). Cả hai
tự chạy lại khi máy khởi động hoặc khi bot lỗi (`restart: unless-stopped`).

## 0. Chọn máy

| | VPS | Máy ở nhà |
| --- | --- | --- |
| Cấu hình đủ dùng | 1 vCPU, 2 GB RAM, 20 GB ổ | như trên |
| Hệ điều hành | Ubuntu 24.04 | Ubuntu (khuyên dùng) hoặc Windows + Docker Desktop |
| Ưu | luôn bật, IP ổn định | không tốn tiền thuê |
| Nhược | ~5 USD/tháng | mất điện / mạng thì bot im; Windows phải tự đăng nhập và không ngủ |

Bot chỉ gọi ra ngoài (Telegram, OpenRouter, Google), không cần mở cổng nào vào máy.

## 1. Cài trên máy chủ

Ubuntu:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # đăng xuất, đăng nhập lại
sudo apt install -y git
```

Windows ở nhà: cài Docker Desktop, bật *Start Docker Desktop when you sign in*; Windows bật tự
đăng nhập và tắt Sleep (Power settings → Sleep: Never).

## 2. Lấy code

```bash
git clone <repo> qltt-bot && cd qltt-bot
```

Chưa có repo trên GitHub thì chép cả thư mục, bỏ `.venv/`, `.git/` và `data/` (trừ `data/raw/`).

## 3. Chép bí mật bằng tay (không qua git, không qua chat)

Từ máy dev sang máy chủ: `.env` và `secrets/google-sa.json`.

```powershell
scp .env user@may-chu:~/qltt-bot/.env
scp secrets/google-sa.json user@may-chu:~/qltt-bot/secrets/google-sa.json
```

`.env` giữ nguyên như máy dev. `DB_HOST`, `DB_PORT` được compose đặt lại cho container.

## 4. Chuyển dữ liệu từ máy dev

Mang theo nhật ký hỏi đáp, báo sai và cache vector, nên không phải nạp và embed lại.

Trên máy dev (PowerShell, trong thư mục repo):

```powershell
docker compose exec db pg_dump -U qltt -Fc -f /tmp/qltt.dump qltt
docker compose cp db:/tmp/qltt.dump ./qltt.dump
scp qltt.dump user@may-chu:~/qltt-bot/
scp -r data/raw user@may-chu:~/qltt-bot/data/
```

(Không dùng `pg_dump ... > qltt.dump` trong PowerShell: dấu `>` làm hỏng file nhị phân.)

Trên máy chủ:

```bash
docker compose up -d db
docker compose cp qltt.dump db:/tmp/qltt.dump
docker compose exec db pg_restore -U qltt -d qltt --clean --if-exists --no-owner /tmp/qltt.dump
```

Không muốn chuyển: `docker compose run --rm bot qltt db init` rồi
`docker compose run --rm bot qltt dong-bo` (tải lại từ Drive, embed lại toàn bộ, mất nhật ký cũ).

## 5. Chạy

Tắt bot trên máy dev trước (Ctrl+C). Một token chỉ chạy được một bot, hai nơi cùng chạy sẽ báo
lỗi `Conflict`.

```bash
docker compose up -d --build
docker compose logs -f bot      # thấy "Bot chạy với 2 người được phép" là xong; Ctrl+C thoát xem log
```

Thử trên Telegram: `/vanban 98/2020/NĐ-CP`, rồi hỏi một tình huống.

## 6. Vận hành hằng ngày

| Việc | Lệnh (trên máy chủ, trong thư mục repo) |
| --- | --- |
| Xem log bot | `docker compose logs -f --tail 100 bot` |
| Xem chú hỏi gì | `docker compose exec bot qltt nhat-ky --theo-doi` |
| Đồng bộ bằng tay | `docker compose exec bot qltt dong-bo` (hoặc `/dongbo` trên Telegram) |
| Tình trạng văn bản | `docker compose exec bot qltt van-ban 98/2020` |
| Khởi động lại bot | `docker compose restart bot` |
| Sửa `.env` | sửa xong chạy `docker compose up -d bot` |
| Cập nhật code | `git pull && docker compose up -d --build bot` |

Cập nhật có đổi `schema.sql`: chạy thêm `docker compose exec bot qltt db init`.

## 7. Sao lưu

Mỗi tuần (hoặc trước khi cập nhật):

```bash
docker compose exec db pg_dump -U qltt -Fc -f /tmp/qltt.dump qltt
mkdir -p sao_luu
docker compose cp db:/tmp/qltt.dump ./sao_luu/qltt-$(date +%F).dump
```

Kho văn bản dựng lại được từ Drive. Thứ không dựng lại được là `chat_log` và `bao_sai`
(câu chú hỏi, chỗ chú báo sai), nên vẫn cần sao lưu.

Sau khi chuyển: máy dev có DB riêng, không tự cập nhật theo máy chủ. Muốn thử trên máy dev với
dữ liệu mới thì làm ngược lại bước 4.
