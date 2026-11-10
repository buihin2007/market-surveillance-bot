from qltt.chunk import cat
from qltt.parse import Dieu, Khoan, PhuLuc, VanBanParse


def vb(dieu, loai_goc="NGHỊ ĐỊNH", phu_luc=()):
    return VanBanParse(
        "98/2020/NĐ-CP", None, dieu, list(phu_luc), {}, False, 0, 0, loai_goc, "QUY ĐỊNH XỬ PHẠT"
    )


def dieu(so, ten, khoan=(), chuong="Chương II. HÀNH VI VI PHẠM", dau=""):
    return Dieu(
        so, "", ten, None, chuong, None, dau, [Khoan(i + 1, "", k) for i, k in enumerate(khoan)]
    )


def test_dieu_hanh_vi_cua_nghi_dinh():
    d = dieu(
        9,
        "Buôn bán hàng giả",
        [
            "1. Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng.",
            "2. Hình thức xử phạt bổ sung: tịch thu",
            "3. Biện pháp khắc phục hậu quả: buộc tiêu hủy",
        ],
    )
    ch = cat(vb([d]), "98/2020/NĐ-CP")
    assert [(c.cap, c.duong_dan, c.loai_chunk, c.vai_tro) for c in ch] == [
        ("dieu", "Điều 9", "hanh_vi", "xu_phat"),
        ("khoan", "Điều 9 khoản 1", "hanh_vi", "xu_phat"),
        ("khoan", "Điều 9 khoản 2", "xu_phat_bo_sung", "xu_phat"),
        ("khoan", "Điều 9 khoản 3", "khac_phuc", "xu_phat"),
    ]
    assert all(c.cha == 0 for c in ch[1:])
    assert ch[1].noi_dung_embed.startswith(
        "Nghị định 98/2020/NĐ-CP: Quy định xử phạt › Chương II. HÀNH VI VI PHẠM › "
        "Điều 9. Buôn bán hàng giả › khoản 1\n1. Phạt tiền"
    )


def test_muc_phat_trong_luat_chi_la_quy_pham():
    """Luật XLVPHC Điều 4: chỉ nghị định quy định mức phạt."""
    d = dieu(24, "Mức phạt tiền", ["1. Mức phạt tiền tối đa là 100.000.000 đồng."])
    assert {c.vai_tro for c in cat(vb([d], loai_goc="LUẬT"), "15/2012/QH13")} == {"quy_pham"}


def test_tham_quyen_va_hieu_luc_khong_tim_kiem():
    ch = cat(
        vb(
            [
                dieu(1, "Phạm vi điều chỉnh", chuong="Chương I. QUY ĐỊNH CHUNG"),
                dieu(2, "Giải thích từ ngữ", chuong="Chương I. QUY ĐỊNH CHUNG"),
                dieu(
                    80, "Thẩm quyền xử phạt của Quản lý thị trường", ["1. Phạt tiền đến 50 triệu"]
                ),
                dieu(81, "Thi hành quyết định xử phạt"),  # không phải Điều hiệu lực
                dieu(90, "Hiệu lực thi hành"),
            ]
        ),
        "98/2020/NĐ-CP",
    )
    loai = {(c.dieu_so, c.cap): (c.loai_chunk, c.embed, c.vai_tro) for c in ch}
    assert loai[(1, "dieu")] == ("quy_dinh_chung", True, "quy_pham")
    assert loai[(2, "dieu")][0] == "giai_thich"
    assert loai[(80, "dieu")] == ("tham_quyen", False, "quy_pham")
    assert loai[(80, "khoan")] == ("tham_quyen", False, "quy_pham")
    assert loai[(81, "dieu")][1] is True
    assert loai[(90, "dieu")] == ("hieu_luc", False, "quy_pham")


def test_phu_luc_danh_muc_cat_theo_dong_bieu_mau_bo():
    dai = "\n".join(f"{i}. Mặt hàng số {i} " + "x" * 90 for i in range(1, 80))
    pl = [
        PhuLuc("01", "DANH MỤC HÀNG HÓA BÌNH ỔN GIÁ", dai, True),
        PhuLuc("II", "MẪU ĐƠN", "...", False),
    ]
    ch = cat(vb([dieu(1, "A")], loai_goc="LUẬT", phu_luc=pl), "16/2023/QH15")
    pls = [c for c in ch if c.cap == "phu_luc"]
    assert len(pls) > 1 and all(len(c.noi_dung) <= 3000 for c in pls)
    assert pls[0].duong_dan == f"Phụ lục 01 (phần 1/{len(pls)})"
    assert {c.vai_tro for c in pls} == {"quy_pham"} and all(c.embed for c in pls)
    assert "\n".join(c.noi_dung for c in pls) == dai  # không mất dòng nào
    assert pls[1].noi_dung_embed.startswith(
        "Luật 16/2023/QH15: Quy định xử phạt › Phụ lục 01: DANH MỤC"
    )
