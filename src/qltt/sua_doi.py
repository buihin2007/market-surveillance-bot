"""Quan hệ sửa đổi giữa văn bản (GĐ 3.1) và bảng phủ: sửa đổi nào đã nằm trong VBHN, nào chưa.

Nguồn: tên Điều của văn bản (không phải VBHN) bắt đầu bằng "Sửa đổi", "Bổ sung", "Bãi bỏ", "Thay
thế". Đích:
  - số hiệu trong tên Điều, kể cả chuỗi "Nghị định số X ngày … và Nghị định số Y";
    "Bãi bỏ khoản 7 Điều 1 của Nghị định số 106/2017 sửa đổi … Nghị định số 67/2013" → chỉ 106/2017
    (số sau là mô tả của văn bản đích);
  - tên Điều không có số hiệu ("Sửa đổi, bổ sung Điều 27" của 114/2026) → đích trong tiêu đề văn
    bản (van_ban.chi_sua_van_ban);
  - "Luật Dược" (luật không ghi số) → tra theo tên luật trong kho.
Ghi quan_he_van_ban (loai sua_doi | bai_bo | thay_the, nguon ten_dieu); dựng lại toàn bộ sau nạp.

Bảng phủ: mỗi cặp (văn bản sửa đổi → văn bản bị sửa) thuộc một nhóm:
  da_hop_nhat     có VBHN đang hiệu lực hợp nhất văn bản bị sửa và liệt kê văn bản sửa đổi này
  chua_hop_nhat   văn bản bị sửa đang dùng để tra, chưa có VBHN chứa sửa đổi → bot đọc chữ cũ
  vbhn_thieu      văn bản bị sửa đã có VBHN nhưng VBHN đó chưa gồm sửa đổi này → bot đọc chữ cũ
  khong_trong_kho văn bản bị sửa không có trong kho
  khac            văn bản bị sửa hết hiệu lực / không dùng để tra vì lý do khác
  nghi_quyet      nghị quyết cắt giảm tạm thời (19/2026, 66.18/2026): không hợp nhất, chỉ cảnh báo
"""

import re
from dataclasses import dataclass

import psycopg

from qltt.parse import chuan_so_hieu

R_HANH_DONG = re.compile(r"^(?:sửa đổi|bổ sung|bãi bỏ|thay thế)\b", re.I)
LOAI_VB = "Nghị định|Thông tư liên tịch|Thông tư|Luật|Pháp lệnh|Quyết định|Nghị quyết"
SO = r"\d{1,4}(?:\.\d{1,3})?/\d{4}/\s?[A-ZĐa-zđ][A-ZĐa-zđ0-9\-]*"
R_DAU = re.compile(
    rf"\b(?:{LOAI_VB})[^\d]{{0,40}}?"
    rf"(?:số\s*)?(?P<so>{SO})",
    re.I,
)
R_NOI = re.compile(
    rf"^\s*(?:ngày \d{{1,2}} tháng \d{{1,2}} năm \d{{4}}\s*)?(?:,|và)\s*"
    rf"(?:{LOAI_VB})\s*(?:số\s*)?"
    rf"(?P<so>{SO})",
    re.I,
)
R_LUAT_TEN = re.compile(r"\bcủa (?:các )?Luật ([A-ZĐ][^\d,;]*?)\s*$")


def loai_hanh_dong(dieu_ten: str) -> str:
    t = dieu_ten.lower()
    co = {k for k, w in (("sua", "sửa đổi"), ("bo_sung", "bổ sung"), ("bai_bo", "bãi bỏ"),
                         ("thay_the", "thay thế")) if w in t}  # fmt: skip
    if co == {"bai_bo"}:
        return "bai_bo"
    if co == {"thay_the"}:
        return "thay_the"
    return "sua_doi"


def dich(dieu_ten: str) -> list[str]:
    """Số hiệu (chưa chuẩn hóa) các văn bản bị sửa nêu trong tên Điều; [] nếu không nêu."""
    m = R_DAU.search(dieu_ten)
    if not m:
        return []
    ra = [m.group("so")]
    con = dieu_ten[m.end() :]
    while n := R_NOI.match(con):
        ra.append(n.group("so"))
        con = con[n.end() :]
    return [re.sub(r"\s+", "", s) for s in ra]


@dataclass
class QuanHe:
    tu: int
    den_so_hieu: str
    loai: str
    dieu: str  # Điều của văn bản sửa đổi nêu quan hệ (để báo cáo)


def tim_quan_he(conn: psycopg.Connection) -> list[QuanHe]:
    # tên luật lưu "DƯỢC" hoặc "LUẬT DƯỢC" tùy file
    luat = {
        re.sub(r"^LUẬT\s+", "", (ten or "").strip().upper()): sh
        for sh, ten in conn.execute("SELECT so_hieu_chuan, ten FROM van_ban WHERE loai = 'luat'")
    }
    rows = conn.execute(
        "SELECT v.tvpl_id, v.chi_sua_van_ban, c.dieu_so, c.dieu_suffix, c.dieu_ten"
        " FROM chunk c JOIN van_ban v USING (tvpl_id)"
        " WHERE c.cap = 'dieu' AND v.loai <> 'vbhn' AND c.dieu_ten IS NOT NULL"
        " ORDER BY v.tvpl_id, c.dieu_so, c.dieu_suffix"
    ).fetchall()
    ra: list[QuanHe] = []
    for tvpl, chi_sua, so, ht, ten in rows:
        ten = " ".join(ten.split())
        if not R_HANH_DONG.match(ten):
            continue
        ds = [chuan_so_hieu(s) for s in dich(ten)]
        if not ds and (m := R_LUAT_TEN.search(ten)) and m.group(1).upper() in luat:
            ds = [luat[m.group(1).upper()]]
        if not ds and chi_sua:
            ds = [chi_sua]
        for d in ds:
            ra.append(QuanHe(tvpl, d, loai_hanh_dong(ten), f"Điều {so}{ht or ''}"))
    return ra


def dung_lai(conn: psycopg.Connection) -> int:
    """Xóa và ghi lại quan hệ nguồn ten_dieu (kể cả chỉ dẫn trong phụ lục nghị quyết); nối den theo
    số hiệu. Trả số quan hệ."""
    qh = tim_quan_he(conn)
    het, _ = chi_dan_hieu_luc(conn)
    for tu, cts in chi_dan_phu_luc(conn):
        for x in cts:
            loai = "bai_bo" if x.hanh_dong in ("bai_bo", "khong_thuc_hien") else "sua_doi"
            qh.append(QuanHe(tu, x.den_so_hieu, loai, x.vi_tri_tu))
    with conn.transaction():
        conn.execute("DELETE FROM quan_he_van_ban WHERE nguon IN ('ten_dieu', 'dieu_hieu_luc')")
        for h in het:
            conn.execute(
                "INSERT INTO quan_he_van_ban (tu, den_so_hieu, loai, nguon)"
                " VALUES (%s, %s, %s, 'dieu_hieu_luc') ON CONFLICT DO NOTHING",
                [h.tu, h.den_so_hieu, h.loai],
            )
        for q in qh:
            if conn.execute(
                "SELECT 1 FROM van_ban WHERE tvpl_id = %s AND so_hieu_chuan = %s",
                [q.tu, q.den_so_hieu],
            ).fetchone():
                continue  # tự trỏ về chính mình (tên Điều nhắc số hiệu của chính văn bản)
            conn.execute(
                "INSERT INTO quan_he_van_ban (tu, den_so_hieu, loai, nguon)"
                " VALUES (%s, %s, %s, 'ten_dieu') ON CONFLICT DO NOTHING",
                [q.tu, q.den_so_hieu, q.loai],
            )
        conn.execute(
            "UPDATE quan_he_van_ban q SET den = v.tvpl_id FROM van_ban v"
            " WHERE q.nguon IN ('ten_dieu', 'dieu_hieu_luc') AND v.so_hieu_chuan = q.den_so_hieu"
        )
    return conn.execute(
        "SELECT count(*) FROM quan_he_van_ban WHERE nguon IN ('ten_dieu', 'dieu_hieu_luc')"
    ).fetchone()[0]


@dataclass
class DongPhu:
    tu_so_hieu: str
    tu_hieu_luc: str | None  # ngày hiệu lực văn bản sửa đổi
    den_so_hieu: str
    loai: str
    nhom: str
    vbhn: str | None  # VBHN liên quan (đã gồm / chưa gồm)
    den_ten: str | None


def bang_phu(conn: psycopg.Connection) -> list[DongPhu]:
    rows = conn.execute(
        """
        SELECT t.so_hieu, t.ngay_hieu_luc, q.den_so_hieu, string_agg(DISTINCT q.loai, ','),
            d.tvpl_id, d.dung_de_tra, d.trang_thai, d.ten, t.tvpl_id, t.loai
        FROM quan_he_van_ban q
        JOIN van_ban t ON t.tvpl_id = q.tu
        LEFT JOIN van_ban d ON d.tvpl_id = q.den
        WHERE q.nguon = 'ten_dieu' AND t.trang_thai = 'hieu_luc'
        GROUP BY 1, 2, 3, 5, 6, 7, 8, 9, 10
        ORDER BY 3, 2
        """
    ).fetchall()
    ra = []
    for tu_sh, tu_hl, den_sh, loai, den, den_tra, den_tt, den_ten, tu, tu_loai in rows:
        vbhn_gom = conn.execute(
            """
            SELECT h.so_hieu FROM quan_he_van_ban g JOIN van_ban h ON h.tvpl_id = g.tu
            JOIN quan_he_van_ban s ON s.tu = g.tu AND s.loai = 'hop_nhat_sua' AND s.den = %s
            WHERE g.loai = 'hop_nhat' AND g.den = %s AND h.trang_thai = 'hieu_luc'
            LIMIT 1
            """,
            [tu, den],
        ).fetchone() if den else None  # fmt: skip
        vbhn_co = conn.execute(
            "SELECT h.so_hieu FROM quan_he_van_ban g JOIN van_ban h ON h.tvpl_id = g.tu"
            " WHERE g.loai = 'hop_nhat' AND g.den = %s AND h.dung_de_tra LIMIT 1",
            [den],
        ).fetchone() if den else None  # fmt: skip
        if den is None:
            nhom, vb = "khong_trong_kho", None
        elif tu_loai == "nghi_quyet" and den_tra is not None:
            nhom, vb = "nghi_quyet", None  # tạm thời, không bao giờ được hợp nhất
        elif vbhn_gom:
            nhom, vb = "da_hop_nhat", vbhn_gom[0]
        elif den_tra:
            nhom, vb = "chua_hop_nhat", None
        elif vbhn_co:
            nhom, vb = "vbhn_thieu", vbhn_co[0]
        else:
            nhom, vb = "khac", den_tt
        ra.append(DongPhu(tu_sh, str(tu_hl) if tu_hl else None, den_sh, loai, nhom, vb, den_ten))
    return ra


# ---------- GĐ 3.2: chỉ dẫn sửa đổi chi tiết (Điều / khoản nào bị sửa, chữ mới là gì) ----------
#
# Mỗi khoản của Điều "Sửa đổi …" là một chỉ dẫn, ví dụ:
#   "7. Điểm a, điểm d khoản 2 và khoản 6 Điều 8 được sửa đổi, bổ sung như sau: “a) …”"
#   "3. Sửa đổi, bổ sung một số điểm, khoản của Điều 6 như sau: a) Sửa đổi khoản 2 …: “…”"
#   "2. Bãi bỏ khoản 2, 3, 4 và 5 Điều 7."
# Điều không chia khoản ("Điều 4. Sửa đổi, bổ sung Điều 27 “Điều 27. …”") là một chỉ dẫn.
# Bỏ phần trong ngoặc kép (chữ mới) rồi đọc vị trí: khoản đứng trước "Điều N" thuộc Điều N; khoản
# sau Điều cuối (các mục a, b …) thuộc Điều cuối. Không nêu Điều → Điều trong tên Điều sửa đổi.
# Không ghép chữ mới vào văn bản cũ (dễ sai); chỉ cảnh báo + đưa chữ mới khi bot trích đúng chỗ đó.

R_NGOAC = re.compile(r"“[^”]*(?:”|$)|\"[^\"]*(?:\"|$)", re.S)
# "Điều 21", "các Điều 21, 25, 26 và 27" (số sau là Điều khác), "điều 28" (viết thường có số)
R_DIEU_SO = re.compile(r"\b[Đđ]iều\s+(\d+)([a-zđ]?)\b((?:\s*(?:,|và)\s*\d+[a-zđ]?\b(?!\s*/))*)")
R_KHOAN_DS = re.compile(r"\bkhoản\s+\d+[a-zđ]?(?:\s*(?:,|và)\s*(?:khoản\s+)?\d+[a-zđ]?\b)*", re.I)


def so_khoan(s: str) -> list[int]:
    """Số khoản trong "khoản 2, 3 và 5"; khoản mới có hậu tố ("khoản 5a") → 0 (không trùng khoản
    nào đang có, chỉ khớp khi trích cả Điều)."""
    return [0 if h else int(n) for n, h in re.findall(r"(\d+)([a-zđ]?)\b", s)]


# "Bổ sung Điều 5a sau Điều 5": Điều 5 là chỗ chèn, không phải đích
R_NEO = re.compile(r"(?:vào\s+)?(?:sau|trước)\s+Điều\s+\d+[a-zđ]?\b")
R_DAU_DIEU = re.compile(r"^\s*Điều\s+\d+[a-zđ]?\.\s*")
R_SO_HIEU = re.compile(
    rf"(?:Nghị định|Thông tư|Luật|Quyết định|Nghị quyết)[^\d]{{0,30}}?(?:số\s*)?({SO})", re.I
)


def ngoac_mo(s: str) -> bool:
    return s.count("“") > s.count("”")


def hanh_dong_chi_tiet(lay: str) -> str:
    """Theo động từ đầu câu chỉ dẫn (phần sau dễ nhắc "được sửa đổi, bổ sung bởi …" của văn bản
    khác: "Bãi bỏ khoản 11 Điều 3 … Nghị định 98/2020 được sửa đổi, bổ sung bởi …" là bãi bỏ)."""
    t = " ".join(lay.lower().split()).lstrip(" 0123456789.")
    dau = t[:120]
    if "cụm từ" in dau or t.startswith("đổi tên"):
        return "thay_cum_tu"
    if t.startswith("bãi bỏ"):
        return "bai_bo"
    if t.startswith("bổ sung") and "sửa đổi" not in t[:40]:
        return "bo_sung"
    if t.startswith("sửa đổi"):
        return "sua_doi"
    # "Khoản 2 Điều 2 được sửa đổi", "Khoản 15 Điều 3 bổ sung"
    if "bãi bỏ" in dau and "sửa đổi" not in dau and "bổ sung" not in dau:
        return "bai_bo"
    if "bổ sung" in dau and "sửa đổi" not in dau:
        return "bo_sung"
    return "sua_doi"


def vi_tri_bi_sua(lay: str) -> list[tuple[int, str, list[int]]]:
    """[(Điều, hậu tố, [khoản])] nêu trong câu chỉ dẫn đã bỏ ngoặc kép."""
    lay = R_NEO.sub(" ", lay)
    dieu = list(R_DIEU_SO.finditer(lay))
    khoan = [(m.start(), so_khoan(m.group())) for m in R_KHOAN_DS.finditer(lay)]
    ra: dict[tuple[int, str], set[int]] = {}
    truoc = 0
    for i, m in enumerate(dieu):
        sau = len(lay) if i == len(dieu) - 1 else m.start()
        k = ra.setdefault((int(m.group(1)), m.group(2)), set())
        for vt, ds in khoan:
            if truoc <= vt < sau:
                k.update(ds)
        for n, h in re.findall(r"(\d+)([a-zđ]?)", m.group(3)):
            ra.setdefault((int(n), h), set())
        truoc = m.end()
    return [(d, h, sorted(k)) for (d, h), k in ra.items()]


@dataclass
class ChiTiet:
    chunk_id: int
    vi_tri_tu: str
    den_so_hieu: str
    dieu_so: int | None
    dieu_suffix: str
    khoan: list[int]
    hanh_dong: str
    mo_ta: str
    noi_dung_moi: str
    chac: bool


def mo_ta_gon(lay: str) -> str:
    s = " ".join(lay.split())
    s = re.sub(r"^\d+[a-zđ]?\.\s*", "", s)
    s = re.split(r"\s+như sau\b", s)[0]
    s = re.sub(r"(?:\s*…)+", " …", s).strip(' :.…“”"')
    return s[:300]


def tach_chi_tiet(
    chunk_id: int, vi_tri_tu: str, noi_dung: str, dieu_ten: str, dich_dieu: list[str]
) -> list[ChiTiet]:
    """Một chỉ dẫn (khoản / Điều của văn bản sửa đổi) → các vị trí bị sửa."""
    noi_dung = R_DAU_DIEU.sub("", noi_dung)
    lay = R_NGOAC.sub(" … ", noi_dung)
    moi = "\n".join(m.group().strip('“”"') for m in R_NGOAC.finditer(noi_dung)).strip()
    # văn bản đích: số hiệu nêu trong chỉ dẫn (nếu là một đích của Điều), không thì đích của Điều
    neu = [chuan_so_hieu(re.sub(r"\s+", "", m.group(1))) for m in R_SO_HIEU.finditer(lay)]
    trung = [s for s in neu if s in dich_dieu]
    den = trung[0] if trung else dich_dieu[0]
    chac = bool(trung) or len(dich_dieu) == 1
    vt = vi_tri_bi_sua(lay)
    if not vt:  # "1. Bổ sung khoản 9" trong Điều "Sửa đổi, bổ sung Điều 3"
        tu_ten = vi_tri_bi_sua(dieu_ten)
        if len(tu_ten) == 1:
            khoan = sorted({x for m in R_KHOAN_DS.finditer(lay) for x in so_khoan(m.group())})
            vt = [(tu_ten[0][0], tu_ten[0][1], khoan or tu_ten[0][2])]
    hd, mt = hanh_dong_chi_tiet(lay), mo_ta_gon(lay)
    if not vt:
        return [ChiTiet(chunk_id, vi_tri_tu, den, None, "", [], hd, mt, moi, chac)]
    return [ChiTiet(chunk_id, vi_tri_tu, den, d, h, k, hd, mt, moi, chac) for d, h, k in vt]


def chi_dan(conn: psycopg.Connection) -> list[tuple[int, list[ChiTiet]]]:
    """[(tvpl văn bản sửa đổi, chỉ dẫn)] cho mọi Điều "Sửa đổi …" của văn bản không phải VBHN."""
    dich_theo_dieu: dict[tuple[int, int, str], list[str]] = {}
    for q in tim_quan_he(conn):
        dich_theo_dieu.setdefault((q.tu, *_so_dieu(q.dieu)), []).append(q.den_so_hieu)
    ra = []
    for (tvpl, so, ht), dich_dieu in dich_theo_dieu.items():
        dieu = conn.execute(
            "SELECT id, dieu_ten, noi_dung FROM chunk WHERE tvpl_id = %s AND cap = 'dieu'"
            " AND dieu_so = %s AND dieu_suffix = %s",
            [tvpl, so, ht],
        ).fetchone()
        if not dieu:
            continue
        khoan = conn.execute(
            "SELECT id, khoan_so, khoan_suffix, noi_dung FROM chunk WHERE cha_id = %s"
            " AND cap = 'khoan' ORDER BY id",
            [dieu[0]],
        ).fetchall()
        don_vi: list[tuple[int, str, str]] = []  # (chunk_id, vị trí, nội dung)
        so_truoc = 0
        for cid, k, ks, nd in khoan:
            # khoản trong ngoặc kép bị tách nhầm (số khoản không tăng, vd 17/2020 "6." trong khoản
            # 6): ghép lại. Số tăng tiếp = chỉ dẫn mới, kể cả khi khoản trước quên đóng ngoặc
            # (17/2022 khoản 3)
            if don_vi and ngoac_mo(don_vi[-1][2]) and (k or 0) <= so_truoc:
                don_vi[-1] = (don_vi[-1][0], don_vi[-1][1], don_vi[-1][2] + "\n" + nd)
            else:
                don_vi.append((cid, f"khoản {k}{ks or ''} Điều {so}{ht}", nd))
                so_truoc = k or so_truoc
        if not don_vi:
            don_vi = [(dieu[0], f"Điều {so}{ht}", dieu[2])]
        ten = " ".join((dieu[1] or "").split())
        for cid, vt, nd in don_vi:
            ra.append((tvpl, tach_chi_tiet(cid, vt, nd, ten, list(dict.fromkeys(dich_dieu)))))
    return ra


# ---------- chỉ dẫn trong phụ lục (nghị quyết cắt giảm điều kiện kinh doanh 19/2026, 66.18/2026)
#   "IX. Bãi bỏ điều kiện cấp Giấy phép phân phối sản phẩm thuốc lá quy định tại Điều 26 Nghị định
#    số 67/2013/NĐ-CP."
#   "III. Không thực hiện thủ tục cấp … Giấy phép bán lẻ rượu quy định tại các Điều 23, 25, 26 và 27
#    Nghị định số 105/2017/NĐ-CP được sửa đổi, bổ sung bởi Nghị định số 17/2020/NĐ-CP."
#   "I. Điều kiện cấp Giấy phép chế biến … quy định tại Điều 12 Nghị định 67/2013/NĐ-CP:" + các dòng
#    điều kiện còn lại (= chữ mới).
# Một dòng có thể nêu nhiều văn bản: mỗi số hiệu là đích của phần chữ đứng trước nó, nếu phần đó
# có "Điều N" ("… được sửa đổi bởi Nghị định số 17/2020" không có Điều → không phải đích).

R_SO_DAU_DONG = r"(?:[IVXLC]+|\d+(?:\.\d+)*)\.\s*"
R_DONG_PL = re.compile(
    rf"^\s*{R_SO_DAU_DONG}(?P<lenh>Không thực hiện|Bãi bỏ|Cắt giảm|Sửa đổi|Thay thế|Đơn giản hóa"
    r"|Điều kiện)\b"
)
R_DAU_MUC_PL = re.compile(r"^\s*(?:[IVXLC]+\.|[A-ZĐ]\.\s|Tiểu mục|Mục\s|Phần\s|Phụ lục)")
R_SO_BAT_KY = re.compile(SO)
HANH_DONG_PL = {"Không thực hiện": "khong_thuc_hien", "Bãi bỏ": "bai_bo"}


def tach_dong_phu_luc(chunk_id: int, vi_tri_tu: str, dong: str, tiep: list[str]) -> list[ChiTiet]:
    """Một dòng phụ lục → chỉ dẫn; tiep: các dòng sau (chữ mới của dòng "Điều kiện …:")."""
    m = R_DONG_PL.match(dong)
    if not m:
        return []
    lay = R_NGOAC.sub(" … ", dong)
    hd = HANH_DONG_PL.get(m.group("lenh"), "sua_doi")
    moi = ""
    if m.group("lenh") == "Điều kiện":  # các dòng sau (tới mục kế) là điều kiện còn lại
        ds = []
        for x in tiep:
            if R_DAU_MUC_PL.match(x):
                break
            ds.append(x.strip())
        moi = "\n".join(ds)
    mo_ta = re.sub(rf"^\s*{R_SO_DAU_DONG}", "", " ".join(dong.split())).rstrip(" .;:")[:300]
    ra, truoc = [], 0
    for so in R_SO_BAT_KY.finditer(lay):
        doan, truoc = lay[truoc : so.start()], so.end()
        den = chuan_so_hieu(re.sub(r"\s+", "", so.group()))
        for d, h, k in vi_tri_bi_sua(doan):
            ra.append(ChiTiet(chunk_id, vi_tri_tu, den, d, h, k, hd, mo_ta, moi, True))
    return ra


def chi_dan_phu_luc(conn: psycopg.Connection) -> list[tuple[int, list[ChiTiet]]]:
    rows = conn.execute(
        "SELECT c.tvpl_id, c.id, c.phu_luc_so, c.noi_dung FROM chunk c"
        " JOIN van_ban v USING (tvpl_id)"
        " WHERE c.cap = 'phu_luc' AND v.loai <> 'vbhn' ORDER BY c.tvpl_id, c.id"
    ).fetchall()
    ra = []
    for tvpl, cid, pl, nd in rows:
        dong = nd.split("\n")
        for i, x in enumerate(dong):
            if ct := tach_dong_phu_luc(cid, f"Phụ lục {pl}".strip(), x, dong[i + 1 : i + 40]):
                ra.append((tvpl, ct))
    return ra


# ---------- 3.3: thay thế / hết hiệu lực / bãi bỏ trong Điều hiệu lực thi hành ----------
#   "2. Nghị định này thay thế Nghị định số 38/2024/NĐ-CP … và Nghị định số 301/2025/NĐ-CP … sửa
#    đổi, bổ sung một số điều của Nghị định số 38/2024/NĐ-CP …" → thay 38/2024, 301/2025
#   "2. Các quy định sau đây hết hiệu lực …:" + "a) Nghị định số 117/2020 …" (cả văn bản)
#    + "b) Điều 2 và khoản 1 Điều 3 Nghị định số 124/2021 …" (một phần → chỉ dẫn bãi bỏ)
#   "2. Bãi bỏ khoản 6 Điều 9, …, Điều 36 … của Nghị định số 83/2014/NĐ-CP" (một phần)
# Số hiệu đứng sau cụm mô tả "sửa đổi, bổ sung … của / hướng dẫn / quy định chi tiết" là mô tả
# của văn bản đích, không phải đích: gặp cụm đó thì bỏ phần còn lại của dòng.

R_TEN_DIEU_HIEU_LUC = re.compile(r"^(?:Hiệu lực|Điều khoản thi hành)", re.I)
R_DONG_THAY = re.compile(r"\bthay thế\b", re.I)
R_DONG_HET = re.compile(r"\bhết hiệu lực\b", re.I)
R_DONG_BAI_BO = re.compile(r"\bbãi bỏ\b", re.I)
R_MO_TA_DICH = re.compile(r"(?:sửa đổi|bổ sung)[^;]*?\bcủa\b|hướng dẫn|quy định chi tiết", re.I)
R_MOT_PHAN = re.compile(r"\b(?:Chương|Mục|Phụ lục|Mẫu)\b|các quy định (?:về|tại)", re.I)
R_CHUYEN_TIEP = re.compile(r"tiếp tục|cho đến khi", re.I)
R_TU_THAN = re.compile(r"\b(?:Nghị định|Luật|Thông tư|Nghị quyết|Quyết định|Pháp lệnh) này\b")
R_MUC_CON = re.compile(r"^\s*(?:[a-zđ]\)|-)\s")


@dataclass
class HetHieuLuc:
    tu: int
    den_so_hieu: str
    loai: str  # thay_the | bai_bo (cả văn bản)
    vi_tri_tu: str


def doc_dieu_hieu_luc(
    tu: int, so_hieu_tu: str, chunk_id: int, vi_tri: str, text: str
) -> tuple[list[HetHieuLuc], list[ChiTiet]]:
    """Một Điều hiệu lực thi hành → (thay thế / bãi bỏ cả văn bản, chỉ dẫn bãi bỏ một phần)."""
    ca, mot_phan = [], []
    lenh = None  # động từ của khoản đang đọc, áp cho các mục a), b) bên dưới
    for dong in text.split("\n"):
        lay = R_NGOAC.sub(" … ", dong)
        cum_tu = "cụm từ" in lay.lower()
        if R_CHUYEN_TIEP.search(lay):  # "được tiếp tục hoạt động … cho đến khi … hết hiệu lực"
            lenh = None
        elif R_DONG_THAY.search(lay) and not cum_tu:
            lenh = "thay_the"
        elif R_DONG_HET.search(lay):
            lenh = "thay_the"
        elif R_DONG_BAI_BO.search(lay):
            lenh = "bai_bo"
        elif not R_MUC_CON.match(dong):
            lenh = None
        if lenh is None:
            continue
        truoc, mot_phan_dong = 0, False
        for so in R_SO_BAT_KY.finditer(lay):
            doan, truoc = lay[truoc : so.start()], so.end()
            if R_MO_TA_DICH.search(doan):
                break  # số hiệu này (và sau nó) là mô tả của văn bản đích
            doan = R_TU_THAN.split(doan)[-1]  # "điểm a khoản 2 Điều 2 Nghị định này" là chính nó
            # "các quy định về tổng đại lý tại Nghị định 95/2021 và Nghị định 83/2014": cả hai
            # đều chỉ một phần, không đọc được vị trí
            mot_phan_dong = mot_phan_dong or bool(R_MOT_PHAN.search(doan))
            den = chuan_so_hieu(re.sub(r"\s+", "", so.group()))
            if den == so_hieu_tu:
                continue
            vt = vi_tri_bi_sua(doan)
            if vt:
                hd = "thay_cum_tu" if cum_tu else "bai_bo"
                mo_ta = " ".join(R_SO_DAU_DONG_RE.sub("", dong).split()).rstrip(" .;:")[:300]
                mot_phan += [ChiTiet(chunk_id, vi_tri, den, d, h, k, hd, mo_ta, "", True)
                             for d, h, k in vt]  # fmt: skip
            elif not mot_phan_dong and not cum_tu:
                ca.append(HetHieuLuc(tu, den, lenh, vi_tri))
    return ca, mot_phan


R_SO_DAU_DONG_RE = re.compile(r"^\s*(?:\d+\.|[a-zđ]\))\s*")


def chi_dan_hieu_luc(
    conn: psycopg.Connection,
) -> tuple[list[HetHieuLuc], list[tuple[int, list[ChiTiet]]]]:
    rows = conn.execute(
        "SELECT v.tvpl_id, v.so_hieu_chuan, c.id, c.dieu_so, c.dieu_suffix, c.noi_dung"
        " FROM chunk c JOIN van_ban v USING (tvpl_id)"
        " WHERE c.cap = 'dieu' AND v.loai <> 'vbhn' AND c.dieu_ten ~* %s",
        [R_TEN_DIEU_HIEU_LUC.pattern.lstrip("^")],
    ).fetchall()
    ca, mot_phan = [], []
    for tvpl, sh, cid, so, ht, nd in rows:
        a, b = doc_dieu_hieu_luc(tvpl, sh, cid, f"Điều {so}{ht or ''}", R_DAU_DIEU.sub("", nd))
        ca += a
        if b:
            mot_phan.append((tvpl, b))
    return ca, mot_phan


def _so_dieu(dieu: str) -> tuple[int, str]:
    m = re.match(r"Điều (\d+)(.*)", dieu)
    return int(m.group(1)), m.group(2)


def dung_chi_tiet(conn: psycopg.Connection) -> int:
    """Xóa và ghi lại sua_doi_chi_tiet. Trả số dòng."""
    ds = chi_dan(conn) + chi_dan_phu_luc(conn) + chi_dan_hieu_luc(conn)[1]
    with conn.transaction():
        conn.execute("DELETE FROM sua_doi_chi_tiet")
        for tvpl, cts in ds:
            for x in cts:
                if conn.execute(
                    "SELECT 1 FROM van_ban WHERE tvpl_id = %s AND so_hieu_chuan = %s",
                    [tvpl, x.den_so_hieu],
                ).fetchone():
                    continue
                conn.execute(
                    "INSERT INTO sua_doi_chi_tiet (tu, chunk_id, vi_tri_tu, den_so_hieu, dieu_so,"
                    " dieu_suffix, khoan, hanh_dong, mo_ta, noi_dung_moi, chac)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [tvpl, x.chunk_id, x.vi_tri_tu, x.den_so_hieu, x.dieu_so, x.dieu_suffix,
                     x.khoan, x.hanh_dong, x.mo_ta, x.noi_dung_moi, x.chac],
                )  # fmt: skip
        conn.execute(
            "UPDATE sua_doi_chi_tiet s SET den = v.tvpl_id FROM van_ban v"
            " WHERE v.so_hieu_chuan = s.den_so_hieu"
        )
    return conn.execute("SELECT count(*) FROM sua_doi_chi_tiet").fetchone()[0]


@dataclass
class CanhBao:
    so_hieu: str  # văn bản sửa đổi
    vi_tri_tu: str
    hanh_dong: str
    mo_ta: str
    noi_dung_moi: str
    trang_thai: str
    ngay_hieu_luc: str | None
    chac: bool
    ngay_het_hieu_luc: str | None = None


def canh_bao(
    conn: psycopg.Connection, tvpl_id: int, dieu_so: int, dieu_suffix: str, khoan_so: int | None
) -> list[CanhBao]:
    """Sửa đổi chưa có trong văn bản bot đang đọc, chạm Điều (và khoản, nếu có) này.

    Văn bản đọc là VBHN → văn bản gốc của nó; bỏ sửa đổi VBHN đã gồm hoặc ban hành trước VBHN."""
    goc = conn.execute(
        "SELECT q.den, v.ngay_ban_hanh FROM quan_he_van_ban q JOIN van_ban v ON v.tvpl_id = q.tu"
        " WHERE q.tu = %s AND q.loai = 'hop_nhat' AND q.den IS NOT NULL LIMIT 1",
        [tvpl_id],
    ).fetchone()
    den, tu_ngay = (goc[0], goc[1]) if goc else (tvpl_id, None)
    rows = conn.execute(
        """
        SELECT v.so_hieu, s.vi_tri_tu, s.hanh_dong, s.mo_ta, s.noi_dung_moi, v.trang_thai,
            v.ngay_hieu_luc, s.chac, v.ngay_het_hieu_luc
        FROM sua_doi_chi_tiet s JOIN van_ban v ON v.tvpl_id = s.tu
        WHERE s.den = %(den)s AND s.dieu_so = %(dieu)s AND s.dieu_suffix = %(ht)s
          AND v.trang_thai IN ('hieu_luc', 'chua_hieu_luc')
          AND (s.khoan = '{}' OR %(khoan)s::int IS NULL OR %(khoan)s = ANY (s.khoan))
          AND (%(tu_ngay)s::date IS NULL OR v.ngay_ban_hanh > %(tu_ngay)s)
          AND s.tu NOT IN (SELECT den FROM quan_he_van_ban WHERE tu = %(vb)s
                           AND loai = 'hop_nhat_sua' AND den IS NOT NULL)
        ORDER BY v.ngay_ban_hanh DESC, s.id  -- mới nhất trước: dễ bị giấu nhất khi cắt bớt
        """,
        {"den": den, "dieu": dieu_so, "ht": dieu_suffix or "", "khoan": khoan_so,
         "tu_ngay": tu_ngay, "vb": tvpl_id},
    ).fetchall()  # fmt: skip
    return [CanhBao(r[0], r[1], r[2], r[3], r[4], r[5], _ngay(r[6]), r[7], _ngay(r[8]))
            for r in rows]  # fmt: skip


def _ngay(d) -> str | None:
    return f"{d:%d/%m/%Y}" if d else None


TEN_HANH_DONG = {
    "sua_doi": "Đã bị sửa đổi bởi",
    "bo_sung": "Đã được bổ sung bởi",
    "bai_bo": "Đã bị bãi bỏ bởi",
    "thay_cum_tu": "Đã bị thay cụm từ bởi",
    "khong_thuc_hien": "Tạm không thực hiện theo",
}
TOI_DA_CANH_BAO = 3


def _tu(s: str) -> set[str]:
    return set(re.findall(r"\w+", s.lower()))


def gop_canh_bao(cb: list[CanhBao], trich: str = "") -> list[tuple[CanhBao, int]]:
    """Gộp các dòng cùng nguồn + cùng loại (19/2026 bãi bỏ điều kiện giấy phép phân phối / bán
    buôn / bán lẻ ở cùng Điều 26) thành một; dòng đại diện là dòng trùng nhiều từ nhất với đoạn
    trích (khoản 3 "Giấy phép bán lẻ" → dòng "… bán lẻ …"). Trả [(đại diện, số dòng gộp)]."""
    nhom: dict[tuple, list[CanhBao]] = {}
    for x in cb:
        nhom.setdefault((x.so_hieu, x.vi_tri_tu, x.hanh_dong), []).append(x)
    tu = _tu(trich)
    return [(max(ds, key=lambda x: len(_tu(x.mo_ta) & tu)), len(ds)) for ds in nhom.values()]


def khoa_canh_bao(cb: list[CanhBao]) -> frozenset:
    return frozenset((x.so_hieu, x.vi_tri_tu, x.mo_ta) for x in cb)


def dong_canh_bao(cb: list[CanhBao], thut: str = "   ", trich: str = "") -> list[str]:
    """Dòng cảnh báo trong câu trả lời: gộp theo nguồn, tối đa TOI_DA_CANH_BAO dòng."""
    gop = gop_canh_bao(cb, trich)
    ra = []
    for x, n in gop[:TOI_DA_CANH_BAO]:
        hl = []
        if x.trang_thai != "hieu_luc":
            hl.append(f"có hiệu lực từ {x.ngay_hieu_luc}")
        if x.ngay_het_hieu_luc:
            hl.append(f"áp dụng đến {x.ngay_het_hieu_luc}")
        hl_s = f" ({', '.join(hl)})" if hl else ""
        if x.hanh_dong in ("bai_bo", "khong_thuc_hien"):
            sau = "Quy định trích có thể không còn áp dụng."
        elif x.noi_dung_moi:
            sau = "Nội dung trích có thể là chữ cũ, bấm Nguyên văn để xem chữ mới."
        else:
            sau = "Nội dung trích có thể là chữ cũ."
        them = f" (cùng {n - 1} dòng tương tự)" if n > 1 else ""
        ra.append(
            f"{thut}⚠ {TEN_HANH_DONG[x.hanh_dong]} {x.vi_tri_tu} {x.so_hieu}{hl_s}:"
            f" {x.mo_ta}{them}. {sau}"
        )
    if len(gop) > TOI_DA_CANH_BAO:
        con = gop[TOI_DA_CANH_BAO:]
        khac = sorted({x.so_hieu for x, _ in con})
        ra.append(f"{thut}⚠ Và {sum(n for _, n in con)} chỉ dẫn sửa đổi khác ({', '.join(khac)}).")
    return ra


def dem_canh_bao(conn: psycopg.Connection) -> list[tuple[str, int, int]]:
    """[(số hiệu, số Điều/khoản sẽ kèm cảnh báo, tổng Điều/khoản)] của văn bản đang dùng để tra."""
    rows = conn.execute(
        "SELECT c.tvpl_id, v.so_hieu, c.dieu_so, c.dieu_suffix, c.khoan_so FROM chunk c"
        " JOIN van_ban v USING (tvpl_id) WHERE v.dung_de_tra AND c.cap IN ('dieu', 'khoan')"
        " AND c.dieu_so IS NOT NULL AND (v.tvpl_id IN (SELECT den FROM sua_doi_chi_tiet)"
        " OR v.tvpl_id IN (SELECT tu FROM quan_he_van_ban WHERE loai = 'hop_nhat'))"
    ).fetchall()
    dem: dict[str, list[int]] = {}
    for tvpl, sh, d, h, k in rows:
        x = dem.setdefault(sh, [0, 0])
        x[1] += 1
        x[0] += bool(canh_bao(conn, tvpl, d, h, k))
    return sorted(((sh, a, b) for sh, (a, b) in dem.items() if a), key=lambda r: -r[1])


@dataclass
class LechSheet:
    so_hieu: str  # văn bản sheet ghi còn hiệu lực
    bi_thay_boi: str
    loai: str
    tu_ngay: str | None


def lech_sheet(conn: psycopg.Connection) -> list[LechSheet]:
    """Văn bản sheet ghi còn hiệu lực nhưng Điều hiệu lực của một văn bản đang hiệu lực trong kho
    nói đã bị thay thế / bãi bỏ / hết hiệu lực → nhờ chú sửa sheet."""
    rows = conn.execute(
        """
        SELECT d.so_hieu, t.so_hieu, q.loai, t.ngay_hieu_luc FROM quan_he_van_ban q
        JOIN van_ban t ON t.tvpl_id = q.tu AND t.trang_thai = 'hieu_luc'
        JOIN van_ban d ON d.tvpl_id = q.den AND d.trang_thai = 'hieu_luc'
        WHERE q.nguon = 'dieu_hieu_luc' AND q.loai IN ('thay_the', 'bai_bo')
        ORDER BY d.so_hieu
        """
    ).fetchall()
    return [LechSheet(a, b, c, _ngay(d)) for a, b, c, d in rows]
