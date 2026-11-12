import json

import pytest
from test_tra_loi import C, Gia, kho  # noqa: F401  (kho là fixture)

from qltt import danh_gia, nhat_ky, tra_loi


def tra_loi_va_ghi(kho, chon=lambda ma: ma[:1]):  # noqa: F811
    tl = tra_loi.hoi(kho, Gia(chon=chon), C, "bán hàng nhập lậu")
    return tl, nhat_ky.ghi(kho, tl, C)


def test_ghi_vet_du_de_tra_lai(kho):  # noqa: F811
    tl, ma = tra_loi_va_ghi(kho)
    loai, kq, vet = kho.execute(
        "SELECT loai_ket_qua, ket_qua, vet FROM chat_log WHERE id = %s", [ma]
    ).fetchone()
    assert loai == "tra_loi"
    assert kq["chon"][0]["dieu"] == "2" and kq["van_ban"] == tl.van_ban
    assert vet["viet_lai"] == ["buôn bán hàng hóa nhập lậu"]
    assert {x["dieu"] for x in vet["ung_vien_dieu"]} >= {"2", "3"}
    assert vet["phien_ban"]["chon"] == tra_loi.PHIEN_BAN_CHON
    assert [b["ten"] for b in vet["buoc"]][0] == "hiểu câu hỏi"


@pytest.mark.parametrize(
    ("ly_do", "mong"),
    [
        ("sai rồi, phải là Điều 2", "muc_phat"),  # đã chọn đúng Điều → sai ở khoản / mức
        ("phải là Điều 3 mới đúng", "chon"),  # Điều 3 có trong ứng viên nhưng không được chọn
        ("phải là Điều 15 nghị định 98/2020/NĐ-CP", "tim_kiem"),  # không có trong ứng viên
        ("Điều 3 nghị định 98/2020/NĐ-CP", "chon"),  # số hiệu gốc: quy về văn bản đang tra
        ("Điều 3 nghị định 99/2099/NĐ-CP", "chon"),  # số hiệu lạ: chỉ so số Điều
        ("sai", None),  # không nêu căn cứ: không đoán
    ],
)
def test_bao_sai_va_goi_y_khau_hong(kho, ly_do, mong):  # noqa: F811
    _, ma = tra_loi_va_ghi(kho)
    i = nhat_ky.bao_sai(kho, ma, ly_do)
    assert nhat_ky.goi_y(kho, i) == mong
    assert kho.execute("SELECT bao_sai FROM chat_log WHERE id = %s", [ma]).fetchone()[0]


def test_bao_sai_ma_khong_co(kho):  # noqa: F811
    with pytest.raises(ValueError, match="không có câu trả lời"):
        nhat_ky.bao_sai(kho, 999_999, "x")


def test_xu_ly(kho):  # noqa: F811
    _, ma = tra_loi_va_ghi(kho)
    i = nhat_ky.bao_sai(kho, ma, "sai")
    nhat_ky.xu_ly(kho, i, "da_sua", "chon", "sửa prompt c3")
    assert kho.execute(
        "SELECT trang_thai, nguyen_nhan, ghi_chu_xu_ly FROM bao_sai WHERE id = %s", [i]
    ).fetchone() == ("da_sua", "chon", "sửa prompt c3")
    with pytest.raises(ValueError):
        nhat_ky.xu_ly(kho, i, "xong")


def test_thanh_case_moi_case_thu_4_vao_giu_lai(kho, tmp_path):  # noqa: F811
    f = tmp_path / "cases.jsonl"
    f.write_text("", encoding="utf-8")
    ids = []
    for _ in range(4):
        _, ma = tra_loi_va_ghi(kho)
        i = nhat_ky.bao_sai(kho, ma, "phải là Điều 3")
        ids.append(nhat_ky.thanh_case(kho, i, f, "98/2020/NĐ-CP", "3", [1], ["a"]))
    assert ids == ["BS-001", "BS-002", "BS-003", "BS-004"]
    cases = danh_gia.doc_cases(f)  # hợp lệ theo bộ kiểm của eval
    assert [c.giu_lai for c in cases] == [False, False, False, True]
    assert cases[0].kiem == "nguoi_da_kiem" and cases[0].cau_hoi == "bán hàng nhập lậu"
    dong = json.loads(f.read_text(encoding="utf-8").splitlines()[0])
    assert dong["can_cu"] == [
        {"van_ban": "98/2020/NĐ-CP", "dieu": "3", "khoan": [1], "diem": ["a"]}
    ]


@pytest.mark.parametrize(
    ("kieu", "ly_do", "mong"),
    [
        ("van_ban_cu", "", "kho_thieu"),
        ("sai_bien_phap", "", "bien_phap"),
        ("sai_muc_phat", "", "muc_phat"),
        ("sai_muc_phat", "phải là Điều 3", "chon"),  # căn cứ là Điều khác: lỗi ở bước chọn
        ("sai_hanh_vi", "", None),  # không căn cứ: ikm xem vết
        ("sai_hanh_vi", "Điều 15 NĐ 98/2020/NĐ-CP", "tim_kiem"),
        (None, "", None),
    ],
)
def test_goi_y_theo_loai_loi_va_can_cu(kho, kieu, ly_do, mong):  # noqa: F811
    _, ma = tra_loi_va_ghi(kho)
    i = nhat_ky.bao_sai(kho, ma, ly_do, kieu=kieu)
    assert nhat_ky.goi_y(kho, i) == mong
    assert kho.execute("SELECT kieu FROM bao_sai WHERE id = %s", [i]).fetchone()[0] == kieu


def test_loai_loi_la_va_nut_theo_cau_tra_loi(kho):  # noqa: F811
    _, ma = tra_loi_va_ghi(kho)
    with pytest.raises(ValueError, match="loại lỗi"):
        nhat_ky.bao_sai(kho, ma, kieu="sai_gi_do")
    assert "khong_tim_thay" not in nhat_ky.kieu_cho("tra_loi")
    assert nhat_ky.kieu_cho("khong_tim_thay")[0] == "khong_tim_thay"
    assert set(nhat_ky.kieu_cho("tra_loi")) <= set(nhat_ky.KIEU)
