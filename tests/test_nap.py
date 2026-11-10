"""Nạp vào Postgres thật (database qltt_test); tự bỏ qua nếu Postgres chưa chạy."""

from datetime import date

import pytest
from test_parse import tao_docx

from qltt import db, nap
from qltt.nap import DongSheet, chi_sua_mot_van_ban, dong_tu_sheet
from qltt.parse import chuan_so_hieu

HOM_NAY = date(2026, 11, 10)


def dong(ma, so, loai="nghi_dinh", ngay=date(2020, 8, 26), **them):
    gt = dict(
        tvpl_id=ma, so_hieu=so, ngay_ban_hanh=ngay, loai=loai, con_hieu_luc=True,
        ngay_hieu_luc=ngay, ngay_het_hieu_luc=None, link_tvpl=f"x-{ma}.aspx", dong=2,
    )  # fmt: skip
    return DongSheet(**(gt | them))


@pytest.fixture
def csdl(conn):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    return conn


ND_98 = [
    "Điều 1. Phạm vi điều chỉnh",
    "Chương II",
    "HÀNH VI VI PHẠM",
    "Điều 2. Buôn bán hàng giả",
    "1. Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng.",
    "2. Hình thức xử phạt bổ sung: tịch thu.",
    "Điều 3. Thẩm quyền xử phạt của Quản lý thị trường",
    "1. Kiểm soát viên thị trường có quyền phạt tiền đến 500.000 đồng.",
    "Điều 4. Hiệu lực thi hành",
]


def nap_docx(conn, tmp_path, d, noi_dung, ten="vb.docx", **kw):
    p = tao_docx(tmp_path, noi_dung, so=d.so_hieu, ten=ten, **kw)
    return nap.nap_van_ban(conn, d, p, f"md5-{ten}", "drive-id")


def test_nap_van_ban_va_chay_lai_khong_nhan_doi(csdl, tmp_path):
    d = dong(406627, "98/2020/NĐ-CP")
    kq = nap_docx(csdl, tmp_path, d, ND_98)
    assert kq.loi == [] and kq.so_chunk == 4 + 3  # 4 Điều + 3 khoản

    nap_docx(csdl, tmp_path, d, ND_98)  # lần 2: thay, không cộng dồn
    nap.tinh_lai(csdl, HOM_NAY)

    v = csdl.execute(
        "SELECT so_chunk, so_dieu, trang_thai, dung_de_tra, vai_tro, qltt_lien_quan, file_hash, ten"
        " FROM van_ban"
    ).fetchone()
    assert v == (7, 4, "hieu_luc", True, "ca_hai", True, "md5-vb.docx", None)
    assert csdl.execute("SELECT count(*) FROM chunk").fetchone()[0] == 7
    khoan = csdl.execute(
        "SELECT k.duong_dan, d.duong_dan, k.vai_tro FROM chunk k JOIN chunk d ON d.id = k.cha_id"
        " WHERE k.duong_dan = 'Điều 2 khoản 1'"
    ).fetchone()
    assert khoan == ("Điều 2 khoản 1", "Điều 2", "xu_phat")
    tim = csdl.execute(
        "SELECT duong_dan FROM chunk WHERE tsv @@ plainto_tsquery('simple', 'hàng giả')"
    ).fetchall()
    assert ("Điều 2",) in tim


def test_gate_truot_giu_chunk_cu(csdl, tmp_path):
    d = dong(406627, "98/2020/NĐ-CP")
    nap_docx(csdl, tmp_path, d, ND_98)
    kq = nap_docx(
        csdl, tmp_path, dong(406627, "98/2020/NĐ-CP"), ["Điều 1. A", "Điều 5. B"], ten="hong.docx"
    )

    assert kq.loi == ["Số Điều không liên tục: Điều 1 → Điều 5"]
    v = csdl.execute("SELECT so_chunk, file_hash, loi FROM van_ban").fetchone()
    assert v == (7, "md5-vb.docx", ["Số Điều không liên tục: Điều 1 → Điều 5"])


def test_van_ban_moi_truot_gate_thi_trang_thai_loi(csdl, tmp_path):
    nap_docx(csdl, tmp_path, dong(1, "98/2020/NĐ-CP"), ["Điều 2. A"])
    nap.tinh_lai(csdl, HOM_NAY)
    assert csdl.execute("SELECT trang_thai, dung_de_tra FROM van_ban").fetchone() == ("loi", False)


@pytest.mark.parametrize(
    ("them", "trang_thai"),
    [
        ({"con_hieu_luc": False}, "het_hieu_luc"),
        ({"ngay_het_hieu_luc": date(2026, 1, 1)}, "het_hieu_luc"),
        ({"ngay_hieu_luc": date(2027, 1, 1)}, "chua_hieu_luc"),
    ],
)
def test_trang_thai_theo_ngay(csdl, tmp_path, them, trang_thai):
    nap_docx(csdl, tmp_path, dong(406627, "98/2020/NĐ-CP", **them), ND_98)
    nap.tinh_lai(csdl, HOM_NAY)
    assert csdl.execute("SELECT trang_thai, dung_de_tra FROM van_ban").fetchone() == (
        trang_thai,
        False,
    )


def test_vbhn_thay_van_ban_goc_va_van_ban_sua_doi(csdl, tmp_path):
    gioi_thieu = [
        "Nghị định số 98/2020/NĐ-CP ngày 26 tháng 8 năm 2020 của Chính phủ, được sửa đổi bởi:",
        "Nghị định số 17/2022/NĐ-CP ngày 31 tháng 01 năm 2022 sửa đổi các nghị định;",
        "Nghị định số 24/2025/NĐ-CP ngày 21 tháng 02 năm 2025 sửa đổi Nghị định 98/2020.",
    ]
    nap_docx(csdl, tmp_path, dong(406627, "98/2020/NĐ-CP"), ND_98, ten="goc.docx")
    nap_docx(
        csdl, tmp_path, dong(644186, "24/2025/NĐ-CP", ngay=date(2025, 2, 21)),
        ["Điều 1. Sửa đổi", "Điều 2. Hiệu lực thi hành"], ten="sua.docx",
        ngay="ngày 21 tháng 02 năm 2025",
        dau=["SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA NGHỊ ĐỊNH SỐ 98/2020/NĐ-CP NGÀY 26/8/2020"],
    )  # fmt: skip
    nap_docx(
        csdl, tmp_path, dong(502253, "17/2022/NĐ-CP", ngay=date(2022, 1, 31)),
        ["Điều 1. Sửa đổi", "Điều 2. Hiệu lực thi hành"], ten="nhieu.docx",
        ngay="ngày 31 tháng 01 năm 2022",
        dau=["SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA CÁC NGHỊ ĐỊNH QUY ĐỊNH VỀ XỬ PHẠT"],
    )  # fmt: skip
    for ma, ngay, chu in [(600000, date(2022, 2, 1), "2022"), (654519, date(2025, 4, 23), "2025")]:
        nap_docx(
            csdl, tmp_path, dong(ma, "03/VBHN-BCT", loai="vbhn", ngay=ngay), ND_98,
            ten=f"vbhn{chu}.docx", ngay=f"ngày {ngay.day} tháng {ngay.month} năm {ngay.year}",
            dau=gioi_thieu,
        )  # fmt: skip
    nap.tinh_lai(csdl, HOM_NAY)

    tra = dict(csdl.execute("SELECT tvpl_id, dung_de_tra FROM van_ban").fetchall())
    assert tra == {
        406627: False,  # văn bản gốc: đã có VBHN
        644186: False,  # chỉ sửa 98/2020, đã hợp nhất
        502253: True,  # sửa nhiều nghị định: phần sửa văn bản khác chưa hợp nhất ở đâu
        600000: False,  # VBHN cũ
        654519: True,  # VBHN mới nhất
    }
    loai = csdl.execute(
        "SELECT den_so_hieu, loai, den FROM quan_he_van_ban WHERE tu = 654519"
        " ORDER BY loai, den_so_hieu"
    ).fetchall()
    assert loai == [
        ("98/2020/NĐ-CP", "hop_nhat", 406627),
        ("17/2022/NĐ-CP", "hop_nhat_sua", 502253),
        ("24/2025/NĐ-CP", "hop_nhat_sua", 644186),
    ]


def test_chi_sua_mot_van_ban():
    goc = "SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA NGHỊ ĐỊNH SỐ 98/2020/NĐ-CP NGÀY 26 THÁNG 8 NĂM 2020"
    assert chi_sua_mot_van_ban(goc) == chuan_so_hieu("98/2020/NĐ-CP")
    lich_su = goc + " ĐÃ ĐƯỢC SỬA ĐỔI, BỔ SUNG BỞI NGHỊ ĐỊNH SỐ 17/2022/NĐ-CP … CÁC NGHỊ ĐỊNH"
    assert chi_sua_mot_van_ban(lich_su) == chuan_so_hieu("98/2020/NĐ-CP")
    assert chi_sua_mot_van_ban(goc + " VÀ NGHỊ ĐỊNH SỐ 117/2020/NĐ-CP") is None
    assert chi_sua_mot_van_ban("SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA CÁC NGHỊ ĐỊNH") is None
    assert chi_sua_mot_van_ban("QUY ĐỊNH XỬ PHẠT") is None


def test_dong_tu_sheet():
    tho = {
        "dong": 5, "so_hieu": "98/2020/NĐ-CP", "ngay_ban_hanh": 44069, "loai": "Nghị định",
        "con_hieu_luc": True, "ngay_hieu_luc": 44119, "ngay_het_hieu_luc": "", "link_tvpl": "l",
    }  # fmt: skip
    from qltt.google_io import ngay_tu_serial

    d = dong_tu_sheet(tho, 406627, ngay_tu_serial)
    assert (d.loai, d.ngay_ban_hanh, d.ngay_het_hieu_luc) == ("nghi_dinh", date(2020, 8, 26), None)
    assert dong_tu_sheet(tho | {"loai": "Công văn"}, 1, ngay_tu_serial) == (
        "dòng 5: loại văn bản lạ: 'Công văn'"
    )
    assert "không phải kiểu ngày" in dong_tu_sheet(
        tho | {"ngay_ban_hanh": "26/8/2020"}, 1, ngay_tu_serial
    )
