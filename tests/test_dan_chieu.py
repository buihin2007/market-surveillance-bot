from types import SimpleNamespace as NS

from qltt.dan_chieu import BangLuat, tim


def bang_gia():
    b = BangLuat.__new__(BangLuat)
    b.tra = {"19/2023/QH15": 1, "15/2012/QH13": 2, "17/2023/NĐ-CP": 3}
    b.luat = {"bao ve quyen loi nguoi tieu dung": "19/2023/QH15",
              "xu ly vi pham hanh chinh": "15/2012/QH13", "gia": "16/2023/QH15"}  # fmt: skip
    b.ten = {"bao ve quyen loi nguoi tieu dung": "Bảo vệ quyền lợi người tiêu dùng",
             "xu ly vi pham hanh chinh": "Xử lý vi phạm hành chính", "gia": "Giá",
             "phong, chong tac hai cua thuoc la": "Phòng, chống tác hại của thuốc lá"}  # fmt: skip
    return b


def kq(text):
    return [(x.den_loai, x.den_khoa, x.trang_thai, x.den_dieu, x.den_khoan)
            for x in tim(bang_gia(), 1, "98/2020/NĐ-CP", text)]  # fmt: skip


def test_ten_luat_va_vi_tri():
    assert kq("theo quy định tại khoản 2 Điều 3 Luật Xử lý vi phạm hành chính và khoản 1") == [
        ("ten_luat", "Xử lý vi phạm hành chính", "ok", 3, 2)
    ]
    # luật ngoài kho: cắt tên ở "số"; số hiệu ngay sau tên là của chính luật đó (một dẫn chiếu)
    assert kq("quy định tại Điều 30 Luật Hóa chất số 06/2007/QH12") == [
        ("ten_luat", "Hóa chất", "thieu_van_ban", 30, None)
    ]
    # tên không khớp kho nhưng số hiệu khớp → nối theo số
    assert kq("Luật Bảo vệ người tiêu dùng số 19/2023/QH15") == [
        ("ten_luat", "Bảo vệ người tiêu dùng", "ok", None, None)
    ]
    assert kq("Luật số 56/2024/QH15 sửa đổi") == [
        ("so_hieu", "56/2024/QH15", "thieu_van_ban", None, None)
    ]


def test_so_hieu_bo_chinh_no():
    assert kq("Nghị định số 98/2020/NĐ-CP và Điều 5 Nghị định số 17/2023/NĐ-CP") == [
        ("so_hieu", "17/2023/NĐ-CP", "ok", 5, None)
    ]


def test_chu_de():
    assert kq("theo quy định của pháp luật về thẩm định giá sau thời gian 15 ngày") == [
        ("chu_de", "pháp luật về thẩm định giá → Luật Giá", "thieu_van_ban", None, None)
    ]
    assert kq("vi phạm pháp luật về bảo vệ quyền lợi người tiêu dùng và quảng cáo") == [
        ("chu_de", "pháp luật về bảo vệ quyền lợi người tiêu dùng → Luật Bảo vệ quyền lợi"
         " người tiêu dùng", "ok", None, None)]  # fmt: skip
    assert kq("pháp luật về phòng, chống tác hại của thuốc lá thì") == [
        ("chu_de", "pháp luật về phòng, chống tác hại của thuốc lá → Luật Phòng, chống tác hại"
         " của thuốc lá", "thieu_van_ban", None, None)]  # fmt: skip
    assert kq("pháp luật về nhãn hàng hóa;")[0][1:3] == (
        "pháp luật về nhãn hàng hóa → 43/2017/NĐ-CP",
        "thieu_van_ban",
    )
    assert kq("pháp luật về tính chính xác của số liệu")[0][2] == "chua_anh_xa"
    assert NS  # dùng import
