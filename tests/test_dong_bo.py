"""Đồng bộ trọn vẹn trên Postgres thật (qltt_test) với Sheet / Drive giả."""

import hashlib
from datetime import date

import pytest
from test_nap import HOM_NAY, ND_98
from test_parse import tao_docx

from qltt import db, dong_bo
from qltt.google_io import ngay_tu_serial


def serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def dong_sheet(ma, so, ngay=date(2020, 8, 26), tick=True, hl=None, so_dong=2):
    return {
        "dong": so_dong, "so_hieu": so, "ngay_ban_hanh": serial(ngay), "loai": "Nghị định",
        "con_hieu_luc": tick, "ngay_hieu_luc": serial(hl or ngay), "ngay_het_hieu_luc": "",
        "link_tvpl": f"https://thuvienphapluat.vn/van-ban/x-{ma}.aspx",
    }  # fmt: skip


class Drive:
    """Thư mục Drive giả: tên file → bytes."""

    def __init__(self):
        self.noi_dung: dict[str, bytes] = {}
        self.so_lan_tai = 0

    def them(self, tmp_path, ten, so, dong, ngay="ngày 26 tháng 8 năm 2020"):
        p = tao_docx(tmp_path, dong, so=so, ngay=ngay, ten=ten)
        self.noi_dung[ten] = p.read_bytes()

    def files(self):
        return [
            {"id": ten, "name": ten, "md5Checksum": hashlib.md5(b).hexdigest(),
             "modifiedTime": "2026-11-12T00:00:00Z"}
            for ten, b in self.noi_dung.items()
        ]  # fmt: skip

    def tai(self, f):
        self.so_lan_tai += 1
        return self.noi_dung[f["name"]]


@pytest.fixture
def csdl(conn):
    """dong_bo.chay tự commit (như chạy thật) → dọn sạch sau test để không ảnh hưởng test khác."""
    db.khoi_tao(conn, xoa_dan_xuat=True)
    yield conn
    conn.rollback()
    db.khoi_tao(conn, xoa_dan_xuat=True)
    conn.execute("DELETE FROM nhat_ky_dong_bo")
    conn.commit()


def chay(conn, sheet, drive, raw, **kw):
    return dong_bo.chay(conn, sheet, drive.files(), raw, drive.tai, ngay_tu_serial, HOM_NAY, **kw)


def test_lan_dau_lan_hai_va_cac_truong_hop(csdl, tmp_path):
    raw = tmp_path / "raw"
    drive = Drive()
    drive.them(tmp_path, "98_2020_ND-CP_406627.docx", "98/2020/NĐ-CP", ND_98)
    drive.them(tmp_path, "99_2020_ND-CP_500000.docx", "99/2020/NĐ-CP", ND_98)  # chưa có dòng sheet
    sheet = [dong_sheet(406627, "98/2020/NĐ-CP"), dong_sheet(700000, "1/2026/NĐ-CP", so_dong=3)]

    kq = chay(csdl, sheet, drive, raw, embed_fn=lambda c: "Vector: giả.")
    assert kq.da_nap == ["98/2020/NĐ-CP"] and kq.co_gi_moi
    bc = dong_bo.bao_cao(kq)
    assert "Văn bản mới đã nạp (1):\n  - 98/2020/NĐ-CP" in bc
    assert "Dòng sheet chưa có file trên Drive (1):\n  - 1/2026/NĐ-CP (dòng 3)" in bc
    assert "File trên Drive chưa có dòng sheet (1):\n  - 99_2020_ND-CP_500000.docx" in bc
    assert "Vector: giả." in bc
    nk = csdl.execute("SELECT ket_thuc IS NOT NULL, tom_tat->'da_nap' FROM nhat_ky_dong_bo")
    assert nk.fetchone() == (True, ["98/2020/NĐ-CP"])

    # lần 2: không đổi gì → không tải, không nạp; lỗi cũ vẫn nhắc
    tai_truoc = drive.so_lan_tai
    kq = chay(csdl, sheet, drive, raw)
    assert not kq.co_gi_moi and drive.so_lan_tai == tai_truoc
    assert dong_bo.bao_cao(kq).startswith("Không có gì mới.\nDòng sheet chưa có file")

    # sửa sheet: bỏ tick → báo, văn bản thôi được tra
    sheet[0] = dong_sheet(406627, "98/2020/NĐ-CP", tick=False)
    kq = chay(csdl, sheet, drive, raw)
    assert kq.ke_hoach.doi_sheet == ["98/2020/NĐ-CP: bỏ tick còn hiệu lực"]
    assert not csdl.execute("SELECT dung_de_tra FROM van_ban").fetchone()[0]

    # file đổi trên Drive → nạp lại
    sheet[0] = dong_sheet(406627, "98/2020/NĐ-CP")
    moi = [*ND_98[:-1], "Điều 4. Điều khoản chuyển tiếp", "Điều 5. Hiệu lực thi hành"]
    drive.them(tmp_path, "98_2020_ND-CP_406627.docx", "98/2020/NĐ-CP", moi)
    kq = chay(csdl, sheet, drive, raw)
    assert [v.d.so_hieu for v in kq.ke_hoach.doi_file] == ["98/2020/NĐ-CP"]
    assert csdl.execute("SELECT so_dieu, dung_de_tra FROM van_ban").fetchone() == (5, True)

    # xóa dòng sheet → giữ dữ liệu, thôi tra; thêm lại → tra lại
    kq = chay(csdl, [sheet[1]], drive, raw)
    assert [s for _, s in kq.ke_hoach.go_khoi_sheet] == ["98/2020/NĐ-CP"]
    assert csdl.execute("SELECT go_khoi_sheet, dung_de_tra FROM van_ban").fetchone() == (
        True, False)  # fmt: skip
    kq = chay(csdl, sheet, drive, raw)
    assert csdl.execute("SELECT go_khoi_sheet, dung_de_tra FROM van_ban").fetchone() == (
        False, True)  # fmt: skip


def test_file_nham_ma_va_khoa(csdl, tmp_path):
    raw = tmp_path / "raw"
    drive = Drive()
    drive.them(
        tmp_path, "98_2020_ND-CP_406627.docx", "99/2020/NĐ-CP", ND_98
    )  # file của văn bản khác
    kq = chay(csdl, [dong_sheet(406627, "98/2020/NĐ-CP")], drive, raw)
    assert kq.da_nap == [] and len(kq.nham_ma) == 1
    assert "có thể tải nhầm file" in dong_bo.bao_cao(kq)

    # một tiến trình khác đang giữ khóa
    khac = db.ket_noi(dbname=csdl.info.dbname)
    try:
        khac.execute("SELECT pg_advisory_lock(%s)", [dong_bo.KHOA_DONG_BO])
        kq = chay(csdl, [], drive, raw)
        assert kq.dang_chay and dong_bo.bao_cao(kq).startswith("Đang có một lần đồng bộ")
    finally:
        khac.close()
