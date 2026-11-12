"""Tách khung phạt từ chữ các khoản xử phạt thành bảng muc_phat (dẫn xuất, dựng lại toàn bộ).

Mỗi dòng: một hành vi (khoản, hoặc điểm của khoản) + khung phạt + điều kiện giá trị / số lượng.
Ba dạng khoản gặp trong kho:
  A. "1. Phạt tiền từ X đồng đến Y đồng đối với một trong các hành vi sau đây: a) …; b) …"
     → mỗi điểm là một hành vi, chung khung của khoản (điều kiện có thể ở đầu khoản hoặc ở điểm).
  B. "1. Đối với hành vi …, mức phạt tiền như sau: a) Phạt tiền từ X … trong trường hợp trị giá …"
     → mỗi điểm là một bậc phạt của cùng hành vi ở đầu khoản.
  C. Khoản không chia điểm.
Khung "gấp N lần mức phạt tại khoản …" lưu dạng tham chiếu; code nhân khi tra. Khoản không tách
được ghi loai = 'khong_tach' để bot trích nguyên văn thay vì đưa con số.
"""

import re
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from qltt.parse import chuan

SO = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"
DON_VI = (
    r"đồng|bao|kilôgam|kg|lít|gam|tấn|mét khối|m3|đơn vị|chiếc|cái|sản phẩm|hộp|chai|lon"
    r"|bình|tép|viên|liều|con|cây|quả|tờ|bản|lần|mét|người"
)
R_DIEM = re.compile(r"(?:^|(?<=[\s;:.]))([a-zđ])\)\s")
NGHIN = r"\d{1,3}(?:\.\d{3})+"
R_TIEN = re.compile(
    rf"(?P<cc>phạt cảnh cáo hoặc )?phạt tiền"
    # chủ thể chen giữa: "Phạt tiền đơn vị cung cấp thiết bị … từ X đồng đến Y đồng"
    rf"(?: (?:đối với|đơn vị|người|tổ chức|cá nhân|chủ)[^\d.;:%]{{0,120}}? từ| từ)?"
    # số sau thiếu "đồng" (lỗi nguồn): chỉ nhận khi là số có dấu chấm nghìn
    rf" (?P<tu>{SO})(?: đồng)? (?:đến|tới) (?:(?P<den>{SO}) đồng|(?P<den2>{NGHIN})\b(?! ?%))",
    re.I,
)
# điểm bậc phạt không lặp chữ "Phạt tiền": "b) Từ 7.000.000 đồng đến 20.000.000 đồng, khi …"
R_TIEN_DAU = re.compile(
    rf"^(?:mức phạt (?:tiền )?)?từ (?P<tu>{SO})(?: đồng)? (?:đến|tới) (?P<den>{SO}) đồng", re.I
)
R_DEN = re.compile(rf"phạt tiền (?:tối đa )?đến (?P<den>{SO}) đồng", re.I)
R_CANH_CAO = re.compile(r"\bphạt cảnh cáo\b|^cảnh cáo\b", re.I)
# khoản của văn bản sửa đổi: là lệnh sửa văn bản khác, xử lý ở GĐ 3
R_SUA_DOI = re.compile(r"^(?:sửa đổi|bổ sung|bãi bỏ|thay thế|thay cụm từ|đính chính)", re.I)
R_GAP = re.compile(
    r"phạt tiền (?:gấp|bằng) (?P<n>hai|ba|bốn|năm|0\d|\d+(?:,\d+)?) lần (?:các |đối với )?mức"
    r"(?: tiền)? phạt[^.;:]*?(?:tại|từ)"
    r" (?P<tc>(?:(?:các )?điểm [^.;:]*?)?khoản (?:\d+|này)[^.;:]*?)"
    r"(?:Điều này|$|[.;:])",
    re.I,
)
# "Các mức phạt tiền quy định tại khoản 1 và 2 Điều này cũng được áp dụng đối với: a) …"
R_AP_DUNG = re.compile(
    r"mức phạt(?: tiền)? quy định tại (?P<tc>(?:các )?khoản [\d, và]+(?:khoản \d+)?)[^.;:]*?"
    r"(?:cũng )?được áp dụng",
    re.I,
)
# "Phạt tiền từ 10% đến 15% trị giá lô hàng nhưng không vượt quá 50.000.000 đồng"
R_PHAN_TRAM = re.compile(
    r"phạt tiền từ (?P<a>\d+(?:,\d+)?) ?% (?:đến|tới) (?P<b>\d+(?:,\d+)?) ?%[^.;:]*?"
    r"(?:giá trị|trị giá)",
    re.I,
)
R_LAN_GIA_TRI = re.compile(
    r"phạt tiền từ (?P<a>\d+(?:,\d+)?) (?:lần )?đến (?P<b>\d+(?:,\d+)?) lần[^.;:]*?"
    r"(?:giá trị|số tiền|số lợi)",
    re.I,
)
R_TRAN = re.compile(rf"(?:không vượt quá|không quá|tối đa) (?P<x>{SO}) đồng", re.I)
R_KHOAN_SO = re.compile(r"khoản (\d+)", re.I)
R_KHOAN_DEN = re.compile(r"từ khoản (\d+) đến khoản (\d+)", re.I)
R_HV_TAI = re.compile(
    r"hành vi (?:vi phạm )?quy định tại (?:các )?(?:điểm [^K]*?)?khoản ([\d, và]+)", re.I
)
# điều kiện: (đối tượng) … khoảng số + đơn vị
R_DK_KHOANG = re.compile(
    rf"t[ừư] (?P<tren>trên )?(?P<tu>{SO}) ?(?P<dv1>{DON_VI})? (?:đến|tới) (?P<duoi>dưới )?"
    rf"(?P<den>{SO}) ?(?P<dv>{DON_VI})",
    re.I,
)
R_DK_TREN = re.compile(rf"(?:(?P<tu_tren>trên|từ) )?(?P<tu>{SO}) ?(?P<dv>{DON_VI}) trở lên", re.I)
R_DK_TREN2 = re.compile(rf"\btrên (?P<tu>{SO}) ?(?P<dv>{DON_VI})", re.I)
R_DK_DUOI = re.compile(
    rf"(?P<kieu>dưới|không vượt quá|không quá|đến) (?P<den>{SO}) ?(?P<dv>{DON_VI})", re.I
)
CHU_SO = {"hai": 2, "ba": 3, "bốn": 4, "năm": 5}


def so(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def tach_diem(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Khoản → (đầu khoản, [(chữ điểm, nội dung)]). Chỉ nhận điểm đúng thứ tự a, b, c, d, đ, e…"""
    thu_tu = "abcdđeghiklmnopqrstuvxy"
    vi_tri, can = [], 0
    for m in R_DIEM.finditer(text):
        if can < len(thu_tu) and m.group(1) == thu_tu[can]:
            vi_tri.append((m.start(1), m.group(1)))
            can += 1
    if not vi_tri:
        return text, []
    dau = text[: vi_tri[0][0]].strip()
    diem = []
    for i, (bd, chu) in enumerate(vi_tri):
        kt = vi_tri[i + 1][0] if i + 1 < len(vi_tri) else len(text)
        diem.append((chu, text[bd + 2 : kt].strip(" ;.")))
    return dau, diem


@dataclass
class Khung:
    loai: str  # tien | canh_cao | canh_cao_hoac_tien | gap_lan | lan_gia_tri | khong_tach | sua_doi
    tu: int | None = None
    den: int | None = None
    he_so: float | None = None
    he_so_den: float | None = None
    tran: int | None = None
    tham_chieu: list[int] = field(default_factory=list)  # các khoản được nhân hệ số
    nguon: str = ""


def khung(text: str, khoan: int | None = None) -> Khung | None:
    """khoan: số khoản đang tách, để hiểu "gấp N lần mức phạt tại các điểm … khoản này".

    Cố ý để khong_tach (bot trích nguyên văn): "Phạt tiền bằng 1,5 lần … hoặc bằng 02 lần …" của
    90/2026 (hai hệ số theo nhóm thuốc, trần chỉ áp cho vài điểm), "bằng mức tối đa của khung",
    "bằng mức phạt tiền chủ tàu cá": regex dễ ra sai số tiền.
    """
    if m := R_GAP.search(text):
        tc = m.group("tc")
        if r := R_KHOAN_DEN.search(m.group(0)):
            ds = list(range(int(r.group(1)), int(r.group(2)) + 1))
        else:
            ds = [int(x) for x in R_KHOAN_SO.findall(tc)]
            if khoan and re.search(r"khoản này", tc, re.I):
                ds.append(khoan)
        n = m.group("n").lower()
        tran = R_TRAN.search(text[m.end() :])
        return Khung(
            "gap_lan",
            he_so=CHU_SO.get(n) or so(n),
            tham_chieu=ds,
            tran=int(so(tran.group("x"))) if tran else None,
            nguon=m.group(0),
        )
    if m := R_AP_DUNG.search(text):
        ds = [int(x) for x in re.findall(r"\d+", m.group("tc"))]
        return Khung("gap_lan", he_so=1, tham_chieu=ds, nguon=m.group(0))
    if m := R_TIEN.search(text):
        tu, den = int(so(m.group("tu"))), int(so(m.group("den") or m.group("den2")))
        return Khung("canh_cao_hoac_tien" if m.group("cc") else "tien", tu, den, nguon=m.group(0))
    if m := R_TIEN_DAU.search(text):
        return Khung("tien", int(so(m.group("tu"))), int(so(m.group("den"))), nguon=m.group(0))
    if m := R_DEN.search(text):
        return Khung("tien", None, int(so(m.group("den"))), nguon=m.group(0))
    if m := R_PHAN_TRAM.search(text):
        tran = R_TRAN.search(text[m.end() :])
        return Khung(
            "lan_gia_tri",
            he_so=so(m.group("a")) / 100,
            he_so_den=so(m.group("b")) / 100,
            tran=int(so(tran.group("x"))) if tran else None,
            nguon=m.group(0),
        )
    if m := R_LAN_GIA_TRI.search(text):
        tran = R_TRAN.search(text[m.end() :])
        return Khung(
            "lan_gia_tri",
            he_so=so(m.group("a")),
            he_so_den=so(m.group("b")),
            tran=int(so(tran.group("x"))) if tran else None,
            nguon=m.group(0),
        )
    if m := R_CANH_CAO.search(text):
        return Khung("canh_cao", nguon=m.group(0))
    return None


@dataclass
class DieuKien:
    tu: float | None = None
    tu_bao_gom: bool = True
    den: float | None = None
    den_bao_gom: bool = False
    don_vi: str = ""
    doi_tuong: str = ""  # gia_tri | so_loi | so_luong
    chu: str = ""


def dieu_kien(text: str) -> DieuKien | None:
    """Điều kiện định lượng đầu tiên trong chữ (bỏ qua chính khung tiền phạt)."""
    sach = R_TIEN_DAU.sub(" ", R_TIEN.sub(" ", text))
    sach = R_TRAN.sub(" ", sach)
    ung = []
    if m := R_DK_KHOANG.search(sach):
        ung.append((m.start(), DieuKien(
            so(m.group("tu")), not m.group("tren"), so(m.group("den")), not m.group("duoi"),
            m.group("dv").lower(), chu=m.group(0),
        )))  # fmt: skip
    if m := R_DK_TREN.search(sach):
        ung.append((m.start(), DieuKien(
            so(m.group("tu")), (m.group("tu_tren") or "từ").lower() != "trên",
            don_vi=m.group("dv").lower(), chu=m.group(0),
        )))  # fmt: skip
    elif m := R_DK_TREN2.search(sach):
        ung.append((m.start(), DieuKien(
            so(m.group("tu")), False, don_vi=m.group("dv").lower(), chu=m.group(0)
        )))  # fmt: skip
    if m := R_DK_DUOI.search(sach):
        ung.append((m.start(), DieuKien(
            den=so(m.group("den")), den_bao_gom=m.group("kieu").lower() != "dưới",
            don_vi=m.group("dv").lower(), chu=m.group(0),
        )))  # fmt: skip
    if not ung:
        return None
    vt, dk = min(ung, key=lambda x: x[0])
    truoc = sach[max(0, vt - 80) : vt].lower()
    if "lợi" in truoc and "giá" not in truoc[-40:]:
        dk.doi_tuong = "so_loi"
    elif dk.don_vi == "đồng":
        dk.doi_tuong = "gia_tri"
    else:
        dk.doi_tuong = "so_luong"
    return dk


def hanh_vi_tai(text: str) -> list[int]:
    """'hành vi vi phạm quy định tại khoản 1 Điều này' → [1]: bậc phạt cho hành vi ở khoản khác."""
    m = R_HV_TAI.search(text)
    return [int(x) for x in re.findall(r"\d+", m.group(1))] if m else []


@dataclass
class Dong:
    diem: str | None
    hanh_vi: str
    khung: Khung
    dk: DieuKien | None
    hanh_vi_tai: list[int]


R_TIEU_DE_BIEN_PHAP = re.compile(r"^(?:biện pháp khắc phục|hình thức xử phạt bổ sung)", re.I)


def tach_khoan(text: str, khoan: int | None = None) -> list[Dong]:
    text = chuan(" ".join(text.split()))
    text = re.sub(r"^\d+[a-zđ]?\.\s*", "", text)
    if R_SUA_DOI.match(text):
        return [Dong(None, text, Khung("sua_doi"), None, [])]
    dau, diem = tach_diem(text)
    k_dau = khung(dau, khoan)
    dk_dau = dieu_kien(dau)
    tai = hanh_vi_tai(dau)
    if not diem:
        return [Dong(None, text, k_dau or Khung("khong_tach"), dk_dau, tai)]
    ra = []
    for chu, nd in diem:
        if R_TIEU_DE_BIEN_PHAP.match(nd):  # biện pháp lẫn vào điểm: thuộc bảng biện pháp
            continue
        k_diem = khung(nd, khoan)
        if k_dau and not k_diem:  # dạng A: điểm là hành vi
            ra.append(Dong(chu, nd, k_dau, dieu_kien(nd) or dk_dau, tai))
        elif k_diem:  # dạng B: điểm là bậc phạt của hành vi ở đầu khoản
            ra.append(Dong(chu, dau, k_diem, dieu_kien(nd) or dk_dau, tai))
        else:
            ra.append(Dong(chu, nd, Khung("khong_tach"), dieu_kien(nd) or dk_dau, tai))
    return ra


TEN_NGHI_DINH_XU_PHAT = "%XỬ PHẠT VI PHẠM HÀNH CHÍNH%"


def dung_lai(conn: psycopg.Connection) -> dict[str, int]:
    """Xóa và dựng lại muc_phat từ mọi khoản hành vi xử phạt. Trả số dòng theo loại khung."""
    # Chỉ nghị định xử phạt (tên có "xử phạt vi phạm hành chính"): nghị định thi hành Luật XLVPHC
    # (118/2021, 4749/VBHN-BTP) nhắc "phạt cảnh cáo", "phạt tiền đến …" nhưng không có hành vi.
    rows = conn.execute(
        "SELECT c.id, c.tvpl_id, c.dieu_so, c.dieu_suffix, c.khoan_so, c.khoan_suffix, c.noi_dung"
        " FROM chunk c JOIN van_ban v USING (tvpl_id)"
        " WHERE c.cap = 'khoan' AND c.vai_tro = 'xu_phat' AND c.loai_chunk = 'hanh_vi'"
        " AND upper(v.ten) LIKE %s",
        [TEN_NGHI_DINH_XU_PHAT],
    ).fetchall()
    # Điều không có khoản nào ra khung phạt là Điều thủ tục (thi hành, xác định số lợi, từ chối
    # đơn…) lọt nhãn xu_phat vì nhắc "khắc phục hậu quả": bỏ, không tính là chưa tách được.
    theo_dieu: dict[tuple, list] = {}
    for cid, tvpl, dieu, ht, khoan, kht, nd in rows:
        for d in tach_khoan(nd, khoan):
            theo_dieu.setdefault((tvpl, dieu, ht), []).append((cid, khoan, kht, d))
    dong = [
        (tvpl, dieu, ht, *x)
        for (tvpl, dieu, ht), ds in theo_dieu.items()
        if any(d.khung.loai not in ("khong_tach", "sua_doi") for *_, d in ds)
        for x in ds
    ]
    dem: dict[str, int] = {}
    with conn.transaction():
        cap_nhat_muc_cua(conn)
        conn.execute("DELETE FROM muc_phat")
        for tvpl, dieu, ht, cid, khoan, kht, d in dong:
            k, dk = d.khung, d.dk
            dem[k.loai] = dem.get(k.loai, 0) + 1
            conn.execute(
                "INSERT INTO muc_phat (chunk_id, tvpl_id, dieu_so, dieu_suffix, khoan_so,"
                " khoan_suffix, diem, hanh_vi, loai, tu, den, he_so, he_so_den, tran,"
                " tham_chieu, hanh_vi_tai, dk_tu, dk_tu_bao_gom, dk_den, dk_den_bao_gom,"
                " dk_don_vi, dk_doi_tuong, dk_chu, nguon) VALUES"
                " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    cid, tvpl, dieu, ht or "", khoan, kht or "", d.diem, d.hanh_vi, k.loai,
                    k.tu, k.den, k.he_so, k.he_so_den, k.tran, Jsonb(k.tham_chieu),
                    Jsonb(d.hanh_vi_tai), dk.tu if dk else None,
                    dk.tu_bao_gom if dk else None, dk.den if dk else None,
                    dk.den_bao_gom if dk else None, dk.don_vi if dk else None,
                    dk.doi_tuong if dk else None, dk.chu if dk else None, k.nguon,
                ],
            )  # fmt: skip
    return dem


# ---------- mức phạt ghi trong nghị định là của cá nhân hay tổ chức ----------

R_MUC_CUA = re.compile(
    r"Mức phạt tiền(?:, thẩm quyền phạt tiền)? (?:được )?(?:quy định )?(?:tại|ở|trong)"
    r" (?P<pham_vi>[^.;]{0,140}?) (?:là|được)"
    r"[^.;]{0,90}?(?P<cua>cá nhân|tổ chức)(?P<sau>[^.;]{0,400})",
    re.I,
)
R_DIEU_SO = re.compile(r"Điều (\d+[a-zđ]?)")
# Không có câu nói thẳng: suy từ câu so sánh hai mức (cần người xác nhận)
R_TC_GAP = re.compile(r"mức phạt tiền (?:đối với|của) tổ chức (?:gấp|bằng) (?:02|hai|2) lần", re.I)
R_CN_NUA = re.compile(r"mức phạt tiền (?:đối với|của) cá nhân bằng (?:1/2|một nửa)", re.I)


def _cac_dieu(text: str) -> list[str]:
    """'các Điều 6, 8, 9 và 18' / 'Điều 33, Điều 34' → ['6', '8', '9', '18'] / ['33', '34']."""
    ra = []
    for m in re.finditer(r"Điều\s+((?:\d+[a-zđ]?(?:\s*,\s*|\s+và\s+)?)+)", text):
        ra += re.findall(r"\d+[a-zđ]?", m.group(1))
    return list(dict.fromkeys(ra))


def muc_cua(texts: list[str]) -> tuple[str | None, list[dict], str | None]:
    """Chữ các Điều của một nghị định → (mặc định, ngoại lệ [{dieu, cua}], nguồn).

    Câu "Mức phạt tiền quy định tại Chương II … là mức phạt áp dụng đối với cá nhân, trừ … Điều 33"
    → mặc định ca_nhan, Điều 33 là to_chuc. Câu chỉ đích danh Điều ("tại các Điều 6, 8 … là áp
    dụng đối với cá nhân") → ngoại lệ cho các Điều đó.
    """
    mac_dinh, ngoai_le = None, []
    for t in texts:
        for m in R_MUC_CUA.finditer(" ".join(t.split())):
            cua = "ca_nhan" if m.group("cua").lower() == "cá nhân" else "to_chuc"
            nguoc = "to_chuc" if cua == "ca_nhan" else "ca_nhan"
            dich_danh = _cac_dieu(m.group("pham_vi"))
            if dich_danh:
                ngoai_le += [{"dieu": d, "cua": cua} for d in dich_danh]
                continue
            if mac_dinh is None:
                mac_dinh = cua
            if "trừ" in m.group("sau"):
                ngoai_le += [{"dieu": d, "cua": nguoc} for d in _cac_dieu(m.group("sau"))]
    if mac_dinh is not None or ngoai_le:
        return mac_dinh, ngoai_le, "van_ban"
    gop = " ".join(" ".join(t.split()) for t in texts)
    if R_CN_NUA.search(gop):
        return "to_chuc", [], "suy_ra"
    if R_TC_GAP.search(gop):
        return "ca_nhan", [], "suy_ra"
    return None, [], None


def cap_nhat_muc_cua(conn: psycopg.Connection) -> None:
    for (tvpl,) in conn.execute(
        "SELECT DISTINCT tvpl_id FROM chunk WHERE vai_tro = 'xu_phat'"
    ).fetchall():
        texts = [
            r[0]
            for r in conn.execute(
                "SELECT noi_dung FROM chunk WHERE tvpl_id = %s AND cap = 'dieu' ORDER BY dieu_so",
                [tvpl],
            )
        ]
        mac_dinh, ngoai_le, nguon = muc_cua(texts)
        conn.execute(
            "UPDATE van_ban SET mucphat_cua = %s, mucphat_ngoai_le = %s, mucphat_cua_nguon = %s"
            " WHERE tvpl_id = %s",
            [mac_dinh, Jsonb(ngoai_le), nguon, tvpl],
        )


def ca_nhan_to_chuc(
    tu: int | None, den: int | None, cua: str | None
) -> tuple[tuple[int | None, int | None], tuple[int | None, int | None]] | None:
    """Khung ghi trong văn bản → (khung cá nhân, khung tổ chức). Tổ chức = 2 × cá nhân (Luật XLVPHC
    Điều 23 khoản 2). None nếu chưa biết văn bản ghi mức của ai."""

    def nhan(x, h):
        return None if x is None else int(x * h)

    if cua == "ca_nhan":
        return (tu, den), (nhan(tu, 2), nhan(den, 2))
    if cua == "to_chuc":
        return (nhan(tu, 0.5), nhan(den, 0.5)), (tu, den)
    return None


# ---------- tra mức phạt cho một hành vi đã chọn ----------


@dataclass
class MucPhat:
    khoan: int
    diem: str | None
    loai: str
    tu: int | None  # khung ghi trong văn bản, đã nhân hệ số nếu là "gấp N lần"
    den: int | None
    ca_nhan: tuple[int | None, int | None] | None
    to_chuc: tuple[int | None, int | None] | None
    dieu_kien: str | None  # chữ gốc của điều kiện (vd "dưới 3.000.000 đồng")
    nguon: str
    chunk_id: int
    ghi_chu: str = ""


@dataclass
class KetQuaTra:
    muc: list[MucPhat]  # các khung áp dụng (nhiều dòng khi chưa biết giá trị hàng)
    tang_nang: list[MucPhat]  # khung "gấp N lần" áp dụng khi có tình tiết riêng (để LLM/người xét)
    da_loc_gia_tri: bool  # True: đã chọn đúng bậc theo giá trị / số lượng
    mucphat_cua: str | None
    mucphat_cua_nguon: str | None
    # khoản cùng Điều không tách được (vd "bằng 1,5 lần … đối với thuốc gây nghiện"): có thể làm
    # đổi mức phạt, bot trích nguyên văn kèm câu trả lời. [(khoản, điểm, chữ khoản)]
    nguyen_van: list[tuple[int, str | None, str]] = field(default_factory=list)


_COT = (
    "id, chunk_id, khoan_so, diem, hanh_vi, loai, tu, den, he_so, he_so_den, tran, tham_chieu,"
    " hanh_vi_tai, dk_tu, dk_tu_bao_gom, dk_den, dk_den_bao_gom, dk_don_vi, dk_chu, nguon"
)


def _khop(r: dict, gia_tri: float | None, don_vi: str) -> bool | None:
    """None: dòng không có điều kiện (hoặc khác đơn vị); True/False: giá trị có thuộc khoảng."""
    if gia_tri is None or (r["dk_tu"] is None and r["dk_den"] is None):
        return None
    if (r["dk_don_vi"] or "đồng") != don_vi:
        return None
    tu, den = r["dk_tu"], r["dk_den"]
    if tu is not None and (gia_tri < tu or (gia_tri == tu and not r["dk_tu_bao_gom"])):
        return False
    if den is not None and (gia_tri > den or (gia_tri == den and not r["dk_den_bao_gom"])):
        return False
    return True


def _dong_diem(conn: psycopg.Connection, chunk_id: int, diem: str) -> str | None:
    """Dòng "i) …" của điểm trong chunk khoản (chữ đầy đủ, kể cả phần sau dấu hai chấm)."""
    r = conn.execute("SELECT noi_dung FROM chunk WHERE id = %s", [chunk_id]).fetchone()
    if not r:
        return None
    for dong in r[0].split("\n"):
        if dong.startswith(f"{diem})"):
            return dong[len(diem) + 1 :].strip()
    return None


def tra(
    conn: psycopg.Connection,
    tvpl_id: int,
    dieu_so: int,
    dieu_suffix: str,
    khoan_so: int,
    diem: str | None = None,
    gia_tri: float | None = None,
    don_vi: str = "đồng",
) -> KetQuaTra:
    cur = conn.execute(
        f"SELECT {_COT} FROM muc_phat WHERE tvpl_id = %s AND dieu_so = %s AND dieu_suffix = %s"
        " ORDER BY khoan_so, diem NULLS FIRST",
        [tvpl_id, dieu_so, dieu_suffix],
    )
    ten = [d.name for d in cur.description]
    rows = [dict(zip(ten, r, strict=True)) for r in cur.fetchall()]
    cua, ngoai_le, nguon_cua = conn.execute(
        "SELECT mucphat_cua, mucphat_ngoai_le, mucphat_cua_nguon FROM van_ban WHERE tvpl_id = %s",
        [tvpl_id],
    ).fetchone()
    dieu_ten = f"{dieu_so}{dieu_suffix}"
    cua = next((n["cua"] for n in ngoai_le if n["dieu"] == dieu_ten), cua)

    cung_k = [r for r in rows if r["khoan_so"] == khoan_so]
    bac_cung_hanh_vi = len(cung_k) > 1 and len({r["hanh_vi"] for r in cung_k}) == 1  # dạng B
    if diem and not bac_cung_hanh_vi:
        chon = [r for r in cung_k if r["diem"] == diem] or cung_k
    else:
        chon = cung_k
    chon += [r for r in rows if khoan_so in r["hanh_vi_tai"] and r not in chon]  # bậc ở khoản khác
    # khoản không tách được không có con số: chỉ trả trong nguyen_van (trừ khi chính nó được chọn)
    chon = [r for r in chon if r["loai"] != "khong_tach" or r["khoan_so"] == khoan_so] or chon

    # "i) Phạt tiền gấp 02 lần mức tại các điểm a … h khoản này trong trường hợp hàng hóa là thực
    # phẩm": tình tiết tăng nặng của chính các bậc trong khoản, không phải hành vi riêng
    co_bac = any(x["khoan_so"] == khoan_so and x["loai"] == "tien" for x in rows)
    noi_khoan = [
        r for r in chon
        if co_bac and r["loai"] == "gap_lan" and r["khoan_so"] == khoan_so and r["diem"]
        and khoan_so in r["tham_chieu"] and r["he_so"] is not None and float(r["he_so"]) > 1
    ]  # fmt: skip
    chon = [r for r in chon if r not in noi_khoan]

    # hành vi dùng khung của khoản khác ("gấp N lần", "mức phạt tại khoản 1, 2 cũng áp dụng")
    mo_rong = []
    for r in chon:
        if r["loai"] == "gap_lan" and r["khoan_so"] == khoan_so:
            for g in (x for x in rows if x["khoan_so"] in r["tham_chieu"] and x["loai"] == "tien"):
                mo_rong.append((g, r))
    if mo_rong:
        chon = [r for r in chon if r["loai"] != "gap_lan" or r["khoan_so"] != khoan_so]

    def dung(r: dict, nhan: dict | None = None) -> MucPhat:
        h = float(nhan["he_so"]) if nhan else 1.0
        tu = None if r["tu"] is None else int(r["tu"] * h)
        den = None if r["den"] is None else int(r["den"] * h)
        tran = nhan["tran"] if nhan else r["tran"]
        if tran is not None and den is not None:
            den = min(den, tran)
        ghi = f"bằng {h:g} lần khung tại khoản {r['khoan_so']}" if nhan else ""
        if r["loai"] == "lan_gia_tri":
            ghi = f"từ {r['he_so']:g} đến {r['he_so_den']:g} lần giá trị"
            if gia_tri is not None:
                tu, den = int(float(r["he_so"]) * gia_tri), int(float(r["he_so_den"]) * gia_tri)
                if r["tran"] is not None:
                    den = min(den, r["tran"])
        cn_tc = ca_nhan_to_chuc(tu, den, cua) if r["loai"] != "canh_cao" else None
        return MucPhat(
            (nhan or r)["khoan_so"], (nhan or r)["diem"], r["loai"], tu, den,
            cn_tc[0] if cn_tc else None, cn_tc[1] if cn_tc else None, r["dk_chu"],
            r["nguon"], r["chunk_id"], ghi,
        )  # fmt: skip

    ung = [(r, None) for r in chon] + [(g, n) for g, n in mo_rong]
    khop = [(r, n) for r, n in ung if _khop(r, gia_tri, don_vi) is not False]
    da_loc = gia_tri is not None and any(_khop(r, gia_tri, don_vi) for r, _ in ung)
    if da_loc:  # đã có bậc khớp: bỏ các dòng không ghi điều kiện (vd "không xác định được giá trị")
        khop = [(r, n) for r, n in khop if _khop(r, gia_tri, don_vi)]
    if not khop:  # giá trị nằm ngoài mọi bậc (hoặc khác đơn vị): trả hết để người xem
        khop, da_loc = ung, False
    tang_nang = []
    for r in rows:
        # chỉ khung nặng hơn (hệ số > 1); hệ số 1 = hành vi khác dùng chung khung
        if (
            r["loai"] == "gap_lan"
            and r["khoan_so"] != khoan_so
            and khoan_so in r["tham_chieu"]
            and float(r["he_so"]) > 1
        ):
            for g, _ in khop[:1]:
                m = dung(g, r)
                m.dieu_kien = r["hanh_vi"]  # tình tiết làm tăng mức (vd "Là thực phẩm, thuốc…")
                tang_nang.append(m)
    for r in noi_khoan:
        dk = _dong_diem(conn, r["chunk_id"], r["diem"]) or r["dk_chu"]
        if da_loc:  # đã biết giá trị → đúng bậc nhân hệ số
            for g, _ in khop:
                m = dung(g, r)
                m.dieu_kien, m.ghi_chu = dk, f"gấp {float(r['he_so']):g} lần bậc trên"
                tang_nang.append(m)
        else:  # chưa biết bậc: một dòng "gấp N lần các mức trên"
            tang_nang.append(MucPhat(
                r["khoan_so"], r["diem"], "gap_lan", None, None, None, None, dk, r["nguon"],
                r["chunk_id"], f"gấp {float(r['he_so']):g} lần các mức trên",
            ))  # fmt: skip
    nguyen_van = [
        (r["khoan_so"], r["diem"], nd)
        for r in rows
        if r["loai"] == "khong_tach"
        for (nd,) in conn.execute("SELECT noi_dung FROM chunk WHERE id = %s", [r["chunk_id"]])
    ]
    return KetQuaTra([dung(r, n) for r, n in khop], tang_nang, da_loc, cua, nguon_cua, nguyen_van)
