"""Dòng "Quy định tại …" theo văn phong biên bản (chú chốt 12/11):

  điểm b khoản 1 Điều 31 Nghị định số 119/2017/NĐ-CP ngày 01/11/2017 của Chính phủ được sửa đổi,
  bổ sung tại khoản 48 Điều 2 Nghị định số 126/2021/NĐ-CP ngày 30/12/2021 của Chính phủ

- Văn bản đang tra là VBHN → trích văn bản gốc; chuỗi "được sửa đổi … tại …" lấy từ chú thích "[n]"
  của VBHN gắn ở chính vị trí đó: chú thích của điểm (chu_thich_vbhn.diem), của khoản (diem trống)
  và của tiêu đề Điều. Chú thích "bãi bỏ" bỏ qua.
- Sửa đổi ban hành sau VBHN / văn bản không có VBHN: lấy từ sua_doi_chi_tiet (sua_doi.canh_bao),
  trừ nghị quyết tạm dừng (chỉ cảnh báo, không đưa vào căn cứ).
"""

import re
from dataclasses import dataclass

import psycopg

from qltt import sua_doi

LOAI_TEN = {
    "nghi_dinh": "Nghị định",
    "luat": "Luật",
    "thong_tu": "Thông tư",
    "ttlt": "Thông tư liên tịch",
    "quyet_dinh": "Quyết định",
    "nghi_quyet": "Nghị quyết",
    "phap_lenh": "Pháp lệnh",
    "vbhn": "Văn bản hợp nhất",
}
CO_QUAN = {"nghi_dinh": "Chính phủ", "nghi_quyet": "Chính phủ", "luat": "Quốc hội"}

R_CHU_THICH = re.compile(
    r"(?P<dt>được\s+(?:sửa đổi,\s*bổ sung|sửa đổi|bổ sung|thay thế|thế|bãi bỏ|bỏ))"
    r"(?:\s+bởi\s+[^;]{0,40}?…)?"
    r"(?:\s+theo quy định(?:\s+tại)?|\s+tại|\s+bởi|\s+với)\s+(?P<vt>.*?)\s*(?:của\s+)?"
    r"(?P<loai>Nghị định|Luật|Thông tư liên tịch|Thông tư|Nghị quyết|Quyết định|Pháp lệnh)"
    r"[^\d;]{0,80}?số\s*(?P<so>\d[\w./\-]*\w)"
    r"(?:\s+ngày\s+(?P<ngay>\d{1,2}/\d{1,2}/\d{4}|\d{1,2} tháng \d{1,2} năm \d{4}))?"
    r"(?:\s+của\s+(?P<cq>Chính phủ|Quốc hội|Ủy ban [Tt]hường vụ Quốc hội|Thủ tướng Chính phủ"
    r"|Bộ trưởng[^,;.]*?(?=\s+(?:sửa đổi|quy định|về|hướng dẫn)\b|[,;.]|$)))?",
    re.I,
)


@dataclass
class SuaDoi:
    dong_tu: str  # "được sửa đổi, bổ sung" …
    vi_tri: str  # "khoản 48 Điều 2"
    van_ban: str  # "Nghị định số 126/2021/NĐ-CP ngày 30/12/2021 của Chính phủ"


@dataclass
class ChuThich:
    dong_tu: str
    vi_tri: str
    so_hieu: str
    ten_trong_chu_thich: str  # dùng khi văn bản sửa đổi không có trong kho


def doc_chu_thich(noi_dung: str) -> ChuThich | None:
    # 'Đoạn “3. …” được sửa đổi, bổ sung bởi đoạn “…” theo quy định tại …': bỏ phần trích
    s = re.sub(r"[“\"][^”\"]*[”\"]", "…", " ".join(noi_dung.split()))
    m = R_CHU_THICH.search(s)
    if not m or "bãi bỏ" in m.group("dt").lower():
        return None
    from qltt.parse import chuan_so_hieu

    so = chuan_so_hieu(m.group("so"))
    ten = f"{m.group('loai')} số {so}"
    if m.group("ngay"):
        ng = m.group("ngay")
        if "tháng" in ng:
            d, mo, y = re.findall(r"\d+", ng)
            ng = f"{int(d):02d}/{int(mo):02d}/{y}"
        ten += f" ngày {ng}"
    if m.group("cq"):
        ten += f" của {m.group('cq')}"
    vt = re.sub(r"\s+(?:của|tại)$", "", m.group("vt").strip(" ,"))
    dt = re.sub(r"\s+", " ", m.group("dt").lower()).replace(",bổ", ", bổ")
    if dt in ("được thay thế", "được thế", "được bỏ"):  # thay/bỏ cụm từ: ghi là sửa đổi
        dt = "được sửa đổi"
    return ChuThich(dt, vt, so, ten)


def ngay(d) -> str:
    return f"{d:%d/%m/%Y}" if d else ""


def ten_day_du(conn: psycopg.Connection, so_hieu: str) -> str:
    """'Nghị định số 119/2017/NĐ-CP ngày 01/11/2017 của Chính phủ' (thiếu trong kho → số hiệu)."""
    r = conn.execute(
        "SELECT loai, ten, ngay_ban_hanh FROM van_ban WHERE so_hieu = %s"
        " ORDER BY dung_de_tra DESC LIMIT 1",
        [so_hieu],
    ).fetchone()
    if not r:
        return so_hieu
    loai, ten, nbh = r
    if loai == "luat" and ten:
        t = re.sub(r"^LUẬT\s+", "", ten.strip(), flags=re.I)
        t = re.split(r"\s+QUỐC HỘI\b", t)[0].strip(" ,")
        return f"Luật {t[:1]}{t[1:].lower()} số {so_hieu} ngày {ngay(nbh)}"
    cq = CO_QUAN.get(loai)
    return f"{LOAI_TEN.get(loai, '')} số {so_hieu} ngày {ngay(nbh)}".strip() + (
        f" của {cq}" if cq else ""
    )


def vi_tri(
    dieu: int, ht: str, khoan: int | None, diem: list[str] | str | None, kht: str = ""
) -> str:
    ds = [diem] if isinstance(diem, str) else list(diem or [])
    d = ", ".join(f"điểm {x}" for x in ds)
    k = f"khoản {khoan}{kht} " if khoan is not None else ""
    return f"{d + ' ' if d else ''}{k}Điều {dieu}{ht or ''}"


def gop_vi_tri(ds: list[str]) -> str:
    """['khoản 48 Điều 2', 'khoản 49 Điều 2'] → 'khoản 48, khoản 49 Điều 2'."""
    ds = list(dict.fromkeys(ds))
    duoi = {re.search(r"Điều \S+$", x).group() if re.search(r"Điều \S+$", x) else None for x in ds}
    if len(ds) > 1 and len(duoi) == 1 and None not in duoi:
        (d,) = duoi
        return ", ".join(x[: -len(d)].strip() for x in ds) + f" {d}"
    return ", ".join(ds)


def chuoi_sua_doi(ds: list[SuaDoi]) -> str:
    """Gộp theo văn bản sửa đổi: 'được sửa đổi, bổ sung tại khoản 48, khoản 49 Điều 2 Nghị định …
    và được sửa đổi tại … Nghị định …'."""
    theo_vb: dict[str, list[SuaDoi]] = {}
    for x in ds:
        theo_vb.setdefault(x.van_ban, []).append(x)
    phan = []
    for vb, xs in theo_vb.items():
        dt = {x.dong_tu for x in xs}
        dong_tu = xs[0].dong_tu if len(dt) == 1 else "được sửa đổi, bổ sung"
        phan.append(f"{dong_tu} tại {gop_vi_tri([x.vi_tri for x in xs])} {vb}")
    return " và ".join(phan)


def quy_dinh_tai(
    conn: psycopg.Connection, tvpl_id: int, dieu: int, ht: str, khoan: int | None,
    diem: list[str] | str | None = None, kht: str = "",
) -> str:  # fmt: skip
    """Chuỗi căn cứ đầy đủ cho một vị trí trong văn bản đang tra."""
    diem_ds = [diem] if isinstance(diem, str) else list(diem or [])
    so_hieu, loai, nbh = conn.execute(
        "SELECT so_hieu, loai, ngay_ban_hanh FROM van_ban WHERE tvpl_id = %s", [tvpl_id]
    ).fetchone()
    goc = None
    if loai == "vbhn":
        r = conn.execute(
            "SELECT den_so_hieu FROM quan_he_van_ban WHERE tu = %s AND loai = 'hop_nhat' LIMIT 1",
            [tvpl_id],
        ).fetchone()
        goc = r[0] if r else None
    sua: list[SuaDoi] = []
    if goc:
        rows = conn.execute(
            """
            SELECT f.noi_dung FROM chu_thich_vbhn f JOIN chunk c ON c.id = f.chunk_id
            WHERE f.tvpl_id = %(t)s AND c.dieu_so = %(d)s AND c.dieu_suffix = %(h)s
              AND (c.cap = 'dieu'
                   OR (c.khoan_so = %(k)s AND (f.diem IS NULL OR f.diem = ANY(%(diem)s))))
            ORDER BY f.so
            """,
            {"t": tvpl_id, "d": dieu, "h": ht or "", "k": khoan, "diem": diem_ds},
        ).fetchall()
        for (nd,) in rows:
            if x := doc_chu_thich(nd):
                ten = ten_day_du(conn, x.so_hieu)
                sua.append(
                    SuaDoi(x.dong_tu, x.vi_tri, ten if ten != x.so_hieu else x.ten_trong_chu_thich)
                )
    # sửa đổi chưa có trong văn bản đang đọc (sau VBHN, hoặc văn bản chưa hợp nhất)
    for cb in sua_doi.canh_bao(conn, tvpl_id, dieu, ht, khoan):
        if cb.hanh_dong in ("khong_thuc_hien", "bai_bo") or cb.so_hieu.endswith("NQ-CP"):
            continue
        dt = "được bổ sung" if cb.hanh_dong == "bo_sung" else "được sửa đổi, bổ sung"
        sua.append(SuaDoi(dt, cb.vi_tri_tu, ten_day_du(conn, cb.so_hieu)))
    if not goc:
        vb = ten_day_du(conn, so_hieu)
    else:
        vb = ten_day_du(conn, goc)
    dau = f"{vi_tri(dieu, ht, khoan, diem_ds, kht)} {vb}"
    return f"{dau} {chuoi_sua_doi(sua)}" if sua else dau
