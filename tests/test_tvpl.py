import pytest

from qltt import tvpl

GOC = "https://thuvienphapluat.vn/van-ban/Vi-pham-hanh-chinh"


@pytest.mark.parametrize(
    ("link", "ma"),
    [
        (f"{GOC}/Luat-Xu-ly-vi-pham-hanh-chinh-sua-doi-2025-so-88-2025-QH15-659898.aspx", 659898),
        (f"{GOC}/Nghi-dinh-275-2026-ND-CP-683265.aspx?anchor=dieu_1", 683265),
        ("https://thuvienphapluat.vn/page/tim-van-ban.aspx?keyword=98/2020", None),
        ("", None),
    ],
)
def test_id_tu_link(link, ma):
    assert tvpl.id_tu_link(link) == ma


@pytest.mark.parametrize(
    ("ten", "ma"),
    [
        ("98_2020_ND-CP_406627.docx", 406627),
        ("24_2025_ND-CP_m_644186.docx", 644186),  # TVPL chèn "_m_" trước mã
        ("171_2026_VBHN-LQ-VPQH_728304.docx", 728304),
        ("102_2021_ND-CP_494746 (1).docx", 494746),  # tải trùng
        ("98_2020_ND-CP_406627", 406627),  # Drive đổi sang Google Docs, mất đuôi
        ("ghi chu.docx", None),
    ],
)
def test_id_tu_ten_file(ten, ma):
    assert tvpl.id_tu_ten_file(ten) == ma


def test_doi_chieu():
    kq = tvpl.doi_chieu([1, 2, 3, 3], [2, 3, 4])
    assert kq == {
        "khop": [2, 3],
        "dong_thieu_file": [1],
        "file_thieu_dong": [4],
        "dong_trung_ma": [3],
        "file_trung_ma": [],
    }
