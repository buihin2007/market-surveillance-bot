"""Bộ đánh giá: đọc eval/cases.jsonl, quy căn cứ về chunk trong DB, chấm kết quả tìm kiếm.

Căn cứ ghi theo văn bản gốc (vd 98/2020/NĐ-CP Điều 6 khoản 3). Nếu văn bản gốc không dùng để
tra vì đã có VBHN thì quy sang VBHN đang dùng; số Điều/khoản của VBHN giữ như văn bản gốc.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from qltt.parse import chuan_so_hieu

NHOM = {"chinh", "khong_co"}  # khong_co: kho không có quy định → bot phải nói không tìm thấy
KIEM = {"so_tay", "claude_de_xuat", "nguoi_da_kiem"}
# loại câu hỏi (GĐ 2.2): hanh_vi → tra xử phạt; quy_dinh → trích quy định; còn lại → tin hướng dẫn
LOAI_THU_TU = ("hanh_vi", "quy_dinh", "ngoai_pham_vi", "khac")
LOAI = set(LOAI_THU_TU)
R_DIEU = re.compile(r"^(\d+)([a-zđ]?)$")


@dataclass
class CanCu:
    van_ban: str
    dieu: str  # "6", "53a"
    khoan: list[int] = field(default_factory=list)  # trống = cả Điều
    diem: list[str] = field(default_factory=list)


@dataclass
class Case:
    id: str
    nhom: str
    cau_hoi: str
    cau_hoi_nguyen_van: str
    can_cu: list[CanCu]
    cap_cham: str  # "dieu" | "khoan"
    kiem: str
    giu_lai: bool = False
    ghi_chu: str = ""
    linh_vuc: str = ""
    khung_phat: list[dict] = field(default_factory=list)
    bo_sung: list[str] = field(default_factory=list)
    khac_phuc: list[str] = field(default_factory=list)
    loai: str = "hanh_vi"


def _tu_dict(d: dict) -> Case:
    d = dict(d)
    d["can_cu"] = [CanCu(**c) for c in d.get("can_cu", [])]
    c = Case(**d)
    loi = []
    if c.nhom not in NHOM:
        loi.append(f"nhom lạ: {c.nhom!r}")
    if c.kiem not in KIEM:
        loi.append(f"kiem lạ: {c.kiem!r}")
    if c.loai not in LOAI:
        loi.append(f"loai lạ: {c.loai!r}")
    if c.loai in {"ngoai_pham_vi", "khac"} and c.nhom != "khong_co":
        loi.append("loai ngoai_pham_vi / khac phải thuộc nhom khong_co")
    if c.cap_cham not in {"dieu", "khoan"}:
        loi.append(f"cap_cham lạ: {c.cap_cham!r}")
    if not c.cau_hoi.strip():
        loi.append("thiếu cau_hoi")
    if (c.nhom == "chinh") != bool(c.can_cu):
        loi.append("nhom chinh phải có can_cu, nhom khong_co thì không")
    for cc in c.can_cu:
        if not R_DIEU.match(cc.dieu):
            loi.append(f"Điều lạ: {cc.dieu!r}")
        if c.cap_cham == "khoan" and not cc.khoan:
            loi.append("cap_cham khoan nhưng căn cứ không ghi khoản")
    if loi:
        raise ValueError(f"{c.id}: " + "; ".join(loi))
    return c


def doc_cases(path: Path) -> list[Case]:
    cases, loi = [], []
    for i, dong in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not dong.strip():
            continue
        try:
            cases.append(_tu_dict(json.loads(dong)))
        except (ValueError, TypeError) as e:
            loi.append(f"dòng {i}: {e}")
    ids = [c.id for c in cases]
    loi += [f"id trùng: {x}" for x in sorted({x for x in ids if ids.count(x) > 1})]
    if loi:
        raise ValueError("\n".join(loi))
    return cases


# ---------- quy căn cứ về chunk ----------

# Khóa một vị trí: (tvpl_id, dieu_so, dieu_suffix, khoan_so hoặc None = cả Điều)
ViTri = tuple[int, int, str, int | None]


@dataclass
class DapAn:
    case: Case
    vi_tri: set[ViTri] = field(default_factory=set)
    dich: list[str] = field(default_factory=list)  # "98/2020/NĐ-CP → 03/VBHN-BCT (2025-04-23)"
    loi: list[str] = field(default_factory=list)


def _van_ban_tra(conn: psycopg.Connection, so_hieu: str) -> tuple[int | None, str, str]:
    """Văn bản dùng để tra cho số hiệu gốc: chính nó, hoặc VBHN đang dùng đã hợp nhất nó."""
    goc = conn.execute(
        "SELECT tvpl_id, so_hieu, dung_de_tra FROM van_ban WHERE so_hieu_chuan = %s",
        [chuan_so_hieu(so_hieu)],
    ).fetchall()
    if not goc:
        return None, "", f"{so_hieu}: chưa có trong kho"
    if len(goc) > 1:
        return None, "", f"{so_hieu}: có {len(goc)} văn bản cùng số hiệu, ghi rõ văn bản gốc"
    ma, ten, tra = goc[0]
    if tra:
        return ma, ten, ""
    vbhn = conn.execute(
        "SELECT v.tvpl_id, v.so_hieu, v.ngay_ban_hanh FROM quan_he_van_ban q"
        " JOIN van_ban v ON v.tvpl_id = q.tu"
        " WHERE q.den = %s AND q.loai = 'hop_nhat' AND v.dung_de_tra",
        [ma],
    ).fetchall()
    if len(vbhn) != 1:
        return None, "", f"{so_hieu}: không dùng để tra và không có đúng một VBHN thay thế"
    m, s, ngay = vbhn[0]
    return m, f"{s} ({ngay})", ""


def giai(conn: psycopg.Connection, case: Case) -> DapAn:
    da = DapAn(case)
    for cc in case.can_cu:
        ma, ten, loi = _van_ban_tra(conn, cc.van_ban)
        if loi:
            da.loi.append(loi)
            continue
        da.dich.append(cc.van_ban if ten == cc.van_ban else f"{cc.van_ban} → {ten}")
        so, hau_to = R_DIEU.match(cc.dieu).groups()
        so = int(so)
        for k in cc.khoan or [None]:
            co = conn.execute(
                "SELECT embed FROM chunk WHERE tvpl_id = %s AND dieu_so = %s AND dieu_suffix = %s"
                " AND cap = %s AND khoan_so IS NOT DISTINCT FROM %s",
                [ma, so, hau_to, "dieu" if k is None else "khoan", k],
            ).fetchone()
            ten_vt = f"{cc.van_ban} Điều {cc.dieu}" + (f" khoản {k}" if k else "")
            if co is None:
                da.loi.append(f"{ten_vt}: không có trong {ten}")
            elif not co[0]:
                da.loi.append(f"{ten_vt}: chunk không được tìm kiếm (thẩm quyền/hiệu lực)")
            else:
                da.vi_tri.add((ma, so, hau_to, k))
    return da


# ---------- chấm ----------


def trung(chunk: ViTri, da: DapAn) -> bool:
    """chunk = (tvpl_id, dieu_so, dieu_suffix, khoan_so; None nếu chunk cấp Điều).

    Cấp Điều: mọi chunk thuộc Điều đáp án đều tính. Cấp khoản: khoản đáp án, hoặc chunk cả Điều
    chứa nó (bước sau luôn mở rộng ra cả Điều). Khoản khác cùng Điều không tính.
    """
    ma, so, ht, k = chunk
    dieu_dap_an = {(m, s, h) for m, s, h, _ in da.vi_tri}
    if da.case.cap_cham == "dieu" or k is None:
        return (ma, so, ht) in dieu_dap_an
    return (ma, so, ht, k) in da.vi_tri


def hang(ket_qua: list[ViTri], da: DapAn) -> int | None:
    """Thứ hạng (từ 1) của chunk trúng đầu tiên; None nếu không trúng."""
    return next((i for i, c in enumerate(ket_qua, 1) if trung(c, da)), None)


def hang_dieu(cac_dieu: list[tuple[int, int, str]], da: DapAn) -> int | None:
    """Hạng (từ 1) của Điều đáp án trong danh sách hành vi ứng viên (Điều đã gom, không trùng)."""
    dieu_dap_an = {(m, s, h) for m, s, h, _ in da.vi_tri}
    return next((i for i, d in enumerate(cac_dieu, 1) if d in dieu_dap_an), None)


def gom_dieu(ket_qua: list[ViTri]) -> list[tuple[int, int, str]]:
    """Chunk đã xếp hạng → các Điều không trùng, theo thứ tự xuất hiện; bỏ chunk phụ lục."""
    return list(dict.fromkeys((m, s, h) for m, s, h, _ in ket_qua if s is not None))


def tong_hop(cac_hang: list[int | None], ks: tuple[int, ...] = (5, 8, 20)) -> dict[str, float]:
    n = len(cac_hang)
    if n == 0:
        return {}
    kq = {f"recall@{k}": sum(1 for h in cac_hang if h and h <= k) / n for k in ks}
    kq["mrr"] = sum(1 / h for h in cac_hang if h) / n
    return kq
