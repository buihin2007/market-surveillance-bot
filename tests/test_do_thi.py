import pytest
from test_tra_loi import C, Gia, kho  # noqa: F401  (kho là fixture)

from qltt import do_thi


def duong_di(conn, api, cau_hoi):
    cfg = {"configurable": {"conn": conn, "client": api, "c": C}}
    return [next(iter(b)) for b in do_thi.do_thi().stream({"cau_hoi": cau_hoi}, cfg)]


@pytest.mark.parametrize(
    ("api", "mong"),
    [
        (Gia(), ["hieu_cau_hoi", "tim_hanh_vi", "chon_hanh_vi", "tra_muc_phat", "dinh_dang"]),
        (Gia(loai="khac"), ["hieu_cau_hoi", "dinh_dang"]),
        (Gia(loai="ngoai_pham_vi"), ["hieu_cau_hoi", "dinh_dang"]),
        # quy_dinh: kho test chỉ có nghị định xử phạt (không chunk quy phạm) → không đoạn nào
        (Gia(loai="quy_dinh"), ["hieu_cau_hoi", "tim_quy_dinh", "dinh_dang"]),
    ],
)
def test_duong_di_theo_loai(kho, api, mong):  # noqa: F811
    assert duong_di(kho, api, "bán hàng nhập lậu") == mong


def test_khong_ung_vien_thi_bo_qua_llm_2(kho):  # noqa: F811
    kho.execute("DELETE FROM muc_phat")
    api = Gia()
    assert duong_di(kho, api, "bán hàng nhập lậu") == ["hieu_cau_hoi", "tim_hanh_vi", "dinh_dang"]
    assert api.goi_chon == []


def test_mermaid_co_du_nut():
    m = do_thi.mermaid()
    for nut in ("hieu_cau_hoi", "tim_hanh_vi", "chon_hanh_vi", "tim_quy_dinh", "chon_trich"):
        assert nut in m
