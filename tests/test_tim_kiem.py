from datetime import date

import pytest
from test_embed import ApiGia
from test_nap import HOM_NAY, ND_98, dong, nap_docx

from qltt import db, embed, nap, tim_kiem


def test_truy_van_tu_khoa():
    assert tim_kiem.truy_van_tu_khoa("Bán thuốc lá ở cổng trường?") == (
        "('bán' <-> 'thuốc') | ('thuốc' <-> 'lá') | ('lá' <-> 'ở') | ('ở' <-> 'cổng')"
        " | ('cổng' <-> 'trường')"
    )
    assert tim_kiem.truy_van_tu_khoa("giò") == "'giò'"
    assert tim_kiem.truy_van_tu_khoa(" ?! ") == ""


def test_rrf_uu_tien_chunk_co_o_ca_hai_nhanh():
    assert tim_kiem.rrf([1, 2, 3], [3, 4]) == [3, 1, 2, 4]


def test_rrf_co_trong_so():
    # nhánh 2 nhẹ: chunk 9 đứng đầu nhánh 2 vẫn sau chunk 1, 2 của nhánh 1
    assert tim_kiem.rrf([1, 2], [9], trong_so=(1.0, 0.5)) == [1, 2, 9]
    assert tim_kiem.rrf([1, 2], [9], trong_so=(1.0, 1.0)) == [1, 9, 2]


SO_CHIEU = 32


def mot_chieu(i: int, n: int = SO_CHIEU) -> list[float]:
    v = [0.0] * n
    v[i] = 1.0
    return v


@pytest.fixture
def kho(conn, tmp_path):
    """98/2020 gốc (không tra) + VBHN (tra); vector chunk i = trục i."""
    db.khoi_tao(conn, xoa_dan_xuat=True)
    nap_docx(conn, tmp_path, dong(406627, "98/2020/NĐ-CP"), ND_98, ten="goc.docx")
    nap_docx(
        conn, tmp_path, dong(654519, "03/VBHN-BCT", loai="vbhn", ngay=date(2025, 4, 23)), ND_98,
        ten="vbhn.docx", ngay="ngày 23 tháng 4 năm 2025",
        dau=["Nghị định số 98/2020/NĐ-CP ngày 26 tháng 8 năm 2020, được sửa đổi bởi:"],
    )  # fmt: skip
    nap.tinh_lai(conn, HOM_NAY)
    for i, (cid,) in enumerate(conn.execute("SELECT id FROM chunk ORDER BY id").fetchall()):
        conn.execute(
            "UPDATE chunk SET embedding = %s::vector WHERE id = %s AND embed",
            [embed._vec(mot_chieu(i)), cid],
        )
    return conn


def id_chunk(conn, tvpl_id, duong_dan):
    return conn.execute(
        "SELECT id FROM chunk WHERE tvpl_id = %s AND duong_dan = %s", [tvpl_id, duong_dan]
    ).fetchone()[0]


def test_tim_chi_tra_chunk_duoc_tim_cua_van_ban_dang_dung(kho):
    dich = id_chunk(kho, 654519, "Điều 2 khoản 1")
    i = kho.execute("SELECT count(*) FROM chunk WHERE id < %s", [dich]).fetchone()[0]

    kq = tim_kiem.tim(kho, "buôn bán hàng giả", mot_chieu(i))

    assert kq["vector"][0] == dich
    dieu_2 = id_chunk(kho, 654519, "Điều 2")
    assert kq["tu_khoa"][0] in {dich, dieu_2}
    assert set(kq["lai"][:2]) == {dich, dieu_2}  # hai chunk cùng điểm RRF
    dung = {
        r[0]
        for r in kho.execute(
            "SELECT c.id FROM chunk c JOIN van_ban v USING (tvpl_id)"
            " WHERE c.embed AND v.dung_de_tra"
        )
    }
    for nhanh in tim_kiem.NHANH:
        assert set(kq[nhanh]) <= dung  # không có văn bản gốc, không có Điều thẩm quyền
    chi_tiet = tim_kiem.chi_tiet(kho, [dich])[0]
    assert (chi_tiet.so_hieu, chi_tiet.duong_dan, chi_tiet.vi_tri) == (
        "03/VBHN-BCT",
        "Điều 2 khoản 1",
        (654519, 2, "", 1),
    )


def test_mac_dinh_chi_chunk_xu_phat(kho):
    vai_tro = dict(kho.execute("SELECT id, vai_tro FROM chunk").fetchall())
    q = mot_chieu(0)  # gần chunk đầu tiên: Điều 1 quy định chung (quy phạm)

    mac_dinh = tim_kiem.tim(kho, "phạm vi điều chỉnh", q)
    tat_ca = tim_kiem.tim(kho, "phạm vi điều chỉnh", q, tim_kiem.Loc(None))

    assert {vai_tro[i] for n in tim_kiem.NHANH for i in mac_dinh[n]} == {"xu_phat"}
    loai = dict(kho.execute("SELECT id, loai_chunk FROM chunk").fetchall())
    assert not {loai[i] for n in tim_kiem.NHANH for i in mac_dinh[n]} & {
        "xu_phat_bo_sung", "khac_phuc"
    }  # fmt: skip
    co_bo_sung = tim_kiem.tim(kho, "tịch thu", None, tim_kiem.Loc())["tu_khoa"]
    assert "xu_phat_bo_sung" in {loai[i] for i in co_bo_sung}  # Loc() trống: không loại
    assert "quy_pham" in {vai_tro[i] for i in tat_ca["vector"]}


def test_bo_qua_vector_cua_model_khac_so_chieu(kho):
    dich = id_chunk(kho, 654519, "Điều 2 khoản 1")
    kho.execute("UPDATE chunk SET embedding = %s::vector WHERE id = %s", [str([1.0] * 5), dich])

    kq = tim_kiem.nhanh_vector(kho, mot_chieu(0))  # không lỗi "different vector dimensions"
    assert dich not in kq and kq


def test_khong_co_vector_thi_chi_tu_khoa(kho):
    kq = tim_kiem.tim(kho, "hàng giả", None)
    assert kq["vector"] == [] and kq["lai"] == kq["tu_khoa"] != []


def test_vector_cau_hoi_dung_cache(conn):
    db.khoi_tao(conn)
    conn.execute("DELETE FROM embed_cache")
    api = ApiGia()
    v1, token = tim_kiem.vector_cau_hoi(conn, api, "m", ["ab", "abc", "ab"])
    assert api.goi == [["ab", "abc"]] and token == 20  # câu trùng chỉ gửi một lần
    assert v1[0] == v1[2] and v1[1][-1] == 3.0

    v2, token2 = tim_kiem.vector_cau_hoi(conn, api, "m", ["abc"])
    assert len(api.goi) == 1 and token2 == 0 and v2 == [v1[1]]


def test_tim_nhieu_gop_cac_cach_dien_dat(kho):
    mot = tim_kiem.tim(kho, "hàng giả", None)["lai"]
    assert tim_kiem.tim_nhieu(kho, ["hàng giả"], [None]) == mot
    hai = tim_kiem.tim_nhieu(kho, ["xyz không khớp gì", "hàng giả"], [None, None])
    assert set(hai) == set(mot)  # câu gốc không ra gì thì câu viết lại vẫn tìm được
