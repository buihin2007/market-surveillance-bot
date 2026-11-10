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


@lru_cache
def cau_hinh() -> CauHinh:
    return CauHinh()
