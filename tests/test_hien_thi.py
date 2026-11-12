from qltt.hien_thi import gon_bien_phap, gon_so, khung, ten_hanh_vi, ten_ngan, tien

NHAN = (
    "Mức phạt tiền đối với hành vi kinh doanh hàng hóa theo quy định phải có nhãn hàng hóa"
    " mà không có nhãn hàng hóa; không có nhãn gốc hoặc có nhãn gốc nhưng ghi không đủ hoặc"
    " ghi không đúng các nội dung bắt buộc trên nhãn hàng hóa, hoặc bị thay đổi được quy"
    " định như sau:"
)
UU_TIEN = (
    "Đối với hành vi vi phạm quy định tại các khoản 1, 2 và 4 Điều này được thực hiện"
    " theo thứ tự ưu tiên sau: buộc thu hồi hàng hóa"
)
TUOC = (
    "Tước quyền sử dụng giấy phép từ 01 tháng đến 03 tháng đối với hành vi vi phạm quy"
    " định tại khoản 3 khoản 4 Điều này"
)


def test_tien_va_khung():
    assert tien(1_500_000) == "1,5 triệu" and tien(500_000) == "500 nghìn"
    assert khung(1_500_000, 2_500_000) == "1,5 – 2,5 triệu"
    assert khung(500_000, 1_500_000) == "500 nghìn – 1,5 triệu"
    assert khung(None, 3_000_000) == "đến 3 triệu"
    assert gon_so("từ 5.000.000 đồng đến dưới 10.000.000 đồng") == "từ 5 triệu đến dưới 10 triệu"


def test_ten_hanh_vi_va_van_ban():
    mong = "Kinh doanh hàng hóa theo quy định phải có nhãn hàng hóa mà không có nhãn hàng hóa…"
    assert ten_hanh_vi(NHAN) == mong
    assert ten_hanh_vi("Buôn bán hàng nhập lậu") == "Buôn bán hàng nhập lậu"
    assert ten_ngan("119/2017/NĐ-CP") == "NĐ 119/2017"
    assert ten_ngan("66.18/2026/NQ-CP") == "NQ 66.18/2026"
    assert ten_ngan("02/VBHN-BKHCN") == "02/VBHN-BKHCN"


def test_gon_bien_phap():
    assert gon_bien_phap(UU_TIEN) == "Buộc thu hồi hàng hóa"
    assert gon_bien_phap(TUOC) == "Tước quyền sử dụng giấy phép từ 01 tháng đến 03 tháng"


def test_gop_vi_tri_theo_thu_tu_diem():
    from qltt.hien_thi import ViTri, gop

    ds = [ViTri(1, 31, "", 4, "", (d,)) for d in "đabd"] + [ViTri(1, 31, "", 8, "", ("c",))]
    g = gop(ds)
    assert [x.chu() for x in g] == ["điểm a, điểm b, điểm d, điểm đ khoản 4 Điều 31",
                                    "điểm c khoản 8 Điều 31"]  # fmt: skip
