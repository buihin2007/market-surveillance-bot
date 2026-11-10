"""Mỗi test là một bẫy có thật trong 109 file TVPL (khảo sát 10/11/2026)."""

import unicodedata
from datetime import date

import docx
import pytest

from qltt.parse import chuan, chuan_so_hieu, parse


def tao_docx(tmp_path, dong, so="98/2020/NĐ-CP", ngay="ngày 26 tháng 8 năm 2020", ten="vb.docx"):
    """dong: chuỗi = một đoạn; list[list[str]] = một bảng. Đầu là bảng quốc hiệu như TVPL."""
    d = docx.Document()
    bang = d.add_table(rows=2, cols=2)
    bang.cell(0, 0).text = "CHÍNH PHỦ"
    bang.cell(0, 1).text = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
    bang.cell(1, 0).text = f"Số: {so}"
    bang.cell(1, 1).text = f"Hà Nội, {ngay}"
    for x in ["NGHỊ ĐỊNH", "Căn cứ Luật Tổ chức Chính phủ;", *dong]:
        if isinstance(x, str):
            d.add_paragraph(x)
        else:
            b = d.add_table(rows=len(x), cols=len(x[0]))
            for i, hang in enumerate(x):
                for j, o in enumerate(hang):
                    b.cell(i, j).text = o
    path = tmp_path / ten
    d.save(path)
    return path


def test_chuan_hoa():
    nfd = unicodedata.normalize("NFD", "Điều 28.")
    assert chuan(nfd) == "Điều 28."
    assert chuan("Ðiều\xa01") == "Điều 1"
    assert chuan_so_hieu("98 / 2020 / NĐ-CP") == chuan_so_hieu("98/2020/NĐ-CP")


def test_cau_truc_co_ban(tmp_path):
    p = tao_docx(
        tmp_path,
        [
            "Chương I",
            "QUY ĐỊNH CHUNG",
            "Điều 1. Phạm vi điều chỉnh",
            "Nghị định này quy định về xử phạt.",
            "Chương II",
            "HÀNH VI VI PHẠM",
            "Mục 1: VI PHẠM VỀ HÀNG GIẢ",
            "Điều 2. Buôn bán hàng giả",
            "1. Phạt tiền từ 500.000 đồng đến 1.000.000 đồng đối với hành vi:",
            "a) Buôn bán hàng giả;",
            "2. Hình thức xử phạt bổ sung:",
        ],
    )
    vb = parse(p)
    assert vb.so_hieu == "98/2020/NĐ-CP"
    assert vb.ngay_ky == date(2020, 8, 26)
    d1, d2 = vb.dieu
    assert (d1.so, d1.ten, d1.chuong, d1.khoan) == (
        1,
        "Phạm vi điều chỉnh",
        "Chương I. QUY ĐỊNH CHUNG",
        [],
    )
    assert d1.dau == "Nghị định này quy định về xử phạt."
    assert d2.muc == "Mục 1. VI PHẠM VỀ HÀNG GIẢ"
    assert [k.so for k in d2.khoan] == [1, 2]
    assert "a) Buôn bán hàng giả;" in d2.khoan[0].text


def test_dieu_va_khoan_trong_ngoac_kep_khong_phai_cua_van_ban(tmp_path):
    """24/2025 sửa 98/2020: "Điều 9." trong ngoặc kép là nội dung sửa đổi."""
    p = tao_docx(
        tmp_path,
        [
            "Điều 1. Sửa đổi, bổ sung một số điều của Nghị định số 98/2020/NĐ-CP",
            "1. Sửa đổi Điều 9 như sau:",
            "“Điều 9. Hành vi buôn bán hàng giả",
            "1. Phạt tiền từ 1.000.000 đồng đến 3.000.000 đồng;",
            "2. Phạt tiền từ 3.000.000 đồng đến 5.000.000 đồng; được gọi là “hàng giả”.",
            "3. Phạt tiền gấp hai lần.”.",
            "2. Bổ sung Điều 9a như sau:",
            "“Điều 9a. Hành vi mới.”.",
            "Điều 2. Hiệu lực thi hành",
        ],
    )
    vb = parse(p)
    assert [d.ky_hieu for d in vb.dieu] == ["1", "2"]
    assert [k.so for k in vb.dieu[0].khoan] == [1, 2]
    assert "“Điều 9. Hành vi buôn bán hàng giả" in vb.dieu[0].khoan[0].text


def test_ngoac_dong_sai_van_tach_dung_khoan_lenh_sua_doi(tmp_path):
    """14/2022: khối trích không đóng đúng; "48. Sửa đổi..." vẫn là khoản của văn bản."""
    p = tao_docx(
        tmp_path,
        [
            "Điều 1. Sửa đổi một số điều",
            "47. Sửa đổi, bổ sung Điều 120 như sau:",
            "“Điều 120. Phân định thẩm quyền",
            "1. Chủ tịch Ủy ban nhân dân các cấp có quyền xử phạt theo “quy định”",
            "48. Sửa đổi, bổ sung Điều 121 như sau:",
            "“Điều 121. Thẩm quyền lập biên bản.”.",
        ],
    )
    assert [k.so for k in parse(p).dieu[0].khoan] == [47, 48]


def test_ngoac_kep_thang(tmp_path):
    """126/2021 dùng ngoặc thẳng cho khối trích."""
    p = tao_docx(
        tmp_path,
        [
            "Điều 2. Sửa đổi Nghị định 99/2020",
            "45. Bổ sung Điều 29a vào sau Điều 29 như sau:",
            '"Điều 29a. Vi phạm quy định trong sản xuất, pha chế khí',
            "1. Phạt tiền từ 10.000.000 đồng đến 20.000.000 đồng.",
            '2. Tịch thu tang vật."',
            "46. Bãi bỏ Điều 30.",
        ],
        so="126/2021/NĐ-CP",
    )
    assert [k.so for k in parse(p).dieu[0].khoan] == [45, 46]


def test_hau_to_va_loi_go(tmp_path):
    p = tao_docx(
        tmp_path,
        [
            "Điều 1. Phạm vi",
            "Điều 2. Đối tượng",
            "Điều 2a. Thời hiệu",  # hậu tố
            "1. Khoản một.",
            "1a. Khoản bổ sung.",
            "2 Phạt tiền thiếu dấu chấm.",  # lỗi gõ của nguồn, chỉ nhận vì đúng số kế tiếp
            "3) Thời hạn.",
            "Điền 3. Lỗi gõ của TVPL",
            "Điều 4 Thông tư số 18/2011/TT-BNNPTNT ngày 06 tháng 4 năm 2011",  # không có dấu chấm
        ],
    )
    vb = parse(p)
    assert [d.ky_hieu for d in vb.dieu] == ["1", "2", "2a", "3"]
    assert [f"{k.so}{k.suffix}" for k in vb.dieu[2].khoan] == ["1", "1a", "2", "3"]
    assert "Điều 4 Thông tư số 18/2011" in vb.dieu[3].dau


def test_phan_va_tieu_de_nfd(tmp_path):
    p = tao_docx(
        tmp_path,
        ["Phần thứ nhất", "Chương I", "Điều 1. A", unicodedata.normalize("NFD", "Điều 2. B")],
    )
    vb = parse(p)
    assert [d.so for d in vb.dieu] == [1, 2]
    assert vb.dieu[1].phan == "Phần thứ nhất"


def test_bang_trong_dieu_giu_lai_bang_ky_ten_bo_di(tmp_path):
    p = tao_docx(
        tmp_path,
        [
            "Điều 1. Cách tính",
            "1. Tổng giá trị được tính theo công thức:",
            [["Tổng giá trị", "= lượng × đơn giá"]],
            "Điều 2. Hiệu lực thi hành",
            "Nghị định này có hiệu lực từ ngày ký.",
            [["Nơi nhận:- Các Bộ", "TM. CHÍNH PHỦ THỦ TƯỚNG"]],
        ],
    )
    vb = parse(p)
    assert "Tổng giá trị | = lượng × đơn giá" in vb.dieu[0].khoan[0].text
    assert "Nơi nhận" not in vb.dieu[1].text


def test_phu_luc_danh_muc_giu_bieu_mau_bo(tmp_path):
    p = tao_docx(
        tmp_path,
        [
            "Điều 1. Danh mục",
            "Danh mục hàng hóa bình ổn giá quy định tại Phụ lục số 01 ban hành kèm theo Luật này.",
            "Điều 2. Hiệu lực thi hành",
            "PHỤ LỤC SỐ 01",
            "DANH MỤC HÀNG HÓA, DỊCH VỤ BÌNH ỔN GIÁ(Ban hành kèm theo Luật Giá số 16/2023/QH15)",
            "1. Xăng, dầu thành phẩm.",
            "Điều 1. Dòng giả trong phụ lục",
            "PHỤ LỤC II",
            "(Kèm theo Nghị định số 98/2020/NĐ-CP)",
            "Mẫu số 01 Đơn đề nghị cấp giấy phép",
        ],
    )
    vb = parse(p)
    assert [d.so for d in vb.dieu] == [1, 2]  # "Điều 1" trong phụ lục không tính
    pl1, pl2 = vb.phu_luc
    assert (pl1.so, pl1.ten, pl1.la_danh_muc) == (
        "01",
        "DANH MỤC HÀNG HÓA, DỊCH VỤ BÌNH ỔN GIÁ",
        True,
    )
    assert "1. Xăng, dầu thành phẩm." in pl1.text
    assert (pl2.so, pl2.la_danh_muc) == ("II", False)


def test_vbhn_chu_thich_va_danh_sach_cuoi(tmp_path):
    """VBHN của TVPL: "[n]" trong thân; danh sách "[n] ..." ở cuối trích Điều văn bản khác."""
    p = tao_docx(
        tmp_path,
        [
            "Điều 1.[2] Phạm vi",
            "1.[11] Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng.",
            "b)[12] Tịch thu tang vật.",
            "Điều 2. Trách nhiệm thi hành",
            "[1] Nghị định số 17/2022/NĐ-CP có căn cứ ban hành như sau:",
            "[2] Điều này được sửa đổi theo khoản 1 Điều 1 Nghị định số 17/2022/NĐ-CP.",
            "“Điều 5. Điều khoản chuyển tiếp",
            "Điều 6 Nghị định số 17/2022/NĐ-CP có hiệu lực.”",
            "[11] Khoản này được sửa đổi theo Nghị định số 24/2025/NĐ-CP.",
        ],
        so="03/VBHN-BCT",
    )
    vb = parse(p)
    assert [d.ky_hieu for d in vb.dieu] == ["1", "2"]
    d1 = vb.dieu[0]
    assert d1.ten == "Phạm vi" and d1.chu_thich == [2]
    assert d1.khoan[0].chu_thich == [11, 12]
    assert "[11]" not in d1.khoan[0].text and "b) Tịch thu tang vật." in d1.khoan[0].text
    assert vb.chu_thich[11] == "Khoản này được sửa đổi theo Nghị định số 24/2025/NĐ-CP."
    assert "Điều 5. Điều khoản chuyển tiếp" in vb.chu_thich[2]


@pytest.mark.parametrize("dau", ["Nơi nhận:", "XÁC THỰC VĂN BẢN HỢP NHẤT", "KT. BỘ TRƯỞNG"])
def test_ket_van_ban_khong_vao_dieu_cuoi(tmp_path, dau):
    p = tao_docx(tmp_path, ["Điều 1. Hiệu lực", "Có hiệu lực từ ngày ký.", dau, "- Các Bộ;"])
    assert parse(p).dieu[0].text == "Điều 1. Hiệu lực\nCó hiệu lực từ ngày ký."
