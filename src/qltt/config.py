"""Cấu hình: đọc từ biến môi trường, trên máy dev đọc thêm file .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CauHinh(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres. Tên biến môi trường = tên trường viết hoa, ví dụ POSTGRES_PASSWORD.
    postgres_password: SecretStr
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "qltt"
    db_user: str = "qltt"

    # Google, chỉ quyền đọc
    google_sa_key: Path = Path("secrets/google-sa.json")
    sheet_id: str = ""
    sheet_tab: str = "Van_ban"
    folder_id: str = ""  # thư mục "Văn bản" trên Drive

    # bản sao docx trên máy, dựng lại được từ Drive
    thu_muc_raw: Path = Path("data/raw")

    # LLM + embedding qua API kiểu OpenAI (mặc định OpenRouter). Đổi model chỉ cần sửa .env.
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://openrouter.ai/api/v1"
    # Đổi model: sửa .env rồi chạy `qltt embed`; vector model cũ còn trong cache nên đổi ngược
    # không tốn tiền.
    # 10/11/2026: bge-m3 recall@20 câu đời thường 0,77 so với 0,46 của text-embedding-3-small.
    embed_model: str = "baai/bge-m3"
    embed_gia_1m_token: float = 0.01  # USD, chỉ để in ước tính chi phí
    # LLM (viết lại câu hỏi; GĐ 2: trả lời). 11/11/2026, prompt v2, câu đời thường: DeepSeek V4.1
    # Flash tắt suy nghĩ 35/39 (giữ lại 6/9), ngang gemini-3.1-flash-lite 35/39 (7/9) nhưng rẻ hơn
    # ~20 lần. Dự phòng: LLM_MODEL=google/gemini-3.1-flash-lite.
    llm_model: str = "deepseek/deepseek-v4.1-flash"
    # Tắt chế độ suy nghĩ (reasoning effort none). Model bắt buộc suy nghĩ thì đặt false.
    llm_tat_suy_nghi: bool = True
    # Giá chỉ dùng khi API không trả chi phí thật (usage.cost); OpenRouter luôn trả.
    llm_gia_1m_vao: float = 0.006
    llm_gia_1m_ra: float = 0.50
    # Prompt viết lại: v1 | v2 (+ định nghĩa) | v3 (+ danh mục hành vi) | v4 (cả hai) |
    # v5 (v2 + phân loại câu hỏi). 11/11/2026, DeepSeek V4.1 Flash: v5 phân loại 60/60, câu đời
    # thường Đ@5 36/39 (v2: 35/39) → chọn v5 (qltt-tien-do.md).
    viet_lai_prompt: str = "v5"

    # Telegram (GĐ 4). Token lấy từ @BotFather, KHÔNG dán vào chat / commit.
    telegram_token: SecretStr = SecretStr("")
    # chat_id được dùng bot, cách nhau dấu phẩy (chú, ikm). Người ngoài danh sách: bot im lặng.
    telegram_cho_phep: str = ""
    # chat_id nhận báo lỗi và báo sai (ikm). Trống: không báo.
    telegram_admin: int | None = None
    # Gửi admin bản sao mọi câu hỏi + câu trả lời của người khác (theo dõi thời gian thực).
    telegram_theo_doi: bool = True
    # Telegram bị chặn ở VN: nếu máy chạy bot không tới được api.telegram.org thì đặt proxy,
    # vd http://127.0.0.1:7890 hoặc socks5://127.0.0.1:1080 (socks cần gói httpx[socks]).
    telegram_proxy: str = ""

    @field_validator("telegram_admin", mode="before")
    @classmethod
    def _admin_trong(cls, v):
        return None if isinstance(v, str) and not v.strip() else v  # "TELEGRAM_ADMIN=" → không báo

    @property
    def ds_cho_phep(self) -> set[int]:
        return {int(x) for x in self.telegram_cho_phep.replace(" ", "").split(",") if x}


@lru_cache
def cau_hinh() -> CauHinh:
    return CauHinh()
