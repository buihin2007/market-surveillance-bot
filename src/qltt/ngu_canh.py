"""Từ câu hỏi → ngữ cảnh cho bước chọn hành vi và xử phạt.

Luồng: câu hỏi → [1] hành vi ứng viên: tìm chunk xử phạt, gom theo Điều (mỗi Điều của nghị định
xử phạt gọi tên một hành vi vi phạm kèm mức phạt) → [1b] định nghĩa trong chính các văn bản đó +
quy phạm liên quan, để phân định các hành vi gần nhau (vd hàng giả / nhập lậu / không rõ nguồn gốc)
→ [2] GĐ 2: LLM chọn hành vi, chọn khoản theo giá trị hàng, đọc mức phạt, xử phạt bổ sung,
khắc phục hậu quả.
"""

from dataclasses import dataclass

import psycopg

from qltt import tim_kiem
from qltt.tim_kiem import Loc

SO_HANH_VI = 5
SO_DINH_NGHIA = 5
SO_QUY_PHAM = 5

KhoaDieu = tuple[int, int, str]  # (tvpl_id, dieu_so, dieu_suffix)


def gom_dieu(conn: psycopg.Connection, ids: list[int]) -> list[tuple[KhoaDieu, list[int]]]:
    """Danh sách chunk đã xếp hạng → các Điều theo thứ tự xuất hiện đầu tiên, kèm chunk khớp."""
    vt = {
        r[0]: (r[1], r[2], r[3] or "")
        for r in conn.execute(
            "SELECT id, tvpl_id, dieu_so, dieu_suffix FROM chunk"
            " WHERE id = ANY(%s) AND dieu_so IS NOT NULL",
            [ids],
        )
    }
    nhom: dict[KhoaDieu, list[int]] = {}
    for i in ids:
        if i in vt:
            nhom.setdefault(vt[i], []).append(i)
    return list(nhom.items())


@dataclass
class HanhVi:
    """Một Điều xử phạt ứng viên: hành vi vi phạm + toàn bộ khoản (mức phạt, bổ sung, khắc phục)."""

    khoa: KhoaDieu
    so_hieu: str
    dieu: str  # "Điều 13"
    ten: str  # tên Điều
    noi_dung: str  # chữ cả Điều
    chunk_khop: list[str]  # đường dẫn các chunk khớp câu hỏi, theo thứ tự hạng ("Điều 13 khoản 1")


@dataclass
class NguCanh:
    cau_hoi: str
    hanh_vi: list[HanhVi]
    # giải thích từ ngữ trong các văn bản của hành vi ứng viên
    dinh_nghia: list[tim_kiem.DongKetQua]
    quy_pham: list[tim_kiem.DongKetQua]  # quy phạm liên quan, toàn kho


def hanh_vi(conn: psycopg.Connection, ids: list[int], n: int = SO_HANH_VI) -> list[HanhVi]:
    ra = []
    for khoa, khop in gom_dieu(conn, ids)[:n]:
        r = conn.execute(
            "SELECT v.so_hieu, c.duong_dan, c.dieu_ten, c.noi_dung FROM chunk c"
            " JOIN van_ban v USING (tvpl_id) WHERE c.tvpl_id = %s AND c.dieu_so = %s"
            " AND c.dieu_suffix = %s AND c.cap = 'dieu'",
            list(khoa),
        ).fetchone()
        duong_dan = [d.duong_dan for d in tim_kiem.chi_tiet(conn, khop)]
        ra.append(HanhVi(khoa, r[0], r[1], r[2] or "", r[3], duong_dan))
    return ra


def lap(
    conn: psycopg.Connection,
    cau_hoi: str,
    vec: list[float] | None,
    viet_lai: list[tuple[str, list[float] | None]] = (),
) -> NguCanh:
    """viet_lai: các cách diễn đạt khác của câu hỏi (kèm vector), tìm thêm rồi gộp với câu gốc."""
    cau = [cau_hoi, *(q for q, _ in viet_lai)]
    vecs = [vec, *(v for _, v in viet_lai)]
    hv = hanh_vi(conn, tim_kiem.tim_nhieu(conn, cau, vecs))
    van_ban = tuple(dict.fromkeys(h.khoa[0] for h in hv))
    loc_dn = Loc(vai_tro=None, loai_chunk=("giai_thich",), tvpl_ids=van_ban)
    dinh_nghia = tim_kiem.tim_nhieu(conn, cau, vecs, loc_dn) if van_ban else []
    quy_pham = tim_kiem.tim_nhieu(conn, cau, vecs, Loc(vai_tro="quy_pham"))
    return NguCanh(
        cau_hoi,
        hv,
        tim_kiem.chi_tiet(conn, dinh_nghia[:SO_DINH_NGHIA]),
        tim_kiem.chi_tiet(conn, [i for i in quy_pham if i not in dinh_nghia][:SO_QUY_PHAM]),
    )
