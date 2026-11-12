"""Tách hình thức xử phạt bổ sung và biện pháp khắc phục hậu quả thành bảng bien_phap (dẫn xuất).

Khoản "Hình thức xử phạt bổ sung:" / "Biện pháp khắc phục hậu quả:" gồm một hoặc nhiều biện pháp
(điểm a, b… hoặc cả khoản). Mỗi biện pháp nêu nó áp cho hành vi nào:
  "… đối với hành vi vi phạm quy định tại điểm a, b khoản 1 và khoản 3 Điều này"  → khoản/điểm
  "… đối với hành vi vi phạm quy định tại Điều này" hoặc không nêu                → cả Điều
Câu dẫn chiếu không đọc được (Điều khác, "hành vi tái phạm"…) ghi tach_duoc = false: bot trích
nguyên văn biện pháp đó thay vì đoán nó áp cho hành vi nào.
"""

import re
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from qltt.muc_phat import TEN_NGHI_DINH_XU_PHAT, tach_diem
from qltt.parse import chuan

R_DAU = re.compile(
    r"^(?:các )?(?:hình thức xử phạt bổ sung|biện pháp khắc phục hậu quả)[^:]*:\s*", re.I
)
R_BAI_BO = re.compile(r"^\(?(?:được |đã được )?bãi bỏ\)?\.?$", re.I)
# "(đối với / do thực hiện) hành vi (vi phạm) (quy định) tại <dẫn chiếu> Điều này"
R_DOI_VOI = re.compile(r"\bđối với\b", re.I)
R_TAI = re.compile(
    r"\b(?:hành vi|vi phạm)\b[^;]*?(?:\b(?:tại|từ)\s+|\s)"
    r"(?P<ref>(?:(?:các )?(?:điểm|khoản) .*?)?)\s*(?:Điều này|$)",
    re.I,
)
# "…, trừ trường hợp áp dụng biện pháp quy định tại điểm a khoản 4 Điều này": dẫn chiếu sau
# "trừ" / "ngoài" không phải hành vi bị áp dụng
R_TRU = re.compile(r"\btrừ (?:các )?trường hợp\b|\bngoài (?:các )?(?:biện pháp|hình thức)\b", re.I)
R_TRONG_TRUONG_HOP = re.compile(r"\btrong trường hợp\b[^;]*\b(?:điểm|khoản) \d", re.I)
R_CO_DAN_CHIEU = re.compile(r"\b(?:điểm|khoản) [^;]*?Điều này", re.I)
THU_TU_DIEM = "abcdđeghiklmnopqrstuvxy"
R_TOKEN = re.compile(r"điểm|khoản|Điều|đến|\d+[a-zđ]?|\b[a-zđ]\b", re.I)


@dataclass
class ApDung:
    khoan: str  # "3" hoặc "3a"
    diem: list[str] = field(default_factory=list)  # rỗng: cả khoản


def doc_dan_chieu(ref: str) -> list[ApDung] | None:
    """'điểm a, b khoản 1 và khoản 3' → [ApDung(1, [a, b]), ApDung(3)]. None nếu không chắc.

    Rỗng ([]) nghĩa là "tại Điều này": cả Điều.
    """
    ref = ref.strip(" ,;.")
    if not ref:
        return []
    ra: list[ApDung] = []
    che_do, diem_cho, den = "", [], False
    for m in R_TOKEN.finditer(ref):
        t = m.group(0).lower()
        if t in ("điểm", "khoản"):
            che_do = t
        elif t == "điều":
            return None  # dẫn chiếu sang Điều khác: không đoán
        elif t == "đến":
            den = True
        elif che_do == "điểm" and not t[0].isdigit():
            if den and diem_cho:  # "từ điểm đ đến điểm k"
                a, b = THU_TU_DIEM.find(diem_cho[-1]), THU_TU_DIEM.find(t)
                if a < 0 or b <= a:
                    return None
                diem_cho += list(THU_TU_DIEM[a + 1 : b + 1])
                den = False
            else:
                diem_cho.append(t)
        elif che_do == "khoản" and t[0].isdigit():
            if den and ra and not diem_cho:
                if not (t.isdigit() and ra[-1].khoan.isdigit()):
                    return None
                ra += [ApDung(str(x)) for x in range(int(ra[-1].khoan) + 1, int(t) + 1)]
            else:
                ra.append(ApDung(t, diem_cho))
            diem_cho, den = [], False
        else:
            return None
    if diem_cho or den or not ra:
        return None  # điểm không kèm khoản, hoặc khoảng dở dang
    return ra


@dataclass
class BienPhap:
    diem: str | None
    noi_dung: str
    ap_dung: list[ApDung] | None  # None: không đọc được; []: cả Điều


def tach_khoan(text: str) -> list[BienPhap]:
    text = chuan(" ".join(text.split()))
    text = re.sub(r"^\d+[a-zđ]?\.\s*", "", text)
    than = R_DAU.sub("", text)
    dau, diem = tach_diem(than)
    dau = dau.strip(" :;.")
    if not diem:
        return [b] if (b := _bien_phap(None, than)) else []
    # câu dẫn trước điểm a ("Đối với hành vi tại các khoản 1, 2 Điều này được thực hiện…:"):
    # điểm không tự nêu hành vi thì áp theo câu dẫn
    ap_dau = _ap_dung(dau) if dau else []
    ra = []
    for chu, nd in diem:
        if not (b := _bien_phap(chu, nd)):
            continue
        if dau:
            b.noi_dung = f"{dau}: {b.noi_dung}"
            # điểm không tự dẫn chiếu hành vi ("… đối với hàng hóa nhập khẩu") theo câu dẫn
            if not R_TAI.search(nd) and ap_dau:
                b.ap_dung = ap_dau
        ra.append(b)
    return ra


def _ap_dung(nd: str) -> list[ApDung] | None:
    """Hành vi biện pháp áp cho. []: cả Điều; None: không đọc được (bot trích nguyên văn)."""
    ds, truoc = [], 0
    for m in R_TAI.finditer(nd):
        if R_TRU.search(nd[truoc : m.start()]):
            break
        ds.append(doc_dan_chieu(m.group("ref")))
        truoc = m.end()
    if ds:
        if any(d is None for d in ds):
            return None
        if any(d == [] for d in ds):  # "tại Điều này"
            # "… quy định tại Điều này trong trường hợp hàng cấm … quy định tại khoản 6, 7 và 8":
            # có điều kiện theo khoản → không khẳng định áp cho mọi hành vi
            if R_TRONG_TRUONG_HOP.search(nd):
                return None
            return []
        return [a for d in ds for a in d]
    if R_DOI_VOI.search(nd) or R_CO_DAN_CHIEU.search(nd):
        # "đối với tổ chức…", "trường hợp tái phạm", "Giấy phép quy định tại điểm a khoản 2 Điều
        # này": có điều kiện / dẫn chiếu nhưng không gắn với hành vi, không đoán
        return None
    return []  # không nêu hành vi: áp cho cả Điều


def _bien_phap(chu: str | None, nd: str) -> BienPhap | None:
    nd = nd.strip(" ;.")
    if not nd or R_BAI_BO.match(nd):
        return None
    return BienPhap(chu, nd, _ap_dung(nd))


def dung_lai(conn: psycopg.Connection) -> dict[str, int]:
    """Xóa và dựng lại bien_phap (chạy sau muc_phat.dung_lai). Trả số biện pháp theo loại."""
    rows = conn.execute(
        "SELECT c.id, c.tvpl_id, c.dieu_so, c.dieu_suffix, c.khoan_so, c.loai_chunk, c.noi_dung"
        " FROM chunk c JOIN van_ban v USING (tvpl_id)"
        " WHERE c.cap = 'khoan' AND c.loai_chunk IN ('xu_phat_bo_sung', 'khac_phuc')"
        " AND upper(v.ten) LIKE %s"
        # chỉ Điều có hành vi trong muc_phat (bỏ Điều quy định chung về hình thức xử phạt)
        " AND EXISTS (SELECT 1 FROM muc_phat m WHERE m.tvpl_id = c.tvpl_id"
        " AND m.dieu_so = c.dieu_so AND m.dieu_suffix = coalesce(c.dieu_suffix, ''))",
        [TEN_NGHI_DINH_XU_PHAT],
    ).fetchall()
    dem = {"bo_sung": 0, "khac_phuc": 0, "khong_doc_duoc": 0}
    with conn.transaction():
        conn.execute("DELETE FROM bien_phap")
        for cid, tvpl, dieu, ht, khoan, lc, nd in rows:
            loai = "bo_sung" if lc == "xu_phat_bo_sung" else "khac_phuc"
            for b in tach_khoan(nd):
                dem[loai] += 1
                dem["khong_doc_duoc"] += b.ap_dung is None
                conn.execute(
                    "INSERT INTO bien_phap (chunk_id, tvpl_id, dieu_so, dieu_suffix, khoan_so,"
                    " diem, loai, noi_dung, ap_dung, ca_dieu, tach_duoc)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        cid, tvpl, dieu, ht or "", khoan, b.diem, loai, b.noi_dung,
                        Jsonb([{"khoan": a.khoan, "diem": a.diem} for a in b.ap_dung or []]),
                        b.ap_dung == [], b.ap_dung is not None,
                    ],
                )  # fmt: skip
    return dem


@dataclass
class KetQuaBienPhap:
    loai: str  # bo_sung | khac_phuc
    noi_dung: str
    khoan_so: int  # khoản chứa biện pháp (để trích dẫn)
    diem: str | None
    chunk_id: int
    chac: bool  # True: dẫn chiếu khớp đúng hành vi; False: cần người đọc (xem ghi_chu)
    ghi_chu: str = ""


def tra_bien_phap(
    conn: psycopg.Connection,
    tvpl_id: int,
    dieu_so: int,
    dieu_suffix: str,
    khoan_so: int,
    diem: str | None = None,
    khoan_suffix: str = "",
) -> list[KetQuaBienPhap]:
    """Biện pháp áp cho hành vi (Điều, khoản, điểm). Biện pháp không đọc được dẫn chiếu trả kèm
    chac = False để bot trích nguyên văn; không bỏ sót."""
    rows = conn.execute(
        "SELECT loai, noi_dung, khoan_so, diem, chunk_id, ap_dung, ca_dieu, tach_duoc"
        " FROM bien_phap WHERE tvpl_id = %s AND dieu_so = %s AND dieu_suffix = %s"
        " ORDER BY loai DESC, khoan_so, diem NULLS FIRST",
        [tvpl_id, dieu_so, dieu_suffix],
    ).fetchall()
    khoan = f"{khoan_so}{khoan_suffix}"
    ra = []
    for loai, nd, k, d, cid, ap, ca_dieu, tach_duoc in rows:
        if not tach_duoc:
            ghi = "chỉ áp trong trường hợp nêu ở câu trên, xem nguyên văn"
            ra.append(KetQuaBienPhap(loai, nd, k, d, cid, False, ghi))
            continue
        if ca_dieu:
            ra.append(KetQuaBienPhap(loai, nd, k, d, cid, True))
            continue
        for a in ap:
            if a["khoan"] != khoan:
                continue
            if not a["diem"] or (diem and diem in a["diem"]):
                ra.append(KetQuaBienPhap(loai, nd, k, d, cid, True))
            elif diem is None:  # chưa biết điểm mà biện pháp chỉ áp vài điểm
                ghi = f"chỉ áp cho điểm {', '.join(a['diem'])} khoản {khoan}"
                ra.append(KetQuaBienPhap(loai, nd, k, d, cid, False, ghi))
            break
    return ra
