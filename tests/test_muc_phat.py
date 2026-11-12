import pytest
from test_nap import HOM_NAY, dong, nap_docx

from qltt import db, muc_phat, nap
from qltt.muc_phat import ca_nhan_to_chuc, dieu_kien, muc_cua, tach_khoan


def test_dang_a_diem_la_hanh_vi_chung_khung():
    ds = tach_khoan(
        "1. Phạt tiền từ 3.000.000 đồng đến 5.000.000 đồng đối với một trong các hành vi vi phạm"
        " sau đây: a) Viết thêm, tẩy xóa giấy phép kinh doanh; b) Cho thuê giấy phép kinh doanh."
    )
    assert [(d.diem, d.khung.loai, d.khung.tu, d.khung.den) for d in ds] == [
        ("a", "tien", 3_000_000, 5_000_000),
        ("b", "tien", 3_000_000, 5_000_000),
    ]
    assert ds[1].hanh_vi == "Cho thuê giấy phép kinh doanh"


def test_dang_a_dieu_kien_o_tung_diem():
    (a, b) = tach_khoan(
        "1. Phạt tiền từ 1.000.000 đồng đến 3.000.000 đồng đối với một trong các hành vi vi phạm"
        " sau: a) Buôn bán thuốc bảo vệ thực vật cấm có số lượng dưới 5 kilôgam hoặc dưới 5 lít;"
        " b) Buôn bán thuốc lá điếu nhập lậu có số lượng dưới 50 bao (1 bao = 20 điếu);"
    )
    assert (a.dk.den, a.dk.don_vi, a.dk.doi_tuong) == (5, "kilôgam", "so_luong")
    assert (b.dk.den, b.dk.den_bao_gom, b.dk.don_vi) == (50, False, "bao")


def test_dang_b_diem_la_bac_phat():
    ds = tach_khoan(
        "1. Đối với hành vi buôn bán hàng giả về giá trị sử dụng, mức phạt tiền như sau:"
        " a) Phạt tiền từ 1.000.000 đồng đến 3.000.000 đồng trong trường hợp hàng thật có trị giá"
        " dưới 3.000.000 đồng; b) Phạt tiền từ 3.000.000 đồng đến 5.000.000 đồng trong trường hợp"
        " hàng thật có trị giá từ 3.000.000 đồng đến dưới 5.000.000 đồng; c) Phạt tiền từ"
        " 40.000.000 đồng đến 50.000.000 đồng trong trường hợp trị giá từ 100.000.000 đồng trở lên"
    )
    assert len({d.hanh_vi for d in ds}) == 1  # cùng một hành vi ở đầu khoản
    dk = [(d.dk.tu, d.dk.tu_bao_gom, d.dk.den, d.dk.den_bao_gom) for d in ds]
    assert dk == [
        (None, True, 3_000_000, False),
        (3_000_000, True, 5_000_000, False),
        (100_000_000, True, None, False),
    ]
    assert {d.dk.doi_tuong for d in ds} == {"gia_tri"}


def test_khoan_khong_chia_diem_dieu_kien_o_dau_va_loi_go_nguon():
    (d,) = tach_khoan(
        "7. Phạt tiền từ 85.000.000 đồng đến 120.000.000 đồng đối với một trong các hành vi vi phạm"
        " quy định tại Khoản 1 Điều này trong trường hợp giá trị hàng hóa vi phạm tư trên"
        " 100.000.000 đồng đến 200.000.000 đồng."
    )
    assert (d.dk.tu, d.dk.tu_bao_gom, d.dk.den, d.dk.den_bao_gom) == (
        100_000_000, False, 200_000_000, True
    )  # fmt: skip
    assert d.hanh_vi_tai == [1]


@pytest.mark.parametrize(
    ("chu", "loai", "mong"),
    [
        (
            "9. Phạt tiền gấp hai lần mức tiền phạt quy định từ khoản 1 đến khoản 3 Điều này"
            " đối với hành vi sản xuất hàng cấm.",
            "gap_lan", {"he_so": 2, "tham_chieu": [1, 2, 3]},
        ),
        (
            "10. Phạt tiền bằng 1,2 lần mức tiền phạt quy định từ Khoản 1 đến Khoản 2 Điều này"
            " nhưng không vượt quá 250.000.000 đồng đối với hành vi sản xuất.",
            "gap_lan", {"he_so": 1.2, "tham_chieu": [1, 2], "tran": 250_000_000},
        ),
        (
            "3. Các mức phạt tiền quy định tại khoản 1 và 2 Điều này cũng được áp dụng đối với"
            " hành vi cố ý vận chuyển hàng nhập lậu.",
            "gap_lan", {"he_so": 1, "tham_chieu": [1, 2]},
        ),
        (
            "5. Phạt tiền từ 01 lần đến 02 lần tổng giá trị sản phẩm, hàng hóa đã tiêu thụ.",
            "lan_gia_tri", {"he_so": 1, "he_so_den": 2},
        ),
        (
            "1. Phạt cảnh cáo hoặc phạt tiền từ 300.000 đồng đến 500.000 đồng đối với hành vi kinh"
            " doanh hàng hóa không rõ nguồn gốc.",
            "canh_cao_hoac_tien", {"tu": 300_000, "den": 500_000},
        ),
        ("1. Phạt cảnh cáo đối với hành vi không niêm yết.", "canh_cao", {}),
        (  # chủ thể chen giữa "Phạt tiền" và "từ"
            "5. Phạt tiền đơn vị cung cấp thiết bị giám sát hành trình tàu cá từ 30.000.000 đồng"
            " đến 50.000.000 đồng vi phạm hành vi không kẹp chì.",
            "tien", {"tu": 30_000_000, "den": 50_000_000},
        ),
        (  # lỗi nguồn: số sau thiếu "đồng"
            "4. Phạt tiền từ 60.000.000 đồng đến 100.000.000 đối với hành vi chế bản, in.",
            "tien", {"tu": 60_000_000, "den": 100_000_000},
        ),
        (
            "4. Phạt tiền từ 60% đến 70% giá trị sản phẩm động vật nhưng không vượt quá"
            " 50.000.000 đồng đối với hành vi vận chuyển thịt không có dấu kiểm soát giết mổ.",
            "lan_gia_tri", {"he_so": 0.6, "he_so_den": 0.7, "tran": 50_000_000},
        ),

        (
            "3. Phạt tiền từ 10.000.000 đến 20.000.000 đồng đối với hành vi sử dụng thiết bị.",
            "tien", {"tu": 10_000_000, "den": 20_000_000},
        ),
        (
            "2. Sửa đổi, bổ sung khoản 4 như sau: “4. Phạt tiền từ 1.000.000 đồng đến 2.000.000"
            " đồng…”",
            "sua_doi", {},
        ),
        ("4. Áp dụng quy định tại Điều 3 để xác định giá trị.", "khong_tach", {}),
    ],
)  # fmt: skip
def test_cac_loai_khung(chu, loai, mong):
    (d,) = tach_khoan(chu)
    assert d.khung.loai == loai
    for k, v in mong.items():
        assert getattr(d.khung, k) == v


def test_khong_nham_lan_gia_tri_thanh_tien():
    # "từ 01 đến 02 lần" không được đọc thành 1–2 đồng khi bỏ chữ "đồng" ở số sau
    (d,) = tach_khoan("5. Phạt tiền từ 01 đến 02 lần tổng giá trị hàng hóa vi phạm.")
    assert d.khung.loai == "lan_gia_tri"


def test_gap_lan_theo_diem_khoan_nay():
    ds = tach_khoan(
        "2. Phạt tiền đối với hành vi buôn bán hàng hóa không bảo đảm chất lượng như sau:"
        " a) Phạt tiền từ 1.000.000 đồng đến 3.000.000 đồng trong trường hợp hàng hóa vi phạm có"
        " giá trị đến 10.000.000 đồng; b) Phạt tiền gấp 02 lần mức tiền phạt quy định tại điểm a"
        " khoản này trong trường hợp hàng hóa vi phạm là thực phẩm.",
        khoan=2,
    )
    assert (ds[1].khung.loai, ds[1].khung.he_so, ds[1].khung.tham_chieu) == ("gap_lan", 2, [2])


def test_bac_phat_canh_cao_va_khong_lap_chu_phat_tien():
    a, b = tach_khoan(
        "1. Cảnh cáo hoặc phạt tiền đối với hành vi không tuyên truyền theo một trong các mức sau"
        " đây: a) Cảnh cáo đối với cơ sở có sử dụng lao động dưới 50 người; b) Phạt tiền từ"
        " 1.000.000 đồng đến 2.000.000 đồng đối với cơ sở có sử dụng từ 50 người đến dưới 500 người"
    )
    assert (a.khung.loai, b.khung.loai, b.khung.tu) == ("canh_cao", "tien", 1_000_000)
    (c,) = tach_khoan(
        "3. Phạt tiền đối với thuyền trưởng không có văn bằng như sau: a) Từ 2.000.000 đến"
        " 3.000.000 đồng đối với tàu có chiều dài lớn nhất từ 12 đến dưới 15 mét"
    )
    assert (c.khung.tu, c.khung.den, c.dk.don_vi) == (2_000_000, 3_000_000, "mét")


def test_bo_diem_la_tieu_de_bien_phap():
    ds = tach_khoan(
        "1. Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng đối với hành vi không nộp phí: a) Không"
        " nộp phí duy trì; b) Biện pháp khắc phục hậu quả Buộc nộp phí duy trì đúng quy định"
    )
    assert [d.diem for d in ds] == ["a"]


def test_dieu_kien_khong_lay_nham_so_tien_phat():
    assert dieu_kien("Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng đối với hành vi X") is None
    dk = dieu_kien("trong trường hợp số lợi bất hợp pháp thu được từ 20.000.000 đồng trở lên")
    assert (dk.tu, dk.doi_tuong) == (20_000_000, "so_loi")


def test_muc_cua():
    assert muc_cua(
        [
            "Điều 4. 1. Mức phạt tiền quy định tại Chương II của Nghị định này là mức phạt tiền"
            " áp dụng đối với hành vi vi phạm hành chính do cá nhân thực hiện, trừ các hành vi"
            " quy định tại Điều 33, Điều 34 và Điều 35. Tổ chức gấp 02 lần."
        ]
    ) == (
        "ca_nhan",
        [{"dieu": "33", "cua": "to_chuc"}, {"dieu": "34", "cua": "to_chuc"},
         {"dieu": "35", "cua": "to_chuc"}],
        "van_ban",
    )  # fmt: skip
    assert muc_cua(["Mức phạt tiền quy định tại Nghị định này là áp dụng đối với tổ chức."])[0] == (
        "to_chuc"
    )
    assert muc_cua(
        ["Đối với cùng một hành vi thì mức phạt tiền đối với tổ chức gấp 02 lần mức phạt tiền"
         " đối với cá nhân."]
    ) == ("ca_nhan", [], "suy_ra")  # fmt: skip
    assert muc_cua(["Không nói gì về mức phạt."]) == (None, [], None)


def test_ca_nhan_to_chuc():
    assert ca_nhan_to_chuc(1_000_000, 2_000_000, "ca_nhan") == (
        (1_000_000, 2_000_000), (2_000_000, 4_000_000)
    )  # fmt: skip
    assert ca_nhan_to_chuc(1_000_000, 2_000_000, "to_chuc") == (
        (500_000, 1_000_000), (1_000_000, 2_000_000)
    )  # fmt: skip
    assert ca_nhan_to_chuc(1, 2, None) is None


ND = [
    "Điều 1. Phạm vi điều chỉnh",
    "Điều 2. Áp dụng mức phạt",
    "Mức phạt tiền quy định tại Chương II Nghị định này là mức phạt đối với cá nhân.",
    "Chương II",
    "HÀNH VI VI PHẠM",
    "Điều 3. Kinh doanh hàng nhập lậu",
    "1. Đối với hành vi kinh doanh hàng hóa nhập lậu, mức phạt tiền như sau:",
    "a) Phạt tiền từ 500.000 đồng đến 1.000.000 đồng trong trường hợp trị giá dưới 3.000.000 đồng;",
    "b) Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng trong trường hợp trị giá từ 3.000.000 đồng"
    " trở lên.",
    "2. Phạt tiền gấp hai lần mức tiền phạt quy định tại khoản 1 Điều này trong trường hợp hàng là"
    " thực phẩm.",
    "3. Các mức phạt tiền quy định tại khoản 1 Điều này cũng được áp dụng đối với: a) Vận chuyển"
    " hàng nhập lậu; b) Tàng trữ hàng nhập lậu.",
    "4. Phạt tiền bằng mức tiền phạt tối đa của khung tiền phạt đối với hành vi quy định tại khoản"
    " 1 Điều này trong trường hợp tái phạm.",
    "5. Hình thức xử phạt bổ sung: Tịch thu tang vật.",
    "Điều 4. Vi phạm về nhãn hàng hóa",
    "1. Mức phạt tiền đối với hành vi kinh doanh hàng hóa không có nhãn như sau:",
    "a) Phạt tiền từ 500.000 đồng đến 1.000.000 đồng trong trường hợp hàng hóa vi phạm có giá trị"
    " dưới 5.000.000 đồng;",
    "b) Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng trong trường hợp hàng hóa vi phạm có giá trị"
    " từ 5.000.000 đồng trở lên;",
    "c) Phạt tiền gấp 02 lần mức tiền phạt quy định tại các điểm a và b khoản này trong trường hợp"
    " hàng hóa vi phạm là: thực phẩm, thuốc.",
    "Điều 5. Hiệu lực thi hành",
]


@pytest.fixture
def kho(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    nap_docx(conn, tmp_path, dong(1, "98/2020/NĐ-CP"), ND)
    nap.tinh_lai(conn, HOM_NAY)
    conn.execute("UPDATE van_ban SET ten = 'QUY ĐỊNH XỬ PHẠT VI PHẠM HÀNH CHÍNH TRONG THƯƠNG MẠI'")
    muc_phat.dung_lai(conn)
    return conn


def test_dung_lai_va_tra_theo_gia_tri(kho):
    assert kho.execute("SELECT mucphat_cua, mucphat_cua_nguon FROM van_ban").fetchone() == (
        "ca_nhan", "van_ban"
    )  # fmt: skip
    kq = muc_phat.tra(kho, 1, 3, "", 1, gia_tri=5_000_000)
    assert kq.da_loc_gia_tri
    assert [(m.diem, m.ca_nhan, m.to_chuc) for m in kq.muc] == [
        ("b", (1_000_000, 2_000_000), (2_000_000, 4_000_000))
    ]
    # khoản 2 "gấp hai lần khoản 1": tình tiết tăng nặng, áp trên bậc đã chọn
    assert [(m.khoan, m.ca_nhan) for m in kq.tang_nang] == [(2, (2_000_000, 4_000_000))]
    assert "thực phẩm" in kq.tang_nang[0].dieu_kien
    # khoản 4 không tách được nhưng có thể đổi mức: trả nguyên văn để bot trích
    assert [(k, d) for k, d, _ in kq.nguyen_van] == [(4, None)]
    assert "mức tiền phạt tối đa" in kq.nguyen_van[0][2]


def test_tra_chua_biet_gia_tri_thi_tra_moi_bac(kho):
    kq = muc_phat.tra(kho, 1, 3, "", 1)
    assert not kq.da_loc_gia_tri and [m.diem for m in kq.muc] == ["a", "b"]


def test_tra_hanh_vi_dung_khung_khoan_khac(kho):
    kq = muc_phat.tra(kho, 1, 3, "", 3, "a", gia_tri=1_000_000)
    assert [(m.khoan, m.diem, m.ca_nhan) for m in kq.muc] == [(3, "a", (500_000, 1_000_000))]
    assert "khoản 1" in kq.muc[0].ghi_chu


def test_bo_dieu_thu_tuc_va_van_ban_khong_phai_nghi_dinh_xu_phat(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    thu_tuc = [
        "Điều 5. Xác định số lợi bất hợp pháp",
        "1. Việc xác định số lợi bất hợp pháp để buộc nộp lại khi áp dụng biện pháp khắc phục.",
        "Điều 6. Hiệu lực thi hành",
    ]
    nap_docx(conn, tmp_path, dong(1, "98/2020/NĐ-CP"), [*ND[:-1], *thu_tuc])
    nap.tinh_lai(conn, HOM_NAY)
    conn.execute("UPDATE van_ban SET ten = 'QUY ĐỊNH XỬ PHẠT VI PHẠM HÀNH CHÍNH TRONG THƯƠNG MẠI'")
    muc_phat.dung_lai(conn)
    dieu = {r[0] for r in conn.execute("SELECT DISTINCT dieu_so FROM muc_phat")}
    assert dieu == {3, 4}  # Điều 5 thủ tục: không khoản nào ra khung phạt → bỏ
    conn.execute(
        "UPDATE van_ban SET ten = 'QUY ĐỊNH CHI TIẾT THI HÀNH LUẬT XỬ LÝ VI PHẠM HÀNH CHÍNH'"
    )
    muc_phat.dung_lai(conn)
    assert conn.execute("SELECT count(*) FROM muc_phat").fetchone()[0] == 0


def test_khoan_bo_sung_khong_vao_bang(kho):
    assert kho.execute("SELECT count(*) FROM muc_phat WHERE khoan_so = 5").fetchone()[0] == 0


def test_gap_lan_trong_khoan_la_tang_nang(kho):
    # "c) gấp 02 lần các điểm a, b khoản này … là thực phẩm": không phải bậc thường
    kq = muc_phat.tra(kho, 1, 4, "", 1)
    assert [m.diem for m in kq.muc] == ["a", "b"]
    (t,) = kq.tang_nang
    assert (t.diem, t.tu, t.ghi_chu) == ("c", None, "gấp 2 lần các mức trên")
    assert "thực phẩm, thuốc" in t.dieu_kien
    kq = muc_phat.tra(kho, 1, 4, "", 1, gia_tri=1_000_000)
    assert [m.diem for m in kq.muc] == ["a"]
    assert [(m.diem, m.ca_nhan) for m in kq.tang_nang] == [("c", (1_000_000, 2_000_000))]
