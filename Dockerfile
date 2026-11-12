# Image của bot: `docker compose up -d --build` (xem DEPLOY.md).
# Không chứa bí mật: .env và secrets/ được gắn vào lúc chạy, không copy vào image.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

# tzdata: date.today() theo giờ Việt Nam (hiệu lực văn bản tính theo ngày)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Ho_Chi_Minh \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# thư viện trước (ít đổi → dùng lại cache khi chỉ sửa code)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

CMD ["qltt", "bot"]
