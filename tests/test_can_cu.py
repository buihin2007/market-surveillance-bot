"""Chuỗi "Quy định tại …" theo văn phong biên bản (mẫu chú gửi 12/11)."""

from datetime import date

import pytest
from test_nap import HOM_NAY, dong, nap_docx

from qltt import can_cu, db, nap
from qltt.can_cu import SuaDoi, chuoi_sua_doi, doc_chu_thich, gop_vi_tri, vi_tri

MAU_CHU = (
    "điểm b khoản 1 Điều 31 Nghị định số 119/2017/NĐ-CP ngày 01/11/2017 của Chính phủ được sửa"
    " đổi, bổ sung tại khoản 48 Điều 2 Nghị định số 126/2021/NĐ-CP ngày 30/12/2021 của Chính phủ"
)


@pytest.mark.parametrize(
    ("chu", "mong"),
    [
        ("Điểm này được sửa đổi, bổ sung theo quy định tại khoản 48 Điều 2 Nghị định số"
         " 126/2021/NĐ-CP ngày 30/12/2021 của Chính phủ sửa đổi, bổ sung …, có hiệu lực kể từ",
         ("được sửa đổi, bổ sung", "khoản 48 Điều 2",
          "Nghị định số 126/2021/NĐ-CP ngày 30/12/2021 của Chính phủ")),
        ("Khoản này đã được sửa đổi, bổ sung bởi điểm d khoản 6 Điều 1 Nghị định số 124/2021/NĐ-CP,"
         " có hiệu lực kể từ ngày 01 tháng 01 năm 2022.",
         ("được sửa đổi, bổ sung", "điểm d khoản 6 Điều 1", "Nghị định số 124/2021/NĐ-CP")),
        ("Điểm này được sửa đổi, bổ sung với điểm b khoản 3 Điều 1 Nghị định số 17/2022/NĐ-CP"
         " ngày 31 tháng 01 năm 2022 của Chính phủ",
         ("được sửa đổi, bổ sung", "điểm b khoản 3 Điều 1",
          "Nghị định số 17/2022/NĐ-CP ngày 31/01/2022 của Chính phủ")),
        ("Cụm từ “doanh nghiệp\" được thay thế bởi cụm từ \"chủ thể kinh doanh” theo quy định tại"
         " điểm n khoản 1 Điều 2 của Thông tư số 06/2024/TT-BKHCN",
         ("được sửa đổi", "điểm n khoản 1 Điều 2", "Thông tư số 06/2024/TT-BKHCN")),
        ("Cụm từ “, đưa vào cơ sở cai nghiện bắt buộc” được bỏ theo quy định tại khoản 9 Điều 54"
         " của Luật Phòng, chống ma túy số 120/2025/QH15",
         ("được sửa đổi", "khoản 9 Điều 54", "Luật số 120/2025/QH15")),
    ],
)  # fmt: skip
def test_doc_chu_thich(chu, mong):
    (x,) = doc_chu_thich(chu)
    assert (x.dong_tu, x.vi_tri, x.ten_trong_chu_thich) == mong


@pytest.mark.parametrize(
    "chu",
    [
        "Điểm này được bãi bỏ theo quy định tại khoản 3 Điều 3 Nghị định số 126/2021/NĐ-CP.",
        "Nghị định số 17/2022/NĐ-CP có căn cứ ban hành như sau:",
        "(): Ghi rõ sản xuất hoặc nhập khẩu.",
    ],
)
def test_khong_phai_sua_doi(chu):
    assert doc_chu_thich(chu) == []


def test_chu_thich_nhieu_van_ban_sua():
    ds = doc_chu_thich(
        "Điểm này được sửa đổi, bổ sung theo quy định tại điểm a khoản 11 Điều 1 của Nghị định số"
        " 126/2021/NĐ-CP, có hiệu lực kể từ ngày 01 tháng 01 năm 2022 và điểm b khoản 11 Điều 1"
        " của Nghị định số 46/2024/NĐ-CP, có hiệu lực kể từ ngày 01 tháng 7 năm 2024."
    )
    assert [(x.vi_tri, x.so_hieu) for x in ds] == [
        ("điểm a khoản 11 Điều 1", "126/2021/NĐ-CP"),
        ("điểm b khoản 11 Điều 1", "46/2024/NĐ-CP"),
    ]


def test_vi_tri_va_gop():
    assert vi_tri(31, "", 8, ["a", "c"]) == "điểm a, điểm c khoản 8 Điều 31"
    assert vi_tri(4, "a", None, None) == "Điều 4a"
    assert gop_vi_tri(["khoản 48 Điều 2", "khoản 49 Điều 2"]) == "khoản 48, khoản 49 Điều 2"
    vb1, vb2 = "Nghị định số 1/2021/NĐ-CP", "Nghị định số 2/2022/NĐ-CP"
    ds = [
        SuaDoi("được sửa đổi", "khoản 1 Điều 1", vb1),
        SuaDoi("được sửa đổi", "khoản 2 Điều 1", vb1),
        SuaDoi("được bổ sung", "khoản 5 Điều 2", vb2),
    ]
    assert chuoi_sua_doi(ds) == (
        f"được sửa đổi tại khoản 1, khoản 2 Điều 1 {vb1} và được bổ sung tại khoản 5 Điều 2 {vb2}"
    )


@pytest.fixture
def kho(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    nap_docx(
        conn, tmp_path, dong(1, "119/2017/NĐ-CP", ngay=date(2017, 11, 1)), ["Điều 1. Phạm vi"],
        ten="119.docx", ngay="ngày 01 tháng 11 năm 2017",
    )  # fmt: skip
    nap_docx(
        conn, tmp_path, dong(2, "126/2021/NĐ-CP", ngay=date(2021, 12, 30)), ["Điều 1. Sửa đổi"],
        ten="126.docx", ngay="ngày 30 tháng 12 năm 2021",
    )  # fmt: skip
    nap_docx(
        conn,
        tmp_path,
        dong(3, "02/VBHN-BKHCN", loai="vbhn", ngay=date(2022, 1, 25)),
        [
            "Điều 1. Phạm vi điều chỉnh",
            "Điều 31.[47] Vi phạm về nhãn hàng hóa",
            "1. Phạt tiền từ 500.000 đồng đến 1.000.000 đồng đối với một trong các hành vi sau:",
            "a) Không có nhãn;",
            "b)[48] Ghi nhãn sai;",
            "c)[49] Nhãn bị thay đổi.",
            "Điều 32. Hiệu lực",
            "[1] Nghị định số 126/2021/NĐ-CP có căn cứ ban hành như sau:",
            "[47] Tên Điều này được sửa đổi, bổ sung theo quy định tại khoản 47 Điều 2 Nghị định số"
            " 126/2021/NĐ-CP.",
            "[48] Điểm này được sửa đổi, bổ sung theo quy định tại khoản 48 Điều 2 Nghị định số"
            " 126/2021/NĐ-CP ngày 30 tháng 12 năm 2021 của Chính phủ, có hiệu lực kể từ",
            "[49] Điểm này được sửa đổi, bổ sung theo quy định tại khoản 3 Điều 1 Nghị định số"
            " 99/2099/NĐ-CP.",
        ],
        ten="vbhn.docx",
        ngay="ngày 25 tháng 01 năm 2022",
        dau=[
            "Nghị định số 119/2017/NĐ-CP ngày 01 tháng 11 năm 2017 của Chính phủ, được sửa đổi"
            " bởi:",
            "Nghị định số 126/2021/NĐ-CP ngày 30 tháng 12 năm 2021.",
        ],
    )
    nap.tinh_lai(conn, HOM_NAY)
    return conn


def test_mau_cua_chu(kho):
    assert can_cu.quy_dinh_tai(kho, 3, 31, "", 1, "b") == MAU_CHU
    # chú thích của điểm khác, chú thích chỉ sửa tên Điều: không dính vào
    assert can_cu.quy_dinh_tai(kho, 3, 31, "", 1, "a") == MAU_CHU.split(" được")[0].replace(
        "điểm b", "điểm a"
    )
    # văn bản không phải VBHN: trích chính nó
    assert can_cu.ten_day_du(kho, "126/2021/NĐ-CP") == (
        "Nghị định số 126/2021/NĐ-CP ngày 30/12/2021 của Chính phủ"
    )


def test_van_ban_lien_quan_co_link_ca_van_ban_chua_co_trong_kho(kho):
    from qltt.hien_thi import VanBan, ViTri, van_ban_lien_quan

    vt = ViTri(3, 31, "", 1, "", ("b", "c"))
    chu = [can_cu.quy_dinh_tai(kho, 3, 31, "", 1, ["b", "c"])]
    assert "khoản 48 Điều 2 Nghị định số 126/2021/NĐ-CP" in chu[0]
    assert chu[0].endswith("tại khoản 3 Điều 1 Nghị định số 99/2099/NĐ-CP")
    dong = van_ban_lien_quan(kho, VanBan(kho), [vt], chu)
    assert dong == [
        '• <a href="x-3.aspx">NĐ 119/2017 (02/VBHN-BKHCN)</a> – bản hợp nhất, bot đang đọc',
        '• <a href="x-1.aspx">NĐ 119/2017</a> – văn bản gốc',
        '• <a href="x-2.aspx">NĐ 126/2021</a> – sửa đổi, bổ sung',
        '• <a href="https://thuvienphapluat.vn/page/tim-van-ban.aspx?keyword=99/2099/N%C4%90-CP">'
        "NĐ 99/2099</a> – sửa đổi, bổ sung (chưa có trong kho)",
    ]
