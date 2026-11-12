import dataclasses
from datetime import date

import pytest
from test_nap import HOM_NAY, ND_98, dong, nap_docx

from qltt import db, nap, sua_doi
from qltt.sua_doi import (
    dich,
    doc_dieu_hieu_luc,
    loai_hanh_dong,
    tach_chi_tiet,
    tach_dong_phu_luc,
    vi_tri_bi_sua,
)


@pytest.mark.parametrize(
    ("ten", "mong"),
    [
        ("Sửa đổi một số Điều của Nghị định số 83/2014/NĐ-CP ngày 03 tháng 9 năm 2014",
         ["83/2014/NĐ-CP"]),
        ("Sửa đổi, bổ sung một số điều của Nghị định số 95/2021/NĐ-CP ngày 01 tháng 11 năm 2021"
         " và Nghị định số 83/2014/NĐ-CP ngày 03 tháng 9 năm 2014",
         ["95/2021/NĐ-CP", "83/2014/NĐ-CP"]),
        ("Bổ sung, thay thế, bãi bỏ một số cụm từ của Nghị định số 45/2019/NĐ-CP, Nghị định số"
         " 131/2013/NĐ-CP và Nghị định số 38/2021/NĐ-CP",
         ["45/2019/NĐ-CP", "131/2013/NĐ-CP", "38/2021/NĐ-CP"]),
        # số sau là mô tả của văn bản đích, không phải đích
        ("Bãi bỏ Khoản 7 Điều 1 của Nghị định số 106/2017/NĐ-CP sửa đổi, bổ sung một số Điều của"
         " Nghị định số 67/2013/NĐ-CP", ["106/2017/NĐ-CP"]),
        ("Sửa đổi, bổ sung một số điều, khoản của Nghị định số 137/2013/ NĐ-CP ngày 21",
         ["137/2013/NĐ-CP"]),
        ("Sửa đổi, bổ sung Luật Giá số 16/2023/QH15", ["16/2023/QH15"]),
        ("Sửa đổi, bổ sung Điều 27", []),
    ],
)  # fmt: skip
def test_dich(ten, mong):
    assert dich(ten) == mong


def test_loai_hanh_dong():
    assert loai_hanh_dong("Bãi bỏ Điều 6 và Điều 7 Nghị định số 35/2006") == "bai_bo"
    assert loai_hanh_dong("Thay thế cụm từ trong Nghị định số 1/2020") == "thay_the"
    assert loai_hanh_dong("Bổ sung, thay thế, bãi bỏ một số cụm từ") == "sua_doi"


@pytest.fixture
def kho(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    # 98/2020 (gốc) + VBHN gồm 24/2025; 87/2024 bị 114/2026 sửa, chưa có VBHN; 83/2014 bị 08/2018
    # (văn bản sửa nhiều nghị định) sửa; luật Dược bị luật 44/2024 sửa (gọi tên, không số)
    nap_docx(conn, tmp_path, dong(1, "98/2020/NĐ-CP"), ND_98, ten="98.docx")
    nap_docx(
        conn,
        tmp_path,
        dong(2, "24/2025/NĐ-CP", ngay=date(2025, 2, 21)),
        [
            "Điều 1. Sửa đổi, bổ sung một số điều của Nghị định số 98/2020/NĐ-CP ngày 26 tháng 8",
            "1. Khoản 1 Điều 2 được sửa đổi như sau:",
            "“1. Phạt tiền từ 2.000.000 đồng đến 4.000.000 đồng.”",
            "Điều 2. Hiệu lực thi hành",
        ],
        ten="24.docx",
        ngay="ngày 21 tháng 02 năm 2025",
        dau=["SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA NGHỊ ĐỊNH SỐ 98/2020/NĐ-CP"],
    )
    nap_docx(
        conn,
        tmp_path,
        dong(3, "03/VBHN-BCT", loai="vbhn", ngay=date(2025, 4, 23)),
        ND_98,
        ten="vbhn.docx",
        ngay="ngày 23 tháng 4 năm 2025",
        dau=[
            "Nghị định số 98/2020/NĐ-CP ngày 26 tháng 8 năm 2020 của Chính phủ, được sửa đổi bởi:",
            "Nghị định số 24/2025/NĐ-CP ngày 21 tháng 02 năm 2025 sửa đổi Nghị định 98/2020.",
        ],
    )
    nap_docx(conn, tmp_path, dong(4, "87/2024/NĐ-CP"), ND_98, ten="87.docx")
    nap_docx(
        conn,
        tmp_path,
        dong(5, "114/2026/NĐ-CP", ngay=date(2026, 5, 20)),
        [
            "Điều 1. Sửa đổi, bổ sung Điều 1",
            "Điều 2. Sửa đổi điểm b khoản 2 Điều 2",
            "“b) Tịch thu tang vật.”.",
            "Điều 3. Điều khoản thi hành",
        ],
        ten="114.docx",
        ngay="ngày 20 tháng 5 năm 2026",
        dau=["SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA NGHỊ ĐỊNH SỐ 87/2024/NĐ-CP NGÀY 12 THÁNG 7"],
    )
    nap_docx(conn, tmp_path, dong(6, "83/2014/NĐ-CP"), ND_98, ten="83.docx")
    nap_docx(
        conn,
        tmp_path,
        dong(7, "08/2018/NĐ-CP", ngay=date(2018, 1, 15)),
        [
            "Điều 1. Sửa đổi một số Điều của Nghị định số 83/2014/NĐ-CP ngày 03 tháng 9 năm 2014",
            "Điều 2. Bãi bỏ một số Điều của Nghị định số 52/2013/NĐ-CP",
            "Điều 3. Hiệu lực thi hành",
        ],
        ten="08.docx",
        ngay="ngày 15 tháng 01 năm 2018",
        dau=["SỬA ĐỔI MỘT SỐ NGHỊ ĐỊNH LIÊN QUAN ĐẾN ĐIỀU KIỆN ĐẦU TƯ KINH DOANH"],
    )
    nap_docx(
        conn,
        tmp_path,
        dong(8, "105/2016/QH13", loai="luat"),
        ND_98,
        ten="duoc.docx",
        dau=["LUẬT", "DƯỢC"],
    )
    nap_docx(
        conn, tmp_path, dong(9, "44/2024/QH15", loai="luat", ngay=date(2024, 11, 21)),
        ["Điều 1. Sửa đổi, bổ sung một số điều của Luật Dược", "Điều 2. Hiệu lực thi hành"],
        ten="44.docx", ngay="ngày 21 tháng 11 năm 2024",
        dau=["LUẬT", "SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA LUẬT DƯỢC"],
    )  # fmt: skip
    nap.tinh_lai(conn, HOM_NAY)
    return conn


def test_bang_phu(kho):
    assert sua_doi.dung_lai(kho) >= 5
    bang = {(d.tu_so_hieu, d.den_so_hieu): d for d in sua_doi.bang_phu(kho)}
    assert bang[("24/2025/NĐ-CP", "98/2020/NĐ-CP")].nhom == "da_hop_nhat"
    assert bang[("24/2025/NĐ-CP", "98/2020/NĐ-CP")].vbhn == "03/VBHN-BCT"
    # tên Điều không nêu số hiệu → đích theo tiêu đề
    assert bang[("114/2026/NĐ-CP", "87/2024/NĐ-CP")].nhom == "chua_hop_nhat"
    assert bang[("08/2018/NĐ-CP", "83/2014/NĐ-CP")].nhom == "chua_hop_nhat"
    assert bang[("08/2018/NĐ-CP", "52/2013/NĐ-CP")].nhom == "khong_trong_kho"
    assert bang[("08/2018/NĐ-CP", "52/2013/NĐ-CP")].loai == "bai_bo"
    assert bang[("44/2024/QH15", "105/2016/QH13")].nhom == "chua_hop_nhat"  # theo tên luật
    # chạy lại không nhân đôi
    n = sua_doi.dung_lai(kho)
    assert sua_doi.dung_lai(kho) == n


@pytest.mark.parametrize(
    ("lay", "mong"),
    [
        ("7. Điểm a, điểm d khoản 2 và khoản 6 Điều 8 được sửa đổi, bổ sung như sau:",
         [(8, "", [2, 6])]),
        ("2. Bãi bỏ khoản 2, 3, 4 và 5 Điều 7.", [(7, "", [2, 3, 4, 5])]),
        ("8. Sửa đổi khoản 1, khoản 2 Điều 9 và bổ sung khoản 20 Điều 9 như sau:",
         [(9, "", [1, 2, 20])]),
        ("Bãi bỏ Điều 5, Khoản 6 Điều 7, Điều 10", [(5, "", []), (7, "", [6]), (10, "", [])]),
        # khoản sau Điều cuối (mục a, b) thuộc Điều đó; "sau Điều 5" là chỗ chèn, không phải đích
        ("3. Sửa đổi một số khoản của Điều 6 như sau: a) Sửa đổi khoản 2 như sau: … b) Bổ sung"
         " khoản 5 như sau: …", [(6, "", [2, 5])]),
        ("4. Bổ sung Điều 5a sau Điều 5 như sau: …", [(5, "a", [])]),
        ("Bổ sung khoản 5a Điều 40", [(40, "", [0])]),  # khoản mới
        ("Đổi tên thương nhân … thành …", []),
        ("Giấy phép bán lẻ rượu quy định tại các Điều 23, 25, 26 và 27 Nghị định số",
         [(23, "", []), (25, "", []), (26, "", []), (27, "", [])]),
        ("tại Điều 36, Điều 44, khoản 2 Điều 45", [(36, "", []), (44, "", []), (45, "", [2])]),
        ("khoản 4 điều 28 Luật", [(28, "", [4])]),
    ],
)  # fmt: skip
def test_vi_tri_bi_sua(lay, mong):
    assert vi_tri_bi_sua(lay) == mong


def test_tach_chi_tiet():
    nd = (
        "3. Sửa đổi, bổ sung khoản 4 Điều 13 Nghị định số 83/2014/NĐ-CP như sau:\n"
        "“4. Có phòng thử nghiệm thuộc sở hữu của thương nhân (Điều 99 không phải đích).”"
    )
    (x,) = tach_chi_tiet(1, "khoản 3 Điều 1", nd, "Sửa đổi …", ["95/2021/NĐ-CP", "83/2014/NĐ-CP"])
    assert (x.den_so_hieu, x.dieu_so, x.khoan, x.chac) == ("83/2014/NĐ-CP", 13, [4], True)
    assert x.mo_ta == "Sửa đổi, bổ sung khoản 4 Điều 13 Nghị định số 83/2014/NĐ-CP"
    assert x.noi_dung_moi.startswith("4. Có phòng thử nghiệm") and x.hanh_dong == "sua_doi"
    # không nêu Điều: lấy Điều trong tên Điều sửa đổi; không nêu văn bản: đích của Điều
    (x,) = tach_chi_tiet(2, "khoản 1 Điều 2", "1. Bổ sung khoản 9\n“9. Mới.”",
                         "Sửa đổi, bổ sung Điều 3", ["87/2024/NĐ-CP"])  # fmt: skip
    assert (x.den_so_hieu, x.dieu_so, x.khoan, x.hanh_dong) == ("87/2024/NĐ-CP", 3, [9], "bo_sung")
    (x,) = tach_chi_tiet(3, "Điều 1", "Điều 1. Sửa đổi Điều 1\nSửa đổi cụm từ “a” thành “b”.",
                         "Sửa đổi, bổ sung Điều 1", ["87/2024/NĐ-CP"])  # fmt: skip
    assert (x.dieu_so, x.hanh_dong) == (1, "thay_cum_tu")


def test_canh_bao(kho):
    sua_doi.dung_lai(kho)
    assert sua_doi.dung_chi_tiet(kho) >= 2
    tv = {sh: t for t, sh in kho.execute("SELECT tvpl_id, so_hieu FROM van_ban")}
    # 87/2024 chưa hợp nhất: khoản 2 Điều 2 bị 114/2026 sửa, khoản 1 thì không
    (cb,) = sua_doi.canh_bao(kho, tv["87/2024/NĐ-CP"], 2, "", 2)
    assert (cb.so_hieu, cb.vi_tri_tu, cb.noi_dung_moi) == (
        "114/2026/NĐ-CP",
        "Điều 2",
        "b) Tịch thu tang vật.",
    )
    assert sua_doi.canh_bao(kho, tv["87/2024/NĐ-CP"], 2, "", 1) == []
    assert len(sua_doi.canh_bao(kho, tv["87/2024/NĐ-CP"], 2, "", None)) == 1  # trích cả Điều
    # 98/2020 gốc: 24/2025 sửa khoản 1 Điều 2; VBHN 03 đã gồm 24/2025 → không cảnh báo
    assert len(sua_doi.canh_bao(kho, tv["98/2020/NĐ-CP"], 2, "", 1)) == 1
    assert sua_doi.canh_bao(kho, tv["03/VBHN-BCT"], 2, "", 1) == []
    dong = sua_doi.dong_canh_bao([cb])
    assert "Đã bị sửa đổi bởi Điều 2 114/2026/NĐ-CP" in dong[0]


def test_tach_dong_phu_luc():
    d = (
        "III. Không thực hiện thủ tục cấp Giấy phép bán lẻ rượu quy định tại các Điều 23, 25 Nghị"
        " định số 105/2017/NĐ-CP được sửa đổi, bổ sung bởi Nghị định số 17/2020/NĐ-CP."
    )
    ct = tach_dong_phu_luc(1, "Phụ lục I.2", d, [])
    # số hiệu thứ hai không có Điều đứng trước → không phải đích
    assert [(x.den_so_hieu, x.dieu_so, x.hanh_dong) for x in ct] == [
        ("105/2017/NĐ-CP", 23, "khong_thuc_hien"),
        ("105/2017/NĐ-CP", 25, "khong_thuc_hien"),
    ]
    assert ct[0].mo_ta.startswith("Không thực hiện thủ tục cấp Giấy phép bán lẻ rượu")
    d = "I. Điều kiện cấp Giấy phép chế biến quy định tại Điều 12 Nghị định 67/2013/NĐ-CP:"
    (x,) = tach_dong_phu_luc(1, "Phụ lục II", d, ["1. Doanh nghiệp …", "2. Có dây chuyền …",
                                                  "II. Điều kiện khác", "1. …"])  # fmt: skip
    assert (x.dieu_so, x.hanh_dong, x.noi_dung_moi) == (
        12,
        "sua_doi",
        "1. Doanh nghiệp …\n2. Có dây chuyền …",
    )
    d = "V. Bãi bỏ điều kiện cấp Giấy phép mua bán tại khoản 1 Điều 9 Nghị định 67/2013/NĐ-CP."
    (x,) = tach_dong_phu_luc(1, "Phụ lục II", d, [])
    assert (x.dieu_so, x.khoan, x.hanh_dong) == (9, [1], "bai_bo")
    assert (
        tach_dong_phu_luc(1, "Phụ lục II", "1. Doanh nghiệp tại Điều 9 Nghị định 67/2013/NĐ-CP", [])
        == []
    )


def test_dong_canh_bao_nghi_quyet_tam_thoi():
    cb = sua_doi.CanhBao("66.18/2026/NQ-CP", "Phụ lục I.2", "khong_thuc_hien", "Không thực hiện X",
                         "", "hieu_luc", "01/07/2026", True, "28/02/2027")  # fmt: skip
    (d,) = sua_doi.dong_canh_bao([cb])
    assert "Tạm không thực hiện theo Phụ lục I.2 66.18/2026/NQ-CP (áp dụng đến 28/02/2027)" in d
    assert "không còn áp dụng" in d
    # cùng nguồn + cùng loại → gộp; dòng đại diện trùng nhiều từ nhất với đoạn trích
    ba = [dataclasses.replace(cb, mo_ta=f"Bãi bỏ điều kiện cấp Giấy phép {x}")
          for x in ("phân phối", "bán buôn", "bán lẻ")]  # fmt: skip
    (d,) = sua_doi.dong_canh_bao(ba, trich="3. Điều kiện cấp Giấy phép bán lẻ sản phẩm thuốc lá")
    assert "Giấy phép bán lẻ (cùng 2 dòng tương tự)" in d
    nhieu = [dataclasses.replace(cb, vi_tri_tu=f"Phụ lục {i}") for i in range(5)]
    d = sua_doi.dong_canh_bao(nhieu)
    assert len(d) == sua_doi.TOI_DA_CANH_BAO + 1 and "Và 2 chỉ dẫn" in d[-1]


def _hl(text, so_hieu="1/2026/NĐ-CP"):
    ca, mp = doc_dieu_hieu_luc(1, so_hieu, 9, "Điều 9", text)
    return [(x.den_so_hieu, x.loai) for x in ca], [(x.den_so_hieu, x.dieu_so, x.khoan) for x in mp]


def test_dieu_hieu_luc():
    # số hiệu sau "sửa đổi, bổ sung … của" là mô tả của văn bản đích
    assert _hl(
        "1. Nghị định này có hiệu lực thi hành từ ngày 18 tháng 8 năm 2026.\n"
        "2. Nghị định này thay thế Nghị định số 38/2024/NĐ-CP ngày 05 tháng 4 năm 2024 về thủy"
        " sản và Nghị định số 301/2025/NĐ-CP ngày 17 tháng 11 năm 2025 sửa đổi, bổ sung một số"
        " điều của Nghị định số 38/2024/NĐ-CP ngày 05 tháng 4 năm 2024."
    ) == ([("38/2024/NĐ-CP", "thay_the"), ("301/2025/NĐ-CP", "thay_the")], [])
    # mục a), b) dưới "hết hiệu lực:"; một phần → chỉ dẫn bãi bỏ
    assert _hl(
        "2. Các quy định sau đây hết hiệu lực thi hành kể từ ngày Nghị định này có hiệu lực:\n"
        "a) Nghị định số 117/2020/NĐ-CP ngày 28 tháng 9 năm 2020 về y tế;\n"
        "b) Điều 2 và khoản 1 Điều 3 Nghị định số 124/2021/NĐ-CP ngày 28 tháng 12 năm 2021 sửa"
        " đổi, bổ sung một số điều của Nghị định số 115/2018/NĐ-CP và Nghị định số 117/2020/NĐ-CP."
    ) == ([("117/2020/NĐ-CP", "thay_the")], [("124/2021/NĐ-CP", 2, []), ("124/2021/NĐ-CP", 3, [1])])
    assert _hl("2. Bãi bỏ khoản 6 Điều 9, Điều 36 của Nghị định số 83/2014/NĐ-CP.") == (
        [],
        [("83/2014/NĐ-CP", 9, [6]), ("83/2014/NĐ-CP", 36, [])],
    )
    # chuyển tiếp; "các quy định về X tại A và B"; "… Nghị định này" là chính nó
    assert _hl(
        "2. Quy định chuyển tiếp\n"
        "a) Thương nhân được tiếp tục hoạt động theo Nghị định số 95/2021/NĐ-CP cho đến khi Giấy"
        " xác nhận hết hiệu lực.\n"
        "b) Trừ trường hợp quy định tại điểm a khoản 2 Điều 2 Nghị định này, các quy định về tổng"
        " đại lý tại Nghị định số 95/2021/NĐ-CP và Nghị định số 83/2014/NĐ-CP hết hiệu lực."
    ) == ([], [])
    assert _hl("Bỏ hiệu lực. Thay thế cụm từ “a” tại Điều 3 Luật số 83/2015/QH13.")[0] == []


def test_bi_thay_the_thi_khong_tra(kho, tmp_path):
    nap_docx(
        kho, tmp_path, dong(10, "99/2026/NĐ-CP", ngay=date(2026, 6, 1)),
        ["Điều 1. Phạm vi điều chỉnh", "Điều 2. Hiệu lực thi hành",
         "1. Nghị định này có hiệu lực thi hành từ ngày 01 tháng 6 năm 2026.",
         "2. Nghị định này thay thế Nghị định số 87/2024/NĐ-CP ngày 12 tháng 7 năm 2024."],
        ten="99.docx", ngay="ngày 01 tháng 6 năm 2026",
    )  # fmt: skip
    nap.tinh_lai(kho, HOM_NAY)
    tra = "SELECT dung_de_tra FROM van_ban WHERE so_hieu = '87/2024/NĐ-CP'"
    assert kho.execute(tra).fetchone()[0]
    sua_doi.dung_lai(kho)
    nap.tinh_lai(kho, HOM_NAY)
    assert not kho.execute(tra).fetchone()[0]
    (x,) = sua_doi.lech_sheet(kho)
    assert (x.so_hieu, x.bi_thay_boi, x.loai) == ("87/2024/NĐ-CP", "99/2026/NĐ-CP", "thay_the")
