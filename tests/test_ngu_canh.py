import pytest
from test_nap import HOM_NAY, dong, nap_docx

from qltt import db, nap, ngu_canh

ND = [
    "Điều 1. Phạm vi điều chỉnh",
    "Nghị định này quy định xử phạt trong hoạt động thương mại.",
    "Điều 2. Giải thích từ ngữ",
    "1. Hàng giả là hàng hóa có giá trị sử dụng không đúng với nguồn gốc bản chất.",
    "2. Hàng nhập lậu là hàng hóa nhập khẩu không có chứng từ hợp pháp.",
    "Chương II",
    "HÀNH VI VI PHẠM",
    "Điều 3. Buôn bán hàng giả",
    "1. Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng đối với hành vi buôn bán hàng giả.",
    "2. Hình thức xử phạt bổ sung: tịch thu hàng giả.",
    "Điều 4. Kinh doanh hàng nhập lậu",
    "1. Phạt tiền từ 3.000.000 đồng đến 5.000.000 đồng đối với hành vi kinh doanh hàng nhập lậu.",
    "Điều 5. Hiệu lực thi hành",
]


@pytest.fixture
def kho(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    nap_docx(conn, tmp_path, dong(406627, "98/2020/NĐ-CP"), ND)
    nap.tinh_lai(conn, HOM_NAY)
    return conn


def test_lap_ngu_canh_hanh_vi_dinh_nghia_quy_pham(kho):
    nc = ngu_canh.lap(kho, "buôn bán hàng giả", None)  # None: chỉ nhánh từ khóa

    hv = nc.hanh_vi[0]
    assert (hv.so_hieu, hv.dieu, hv.ten) == ("98/2020/NĐ-CP", "Điều 3", "Buôn bán hàng giả")
    assert "Phạt tiền từ 1.000.000" in hv.noi_dung and "tịch thu" in hv.noi_dung  # cả Điều
    assert hv.chunk_khop[0] in {"Điều 3", "Điều 3 khoản 1"}
    assert len({h.khoa for h in nc.hanh_vi}) == len(nc.hanh_vi)  # mỗi Điều một lần
    assert all(h.dieu != "Điều 2" for h in nc.hanh_vi)  # định nghĩa không là hành vi

    assert nc.dinh_nghia and {d.duong_dan for d in nc.dinh_nghia} <= {
        "Điều 2", "Điều 2 khoản 1", "Điều 2 khoản 2"
    }  # fmt: skip
    assert not {d.id for d in nc.dinh_nghia} & {d.id for d in nc.quy_pham}


def test_khong_tim_thay_hanh_vi_thi_rong(kho):
    nc = ngu_canh.lap(kho, "vượt đèn đỏ", None)
    assert nc.hanh_vi == [] and nc.dinh_nghia == []
