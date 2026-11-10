"""Fixture dùng chung.

Test cần Postgres chạy trên database riêng qltt_test và tự bỏ qua nếu chưa bật
`docker compose up -d db` hoặc chưa có .env.
"""

import json

import psycopg
import pytest
from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence
from pydantic import ValidationError

from qltt import db, google_io
from qltt.config import cau_hinh

DB_TEST = "qltt_test"


@pytest.fixture(scope="session")
def csdl_test() -> str:
    try:
        conn = db.ket_noi()
    except (psycopg.OperationalError, ValidationError) as e:
        pytest.skip(f"cần Postgres đang chạy ({type(e).__name__})")
    with conn:
        conn.autocommit = True  # CREATE DATABASE không chạy được trong transaction
        co = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [DB_TEST]).fetchone()
        if not co:
            conn.execute(f'CREATE DATABASE "{DB_TEST}"')
    return DB_TEST


@pytest.fixture
def conn(csdl_test):
    """Kết nối tới qltt_test; mọi thay đổi của test bị hủy khi test xong."""
    c = db.ket_noi(dbname=csdl_test)
    # Mở sẵn một transaction: transaction() bên trong code thành savepoint, không tự commit,
    # nên rollback cuối test hủy được cả thay đổi schema.
    c.execute("SELECT 1")
    try:
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture
def gia_lap_google(monkeypatch):
    """Dùng thư viện Google thật nhưng thay mạng bằng dãy câu trả lời có sẵn.

    Gọi gia_lap_google([(200, {...}), ...]); trả về đối tượng ghi lại các request đã gửi.
    """

    def tao(tra_loi: list[tuple[int, dict | bytes]]) -> HttpMockSequence:
        # nd là dict → trả JSON; bytes → trả nguyên nội dung (tải file)
        http = HttpMockSequence(
            [
                ({"status": str(ma)}, nd if isinstance(nd, bytes) else json.dumps(nd))
                for ma, nd in tra_loi
            ]
        )
        monkeypatch.setenv("POSTGRES_PASSWORD", "x")
        monkeypatch.setenv("SHEET_ID", "ma_sheet")
        monkeypatch.setenv("SHEET_TAB", "Van_ban")
        monkeypatch.setenv("FOLDER_ID", "ma_thu_muc")
        cau_hinh.cache_clear()
        monkeypatch.setattr(google_io, "_creds", lambda: None)
        monkeypatch.setattr(
            google_io,
            "build",
            lambda ten, ban, **_: build(ten, ban, http=http, cache_discovery=False),
        )
        return http

    yield tao
    cau_hinh.cache_clear()
