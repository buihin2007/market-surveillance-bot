"""Cấu hình: đọc từ biến môi trường, trên máy dev đọc thêm file .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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
    # LLM (viết lại câu hỏi; GĐ 2: trả lời). Rẻ, nhanh, đọc tiếng Việt tốt.
    llm_model: str = "google/gemini-3.1-flash-lite"
    llm_gia_1m_vao: float = 0.25  # USD / 1 triệu token đầu vào, chỉ để in ước tính
    llm_gia_1m_ra: float = 1.50
    # v1 | v2 (+ định nghĩa) | v3 (+ danh mục hành vi) | v4 (cả hai). Chọn v2 ngày 11/11/2026 theo eval.
    viet_lai_prompt: str = "v2"


@lru_cache
def cau_hinh() -> CauHinh:
    return CauHinh()
