import pytest
from typer.testing import CliRunner

from qltt import google_io
from qltt.cli import app
from qltt.config import cau_hinh

chay = CliRunner()


@pytest.fixture
def moi_truong_gia(monkeypatch, tmp_path):
    """Chạy lệnh trong thư mục tạm, không đụng tới .env thật."""
    monkeypatch.chdir(tmp_path)
    for bien in ("POSTGRES_PASSWORD", "SHEET_ID", "FOLDER_ID", "GOOGLE_SA_KEY"):
        monkeypatch.delenv(bien, raising=False)
    cau_hinh.cache_clear()
    yield monkeypatch
    cau_hinh.cache_clear()


def test_help_liet_ke_nhom_lenh():
    kq = chay.invoke(app, ["--help"])
    assert kq.exit_code == 0
    assert "db" in kq.output and "google" in kq.output


def test_thieu_cau_hinh_thi_bao_ten_bien(moi_truong_gia):
    kq = chay.invoke(app, ["db", "init"])
    assert kq.exit_code == 1
    assert "POSTGRES_PASSWORD" in kq.output
    assert "Traceback" not in kq.output


def test_google_kiem_tra_bao_cho_lech(moi_truong_gia, tmp_path):
    (tmp_path / "khoa.json").write_text("{}")
    moi_truong_gia.setenv("POSTGRES_PASSWORD", "x")
    moi_truong_gia.setenv("SHEET_ID", "s")
    moi_truong_gia.setenv("FOLDER_ID", "f")
    moi_truong_gia.setenv("GOOGLE_SA_KEY", str(tmp_path / "khoa.json"))
    dong = [
        {"dong": 2, "so_hieu": "98/2020/NĐ-CP", "ngay_ban_hanh": 44069, "con_hieu_luc": True,
         "link_tvpl": "https://x/a-406627.aspx"},
        {"dong": 3, "so_hieu": "17/2022/NĐ-CP", "ngay_ban_hanh": "31/01/2022", "con_hieu_luc": True,
         "link_tvpl": "https://x/b-502253.aspx"},
    ]  # fmt: skip
    files = [
        {"name": "98_2020_ND-CP_406627.docx", "md5Checksum": "a"},
        {"name": "24_2025_ND-CP_m_644186.docx", "md5Checksum": "b"},
    ]
    moi_truong_gia.setattr(google_io, "email_service_account", lambda: "bot@x.iam")
    moi_truong_gia.setattr(google_io, "doc_sheet", lambda: dong)
    moi_truong_gia.setattr(google_io, "liet_ke_file", lambda: files)

    kq = chay.invoke(app, ["google", "kiem-tra"])

    assert kq.exit_code == 0, kq.output
    assert "1 văn bản khớp" in kq.output
    assert "Dòng chưa có file (1): 17/2022/NĐ-CP (502253)" in kq.output
    assert "File chưa có dòng (1): 24_2025_ND-CP_m_644186.docx" in kq.output
    assert "không phải kiểu ngày (1): 3" in kq.output


def test_google_tu_choi_thi_goi_y_share(moi_truong_gia, tmp_path, gia_lap_google):
    (tmp_path / "khoa.json").write_text("{}")
    moi_truong_gia.setenv("GOOGLE_SA_KEY", str(tmp_path / "khoa.json"))
    moi_truong_gia.setattr(google_io, "email_service_account", lambda: "bot@x.iam")
    loi = {"error": {"code": 403, "message": "The caller does not have permission"}}
    gia_lap_google([(403, loi)])

    kq = chay.invoke(app, ["google", "kiem-tra"])

    assert kq.exit_code == 1
    assert "Google trả lỗi 403: The caller does not have permission" in kq.output
    assert "share thư mục cho bot@x.iam" in kq.output
    assert "Traceback" not in kq.output
