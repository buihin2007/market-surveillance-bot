import pytest
from test_nap import HOM_NAY, dong, nap_docx

from qltt import bien_phap, db, muc_phat, nap
from qltt.bien_phap import ApDung, doc_dan_chieu, tach_khoan


@pytest.mark.parametrize(
    ("ref", "mong"),
    [
        ("khoản 1", [ApDung("1")]),
        ("các điểm a, b và c khoản 1, khoản 2", [ApDung("1", ["a", "b", "c"]), ApDung("2")]),
        ("điểm a và điểm b khoản 1", [ApDung("1", ["a", "b"])]),
        (
            "khoản 1, điểm đ khoản 2, điểm c khoản 3",
            [ApDung("1"), ApDung("2", ["đ"]), ApDung("3", ["c"])],
        ),
        ("các khoản 1, 2 và 3", [ApDung("1"), ApDung("2"), ApDung("3")]),
        ("khoản 1 đến khoản 3", [ApDung("1"), ApDung("2"), ApDung("3")]),
        ("từ điểm đ đến điểm h khoản 1", [ApDung("1", ["đ", "e", "g", "h"])]),
        ("các khoản 8 và 8a", [ApDung("8"), ApDung("8a")]),
        ("", []),  # "tại Điều này": cả Điều
        ("khoản 2 Điều 5", None),  # Điều khác: không đoán
        ("điểm a", None),  # điểm không kèm khoản
    ],
)
def test_doc_dan_chieu(ref, mong):
    assert doc_dan_chieu(ref) == mong


def ap(b):
    return None if b.ap_dung is None else [(a.khoan, a.diem) for a in b.ap_dung]


def test_tach_khoan_cac_dang():
    a, b, c, d = tach_khoan(
        "4. Biện pháp khắc phục hậu quả: a) Buộc tiêu hủy tang vật đối với hành vi vi phạm quy"
        " định tại Điều này, trừ trường hợp áp dụng biện pháp quy định tại điểm b khoản 4 Điều"
        " này; b) Buộc nộp lại số lợi bất hợp pháp có được do thực hiện hành vi vi phạm quy định"
        " tại điểm b khoản 2 và khoản 3 Điều này; c) Buộc cải chính thông tin đối với hành vi tại"
        " khoản 1 trong trường hợp đã cấp và hành vi quy định tại khoản 2 Điều này; d) (được bãi"
        " bỏ); đ) Buộc tái xuất đối với hàng hóa nhập khẩu"
    )
    assert ap(a) == []  # cả Điều; dẫn chiếu sau "trừ trường hợp" không tính
    assert ap(b) == [("2", ["b"]), ("3", [])]  # không có "đối với" vẫn đọc
    assert ap(c) == [("1", []), ("2", [])]  # hai dẫn chiếu trong một câu
    assert (d.diem, ap(d)) == ("đ", None)  # "đối với hàng hóa…": điều kiện, không đoán


def test_cau_dan_truoc_diem():
    a, b = tach_khoan(
        "5. Biện pháp khắc phục hậu quả: Đối với hành vi vi phạm quy định tại khoản 1, điểm đ"
        " khoản 2 Điều này được thực hiện theo thứ tự ưu tiên sau đây: a) Buộc tái xuất đối với"
        " hàng hóa nhập khẩu; b) Buộc thu hồi và tái chế."
    )
    assert ap(a) == ap(b) == [("1", []), ("2", ["đ"])]
    assert a.noi_dung.startswith("Đối với hành vi") and "tái xuất" in a.noi_dung


def test_khong_neu_hanh_vi_la_ca_dieu_nhung_dan_chieu_tran_thi_khong_doan():
    (a,) = tach_khoan("3. Hình thức xử phạt bổ sung: Tịch thu tang vật vi phạm.")
    assert ap(a) == []
    (b,) = tach_khoan(
        "4. Biện pháp khắc phục hậu quả: Buộc nộp lại Giấy phép quy định tại điểm a khoản 2"
        " Điều này"
    )
    assert ap(b) is None


ND = [
    "Điều 1. Phạm vi điều chỉnh",
    "Chương II",
    "HÀNH VI VI PHẠM",
    "Điều 2. Kinh doanh hàng nhập lậu",
    "1. Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng đối với một trong các hành vi sau đây:",
    "a) Bán hàng nhập lậu;",
    "b) Vận chuyển hàng nhập lậu.",
    "2. Phạt tiền từ 3.000.000 đồng đến 5.000.000 đồng đối với hành vi tàng trữ hàng nhập lậu.",
    "3. Hình thức xử phạt bổ sung:",
    "a) Tịch thu tang vật vi phạm;",
    "b) Tước quyền sử dụng giấy phép kinh doanh từ 01 tháng đến 03 tháng đối với hành vi vi phạm"
    " quy định tại điểm a khoản 1 Điều này.",
    "4. Biện pháp khắc phục hậu quả:",
    "a) Buộc tiêu hủy hàng hóa đối với hành vi quy định tại khoản 2 Điều này;",
    "b) Buộc nộp lại Giấy phép quy định tại khoản 1 Điều này.",
    "Điều 3. Hiệu lực thi hành",
]


@pytest.fixture
def kho(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    nap_docx(conn, tmp_path, dong(1, "98/2020/NĐ-CP"), ND)
    nap.tinh_lai(conn, HOM_NAY)
    conn.execute("UPDATE van_ban SET ten = 'QUY ĐỊNH XỬ PHẠT VI PHẠM HÀNH CHÍNH TRONG THƯƠNG MẠI'")
    muc_phat.dung_lai(conn)
    dem = bien_phap.dung_lai(conn)
    assert dem == {"bo_sung": 2, "khac_phuc": 2, "khong_doc_duoc": 1}
    return conn


def test_tra_bien_phap_theo_diem(kho):
    kq = bien_phap.tra_bien_phap(kho, 1, 2, "", 1, "a")
    assert [(x.loai, x.diem, x.chac) for x in kq] == [
        ("khac_phuc", "b", False),  # không đọc được: luôn trả, bot trích nguyên văn
        ("bo_sung", "a", True),  # cả Điều
        ("bo_sung", "b", True),  # đúng điểm a khoản 1
    ]


def test_tra_bien_phap_diem_khac_va_chua_biet_diem(kho):
    kq = bien_phap.tra_bien_phap(kho, 1, 2, "", 1, "b")
    assert ("bo_sung", "b") not in [(x.loai, x.diem) for x in kq]  # chỉ áp điểm a
    kq = bien_phap.tra_bien_phap(kho, 1, 2, "", 1)
    tuoc = next(x for x in kq if x.loai == "bo_sung" and x.diem == "b")
    assert not tuoc.chac and "điểm a" in tuoc.ghi_chu


def test_tra_bien_phap_khoan_2(kho):
    kq = bien_phap.tra_bien_phap(kho, 1, 2, "", 2)
    assert [(x.loai, x.diem, x.chac) for x in kq] == [
        ("khac_phuc", "a", True),
        ("khac_phuc", "b", False),
        ("bo_sung", "a", True),
    ]


def test_ca_dieu_nhung_co_dieu_kien_theo_khoan_thi_khong_khang_dinh():
    a, b = tach_khoan(
        "11. Hình thức xử phạt bổ sung: a) Tịch thu tang vật đối với hành vi vi phạm quy định tại"
        " Điều này, trừ trường hợp áp dụng biện pháp quy định tại điểm a khoản 12 Điều này;"
        " b) Tịch thu phương tiện vận tải đối với hành vi vi phạm quy định tại Điều này trong"
        " trường hợp hàng cấm có số lượng quy định tại khoản 6, 7 và 8 Điều này"
    )
    assert ap(a) == []  # "trừ trường hợp": vẫn cả Điều
    assert ap(b) is None  # "trong trường hợp … khoản 6, 7 và 8": bot trích nguyên văn
