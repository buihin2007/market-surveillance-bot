from datetime import date

from qltt.gate import kiem
from qltt.parse import Dieu, Khoan, VanBanParse


def vb(dieu, so="98/2020/NĐ-CP", ngay=date(2020, 8, 26), nhung=False):
    return VanBanParse(so, ngay, dieu, [], {}, nhung, 1000, 900)


def dieu(so, suffix="", khoan=(), text=""):
    return Dieu(so, suffix, "Tên", None, None, None, text, [Khoan(k, "", f"{k}. x") for k in khoan])


def test_van_ban_dung_thi_qua():
    g = kiem(
        vb([dieu(1), dieu(2, khoan=[1, 2]), dieu(2, "a"), dieu(3)]),
        "98/2020/NĐ-CP",
        date(2020, 8, 26),
    )
    assert g.qua and g.canh_bao == []


def test_so_hieu_khac_sheet_thi_truot():
    g = kiem(vb([dieu(1)], so="99/2020/NĐ-CP"), "98/2020/NĐ-CP", None)
    assert not g.qua and "tải nhầm file" in g.loi[0]


def test_khong_co_dieu_thi_truot():
    assert not kiem(vb([]), "98/2020/NĐ-CP", None).qua


def test_dieu_nhay_hoac_lui_thi_truot():
    g = kiem(vb([dieu(1), dieu(3), dieu(2)]), "98/2020/NĐ-CP", None)
    assert g.loi == [
        "Số Điều không liên tục: Điều 1 → Điều 3",
        "Số Điều không liên tục: Điều 3 → Điều 2",
    ]


def test_khoan_lech_chi_canh_bao():
    g = kiem(vb([dieu(1, khoan=[1, 1])]), "98/2020/NĐ-CP", None)
    assert g.qua and g.canh_bao == ["Điều 1: khoản 1 → khoản 1"]


def test_khung_phat_nguoc_thi_truot():
    d = dieu(1, text="Phạt tiền từ 5.000.000 đồng đến 1.000.000 đồng.")
    assert not kiem(vb([d]), "98/2020/NĐ-CP", None).qua


def test_ngay_lech_va_file_nhung_chi_canh_bao():
    g = kiem(vb([dieu(1)], nhung=True), "98/2020/NĐ-CP", date(2020, 8, 27))
    assert g.qua and len(g.canh_bao) == 2


def test_vbhn_bo_dieu_bi_bai_bo_chi_canh_bao():
    g = kiem(vb([dieu(1), dieu(3), dieu(2)]), "98/2020/NĐ-CP", None, la_vbhn=True)
    assert g.loi == ["Số Điều không liên tục: Điều 3 → Điều 2"]  # lùi vẫn trượt
    assert g.canh_bao == [
        "Số Điều không liên tục: Điều 1 → Điều 3 (VBHN có thể bỏ Điều đã bị bãi bỏ)"
    ]
