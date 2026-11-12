"""Câu trả lời dạng Telegram (HTML), gọn cho điện thoại.

Chú chốt 12/11 (sau ảnh mẫu): mỗi mục (hành vi / mức phạt / bổ sung / khắc phục) có một dòng
"📌 điểm b khoản 4 Điều 31 NĐ 119/2017"; nút "📋 Quy định tại" mở tin căn cứ đầy đủ theo văn phong
biên bản (can_cu.quy_dinh_tai), mỗi căn cứ một khối <code> (chạm để chép), cuối tin là link TVPL.
Bản chữ thường (tra_loi.dinh_dang) vẫn dùng cho dòng lệnh, chat_log và eval.

Mỗi khối cách nhau một dòng trống và tự đóng thẻ, để bot.chia_tin tách tin không cắt giữa thẻ.
"""

import dataclasses
import re
from html import escape
from urllib.parse import quote

import psycopg

from qltt import can_cu as cc
from qltt import dan_chieu, muc_phat, sua_doi
from qltt.tra_loi import TraLoi, dinh_dang, tinh_tiet

TOI_DA_BIEN_PHAP = 110  # ký tự mỗi biện pháp; dài hơn thì cắt, đầy đủ ở link
TOI_DA_TRICH = 1500


def tien(x: int | None) -> str:
    """1500000 → '1,5 triệu'; 500000 → '500 nghìn'."""
    if x is None:
        return "?"
    if x >= 1_000_000_000:
        return f"{x / 1e9:g} tỷ".replace(".", ",")
    if x >= 1_000_000:
        return f"{x / 1e6:g} triệu".replace(".", ",")
    if x >= 1_000:
        return f"{x / 1e3:g} nghìn".replace(".", ",")
    return f"{x} đồng"


def khung(a: int | None, b: int | None) -> str:
    if a is None:
        return f"đến {tien(b)}"
    ta, tb = tien(a), tien(b)
    don_vi = ta.split()[-1]
    if tb.endswith(don_vi):  # "1,5 – 2,5 triệu"
        ta = ta.rsplit(" ", 1)[0]
    return f"{ta} – {tb}"


R_SO_DONG = re.compile(r"(\d{1,3}(?:\.\d{3})+)\s*đồng")


def gon_so(s: str) -> str:
    """'từ 5.000.000 đồng đến dưới 10.000.000 đồng' → 'từ 5 triệu đến dưới 10 triệu'."""
    return R_SO_DONG.sub(lambda m: tien(int(m.group(1).replace(".", ""))), s)


def cat(s: str, n: int) -> tuple[str, bool]:
    s = " ".join(s.split()).rstrip(' ”".;')
    if len(s) <= n:
        return s, False
    return s[:n].rsplit(" ", 1)[0].rstrip(",;") + "…", True


R_DAU_HANH_VI = re.compile(
    r"^(?:mức phạt tiền đối với|phạt tiền[^đ]*đối với)\s+(?:hành vi\s+)?", re.I
)
R_DUOI_HANH_VI = re.compile(
    r"\s*(?:,\s*)?(?:được quy định như sau|như sau|cụ thể như sau)\s*:?\s*$"
)


def ten_hanh_vi(hv: str) -> str:
    """Câu dẫn của khoản → tên hành vi ngắn: bỏ "Mức phạt tiền đối với hành vi", "như sau:", lấy
    vế đầu (trước dấu ;) nếu cả câu quá dài."""
    s = R_DUOI_HANH_VI.sub("", R_DAU_HANH_VI.sub("", " ".join(hv.split()))).strip(" :;.")
    s = s[:1].upper() + s[1:]
    if len(s) > 140 and len(dau := s.split(";")[0]) >= 40:
        return dau.rstrip(" ,") + "…"
    return cat(s, 160)[0]


R_DAU_BIEN_PHAP = re.compile(
    r"^Đối với (?:hành vi|vi phạm)[^:]*?(?:Điều|khoản) này[^:]*?:\s*", re.I
)
R_DUOI_BIEN_PHAP = re.compile(
    r"\s*,?\s*(?:đối với|do thực hiện) (?:các |một trong các )?(?:hành vi )?(?:vi phạm )?"
    r"(?:quy định )?tại (?:các )?(?:điểm|khoản|Điều)[^;]*?(?:Điều|khoản) này\s*$",
    re.I,
)


def gon_bien_phap(s: str) -> str:
    """'Đối với hành vi … tại khoản 1, 2 Điều này được thực hiện theo thứ tự ưu tiên sau: buộc …'
    → 'Buộc …'; bỏ đuôi '… đối với hành vi vi phạm quy định tại khoản 3 Điều này'."""
    s = " ".join(s.split()).rstrip(' ”".;')
    s = R_DUOI_BIEN_PHAP.sub("", R_DAU_BIEN_PHAP.sub("", s))
    return s[:1].upper() + s[1:]


def ten_ngan(so_hieu: str) -> str:
    """'119/2017/NĐ-CP' → 'NĐ 119/2017'; luật, VBHN giữ nguyên."""
    m = re.match(r"(\d+(?:\.\d+)?/\d{4})/(NĐ|NQ|TT|QĐ)", so_hieu)
    return f"{m.group(2)} {m.group(1)}" if m else so_hieu


class VanBan:
    """Tra số hiệu gốc (VBHN) và link TVPL, có nhớ."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self._nho: dict = {}

    def theo_id(self, tvpl_id: int) -> tuple[str, str | None]:
        """(nhãn căn cứ, link) cho văn bản đang trích."""
        if tvpl_id not in self._nho:
            so_hieu, link = self.conn.execute(
                "SELECT so_hieu, link_tvpl FROM van_ban WHERE tvpl_id = %s", [tvpl_id]
            ).fetchone()
            goc = self.conn.execute(
                "SELECT den_so_hieu FROM quan_he_van_ban WHERE tu = %s AND loai = 'hop_nhat'"
                " LIMIT 1",
                [tvpl_id],
            ).fetchone()
            nhan = f"{ten_ngan(goc[0])} ({so_hieu})" if goc else ten_ngan(so_hieu)
            self._nho[tvpl_id] = (nhan, link)
            self._nho[("goc", tvpl_id)] = ten_ngan(goc[0] if goc else so_hieu)
        return self._nho[tvpl_id]

    def ngan(self, tvpl_id: int) -> str:
        """Tên ngắn văn bản gốc để trích: VBHN 02/VBHN-BKHCN → 'NĐ 119/2017'."""
        self.theo_id(tvpl_id)
        return self._nho[("goc", tvpl_id)]

    def link_so_hieu(self, so_hieu: str) -> str | None:
        k = ("sh", so_hieu)
        if k not in self._nho:
            r = self.conn.execute(
                "SELECT link_tvpl FROM van_ban WHERE so_hieu = %s LIMIT 1", [so_hieu]
            ).fetchone()
            self._nho[k] = r[0] if r else None
        return self._nho[k]


def a(chu: str, link: str | None) -> str:
    return f'<a href="{escape(link, quote=True)}">{escape(chu)}</a>' if link else escape(chu)


@dataclasses.dataclass(frozen=True)
class ViTri:
    """Một chỗ trích trong văn bản đang tra (diem: các điểm cùng khoản, có thể rỗng)."""

    tvpl_id: int
    dieu: int
    ht: str
    khoan: int | None
    kht: str = ""
    diem: tuple[str, ...] = ()

    def chu(self) -> str:
        return cc.vi_tri(self.dieu, self.ht, self.khoan, list(self.diem), self.kht)


THU_TU_DIEM = "aăâbcdđeêghiklmnoôơpqrstuưvxy"


def khoa_diem(d: str | None) -> tuple:
    """Thứ tự điểm theo bảng chữ cái tiếng Việt (đ sau d, không xếp sau z như SQL)."""
    return tuple(THU_TU_DIEM.find(ch) for ch in (d or ""))


def gop(ds: list[ViTri]) -> list[ViTri]:
    """Gộp điểm cùng khoản: [điểm a k4, điểm b k4] → điểm a, điểm b khoản 4 (giữ thứ tự)."""
    theo: dict[tuple, list[str]] = {}
    for x in ds:
        d = theo.setdefault((x.tvpl_id, x.dieu, x.ht, x.khoan, x.kht), [])
        d += [y for y in x.diem if y not in d]
    return [ViTri(*k, tuple(sorted(d, key=khoa_diem))) for k, d in theo.items()]


def ghim(vb: VanBan, ds: list[ViTri]) -> str:
    """'📌 điểm b khoản 4 Điều 31 NĐ 119/2017' (nhiều chỗ: cách nhau dấu ;)."""
    return "📌 " + "; ".join(escape(f"{x.chu()} {vb.ngan(x.tvpl_id)}") for x in ds)


@dataclasses.dataclass
class Muc:
    """Một mục trong chuỗi căn cứ của hành vi."""

    ten: str
    vi_tri: list[ViTri]


def chuoi_vi_tri(tl: TraLoi, h) -> list[Muc]:
    """Hành vi → mức phạt → tăng nặng → bổ sung → khắc phục (mục rỗng: "Không quy định")."""
    u, m = h.uv, h.muc

    def vt(k, d, kht=""):
        return ViTri(u.tvpl_id, u.dieu_so, u.dieu_suffix, k, kht, (d,) if d else ())

    diem_hv = m.muc[0].diem if len(m.muc) == 1 and m.muc[0].diem else u.diem
    ra = [Muc("Hành vi vi phạm", [vt(u.khoan_so, diem_hv, u.khoan_suffix)])]
    ra.append(Muc("Mức phạt", gop([vt(x.khoan, x.diem) for x in m.muc])))
    if m.tang_nang:
        ra.append(Muc("Tình tiết tăng nặng", gop([vt(x.khoan, x.diem) for x in m.tang_nang])))
    for ten, loai in (
        ("Hình thức xử phạt bổ sung", "bo_sung"), ("Biện pháp khắc phục hậu quả", "khac_phuc")
    ):  # fmt: skip
        ra.append(Muc(ten, gop([vt(b.khoan_so, b.diem) for b in h.bien_phap if b.loai == loai])))
    return ra


def can_cu(vb: VanBan, vi_tri: str, tvpl_id: int) -> str:
    nhan, link = vb.theo_id(tvpl_id)
    return a(f"{vi_tri} {nhan}", link)


def khoi_canh_bao(vb: VanBan, cb: list[sua_doi.CanhBao], trich: str = "") -> list[str]:
    ra = []
    gop = sua_doi.gop_canh_bao(cb, trich)
    for x, n in gop[: sua_doi.TOI_DA_CANH_BAO]:
        hl = []
        if x.trang_thai != "hieu_luc":
            hl.append(f"có hiệu lực từ {x.ngay_hieu_luc}")
        if x.ngay_het_hieu_luc:
            hl.append(f"áp dụng đến {x.ngay_het_hieu_luc}")
        hl_s = f" ({', '.join(hl)})" if hl else ""
        sau = (
            "quy định trên có thể không còn áp dụng"
            if x.hanh_dong in ("bai_bo", "khong_thuc_hien")
            else "nội dung trên có thể là chữ cũ, xem chữ mới ở link"
        )
        mo_ta = cat(x.mo_ta, 200)[0] + (f" (và {n - 1} dòng tương tự)" if n > 1 else "")
        ra.append(
            f"⚠️ {sua_doi.TEN_HANH_DONG[x.hanh_dong]} "
            f"{a(f'{x.vi_tri_tu} {x.so_hieu}', vb.link_so_hieu(x.so_hieu))}{escape(hl_s)}: "
            f"{escape(mo_ta)}. <i>{sau}</i>"
        )
    if len(gop) > sua_doi.TOI_DA_CANH_BAO:
        con = gop[sua_doi.TOI_DA_CANH_BAO :]
        ra.append(f"⚠️ Và {sum(n for _, n in con)} chỉ dẫn sửa đổi khác.")
    return ra


def khoi_dan_chieu(conn, tvpl: int, dieu: int, ht: str, khoan: int | None) -> list[str]:
    return [
        "🔗 " + escape(d.strip().removeprefix("Dẫn chiếu: "))
        for d in dan_chieu.dong_dan_chieu(conn, tvpl, dieu, ht, khoan, thut="")
        if d.strip().startswith("Dẫn chiếu:")
    ]


def muc_tien(m: muc_phat.MucPhat, chu_the: str) -> str:
    """Một mức: 'cá nhân <b>1,5 – 2,5 triệu</b>; tổ chức <b>3 – 5 triệu</b>'."""
    truoc = "cảnh cáo hoặc " if m.loai == "canh_cao_hoac_tien" else ""
    if m.loai == "canh_cao":
        return "<b>phạt cảnh cáo</b>"
    if m.loai == "khong_tach":
        return "xem nguyên văn ở link căn cứ"
    if m.loai in ("lan_gia_tri", "gap_lan") and m.tu is None:
        return f"<b>{escape(m.ghi_chu)}</b>" + (" trị giá hàng" if m.loai == "lan_gia_tri" else "")
    if m.ca_nhan is None:
        return f"{truoc}<b>{khung(m.tu, m.den)}</b> (văn bản không nói rõ của cá nhân hay tổ chức)"
    cn, tc = f"<b>{khung(*m.ca_nhan)}</b>", f"<b>{khung(*m.to_chuc)}</b>"
    if chu_the == "ca_nhan":
        return f"{truoc}cá nhân {cn}"
    if chu_the == "to_chuc":
        return f"{truoc}tổ chức {tc}"
    return f"{truoc}cá nhân {cn}; tổ chức {tc}"


def khoi_hanh_vi(conn, vb: VanBan, tl: TraLoi, i: int, h) -> list[str]:
    u, m = h.uv, h.muc
    muc_vt = {x.ten: x.vi_tri for x in chuoi_vi_tri(tl, h)}
    so = f"{i}. " if len(tl.chon) > 1 else ""
    dau = [f"🔹 <b>{so}Hành vi vi phạm:</b> {escape(ten_hanh_vi(u.hanh_vi))}"]
    if h.dieu_kien and len(tl.chon) > 1:
        dau.append(f"Khi: {escape(h.dieu_kien)}")
    dau.append(ghim(vb, muc_vt["Hành vi vi phạm"]))
    dau += khoi_canh_bao(
        vb, sua_doi.canh_bao(conn, u.tvpl_id, u.dieu_so, u.dieu_suffix, u.khoan_so), u.hanh_vi
    )
    dau += khoi_dan_chieu(conn, u.tvpl_id, u.dieu_so, u.dieu_suffix, u.khoan_so)
    khoi = ["\n".join(dau)]

    phat = []
    # điểm cùng khung (dạng A, chưa rõ điểm) → một dòng
    muc = list({(x.loai, x.tu, x.den, x.dieu_kien): x for x in m.muc}.values())
    muc.sort(key=lambda x: (x.khoan, khoa_diem(x.diem)))
    m = dataclasses.replace(m, muc=muc)
    if len(m.muc) == 1:
        x = m.muc[0]
        nhan = ""
        if x.dieu_kien and m.da_loc_gia_tri:
            dk = gon_so(x.dieu_kien)
            nhan = f" ({'trị giá ' if re.search(r'triệu|nghìn|tỷ|đồng', dk) else ''}{escape(dk)})"
        if x.ca_nhan is not None and tl.chu_the == "khong_ro" and x.loai != "canh_cao":
            truoc = "cảnh cáo hoặc " if x.loai == "canh_cao_hoac_tien" else ""
            phat.append(f"💰 <b>Mức phạt</b>{nhan}:")
            phat.append(f"• Cá nhân: {truoc}<b>{khung(*x.ca_nhan)}</b>")
            phat.append(f"• Tổ chức: {truoc}<b>{khung(*x.to_chuc)}</b>")
        else:
            phat.append(f"💰 <b>Mức phạt</b>{nhan}: {muc_tien(x, tl.chu_the)}")
    else:
        phat.append("💰 <b>Mức phạt</b> theo từng trường hợp:")
        for x in m.muc:
            nhan = escape(gon_so(x.dieu_kien)) + ": " if x.dieu_kien else ""
            phat.append(f"• {nhan}{muc_tien(x, tl.chu_the)}")
    phat.append(ghim(vb, muc_vt["Mức phạt"]))
    for x in m.tang_nang:
        tt = re.sub(r"[\s\u00a0]+$", "", tinh_tiet(x.dieu_kien or ""))
        vt = ViTri(u.tvpl_id, u.dieu_so, u.dieu_suffix, x.khoan, "", (x.diem,) if x.diem else ())
        dong = f"• Nếu {escape(tt)}: {muc_tien(x, tl.chu_the)} ({escape(vt.chu())})"
        if x.khoan != u.khoan_so:  # khung tăng nặng ở khoản khác có thể bị sửa / tạm dừng riêng
            cb = sua_doi.canh_bao(conn, u.tvpl_id, u.dieu_so, u.dieu_suffix, x.khoan)
            if cb:
                y = cb[0]
                dong += (
                    f" (⚠️ khoản {x.khoan}: {sua_doi.TEN_HANH_DONG[y.hanh_dong].lower()} "
                    f"{a(f'{y.vi_tri_tu} {y.so_hieu}', vb.link_so_hieu(y.so_hieu))})"
                )
        phat.append(dong)
    for k, d, nd in m.nguyen_van:
        if (k, d) != (u.khoan_so, u.diem):
            phat.append(f"📝 Lưu ý khoản {k}: {escape(cat(nd, 400)[0])}")
    khoi.append("\n".join(phat))

    bp = []
    for ten, loai in (
        ("Hình thức xử phạt bổ sung", "bo_sung"), ("Biện pháp khắc phục hậu quả", "khac_phuc")
    ):  # fmt: skip
        bieu = "➕" if loai == "bo_sung" else "🔧"
        ds = [b for b in h.bien_phap if b.loai == loai]
        if not ds:
            bp.append(f"{bieu} <b>{ten}:</b> Không quy định")
            continue
        phan, cut = [], False
        for b in ds[:2]:
            s, c = cat(gon_bien_phap(b.noi_dung), TOI_DA_BIEN_PHAP)
            phan.append(escape(s) + ("" if b.chac else " (cần xem nguyên văn)"))
            cut = cut or c
        them = f"; và {len(ds) - 2} biện pháp khác" if len(ds) > 2 else ""
        cut = cut or len(ds) > 2
        bp.append(
            f"{bieu} <b>{ten}:</b> " + "; ".join(phan) + them
            + (" <i>(đầy đủ ở văn bản)</i>" if cut else "")
            + "\n" + ghim(vb, muc_vt[ten])
        )  # fmt: skip
    return khoi + bp  # bổ sung, khắc phục: mỗi mục một đoạn (cách dòng trống)


def telegram(conn: psycopg.Connection, tl: TraLoi) -> str:
    """Câu trả lời HTML cho Telegram (parse_mode HTML, tắt xem trước link)."""
    vb = VanBan(conn)
    if tl.loai == "quy_dinh" and tl.trich:
        khoi = ["📖 <b>Quy định liên quan</b> (trích nguyên văn)"]
        for i, x in enumerate(tl.trich, 1):
            d = x.doan
            vt = ViTri(d.tvpl_id, d.dieu_so, d.dieu_suffix, d.khoan_so)
            dong = [f"{i}. <b>{escape(d.dieu_ten)}</b>", ghim(vb, [vt])]
            dong += khoi_canh_bao(
                vb, sua_doi.canh_bao(conn, d.tvpl_id, d.dieu_so, d.dieu_suffix, d.khoan_so),
                d.noi_dung,
            )  # fmt: skip
            dong += khoi_dan_chieu(conn, d.tvpl_id, d.dieu_so, d.dieu_suffix, d.khoan_so)
            if x.trich:
                dong.append(f"<i>«…{escape(cat(x.trich, TOI_DA_TRICH)[0])}…»</i>")
            else:
                dong.append(f"<i>«{escape(cat(d.noi_dung, TOI_DA_TRICH)[0])}»</i>")
            khoi.append("\n".join(dong))
        return "\n\n".join(khoi)
    if tl.loai != "hanh_vi" or not tl.chon:
        return escape(dinh_dang(conn, tl))  # khác / ngoài phạm vi / không tìm thấy: chữ thường
    khoi = []
    if len(tl.chon) > 1:
        khoi.append(f"Tình huống có thể thuộc {len(tl.chon)} hành vi; tùy tình tiết thực tế:")
    for i, h in enumerate(tl.chon, 1):
        khoi += khoi_hanh_vi(conn, vb, tl, i, h)
    if tl.chu_the == "khong_ro" and any(x.ca_nhan for h in tl.chon for x in h.muc.muc):
        khoi.append("ℹ️ Câu hỏi không nói rõ cá nhân hay tổ chức nên nêu cả hai.")
    return "\n\n".join(khoi)


VAI_TRO_CANH_BAO = {
    "sua_doi": "sửa đổi (chưa hợp nhất)", "bo_sung": "bổ sung (chưa hợp nhất)",
    "bai_bo": "bãi bỏ", "thay_cum_tu": "thay cụm từ (chưa hợp nhất)",
    "khong_thuc_hien": "tạm dừng áp dụng",
}  # fmt: skip
TIM_TVPL = "https://thuvienphapluat.vn/page/tim-van-ban.aspx?keyword={}"
R_SO_TRONG_CAN_CU = re.compile(r"\bsố (\d[\w./\-]*\w)")


def _dong_can_cu(conn, ds: list[ViTri], chu_ra: list[str]) -> list[str]:
    """Mỗi chỗ một khối <code>; chữ căn cứ gom vào chu_ra (để lấy các văn bản được nêu)."""
    ra = []
    for x in ds:
        chu = cc.quy_dinh_tai(conn, x.tvpl_id, x.dieu, x.ht, x.khoan, list(x.diem), x.kht)
        ra.append(f"<code>{escape(chu)}</code>")
        chu_ra.append(chu)
    return ra


def van_ban_lien_quan(
    conn, vb: VanBan, ds: list[ViTri], can_cu_chu: list[str]
) -> list[str]:  # fmt: skip
    """Mọi văn bản liên quan tới các chỗ được trích, mỗi văn bản một dòng có link:
    văn bản bot đọc (VBHN) → văn bản gốc → văn bản sửa đổi nêu trong căn cứ → văn bản sửa / tạm
    dừng chưa hợp nhất (cảnh báo) → văn bản được dẫn chiếu. Thiếu trong kho: link tìm trên TVPL."""
    ra: dict[str, str] = {}  # khóa: số hiệu / tên → dòng

    def them(khoa: str, nhan: str, vai_tro: str, link: str | None = None) -> None:
        if khoa in ra:
            return
        url = link or vb.link_so_hieu(khoa)
        goi_y = "" if url else " (chưa có trong kho)"
        ra[khoa] = f"• {a(nhan, url or TIM_TVPL.format(quote(khoa)))} – {vai_tro}{goi_y}"

    for t in dict.fromkeys(x.tvpl_id for x in ds):
        so_hieu, link = conn.execute(
            "SELECT so_hieu, link_tvpl FROM van_ban WHERE tvpl_id = %s", [t]
        ).fetchone()
        nhan, _ = vb.theo_id(t)
        la_vbhn = "VBHN" in so_hieu
        them(so_hieu, nhan, "bản hợp nhất, bot đang đọc" if la_vbhn else "văn bản gốc", link)
    for chu in can_cu_chu:
        so = R_SO_TRONG_CAN_CU.findall(chu)
        for i, x in enumerate(so):
            them(x, ten_ngan(x), "văn bản gốc" if i == 0 else "sửa đổi, bổ sung")
    for x in dict.fromkeys(ds):
        for cb in sua_doi.canh_bao(conn, x.tvpl_id, x.dieu, x.ht, x.khoan):
            them(cb.so_hieu, ten_ngan(cb.so_hieu), VAI_TRO_CANH_BAO[cb.hanh_dong])
        rows = conn.execute(
            """
            SELECT DISTINCT d.den_loai, d.den_khoa, v.so_hieu, v.link_tvpl
            FROM dan_chieu d JOIN chunk c ON c.id = d.tu_chunk_id
            LEFT JOIN van_ban v ON v.tvpl_id = d.den_tvpl_id
            WHERE c.tvpl_id = %s AND c.dieu_so = %s AND c.dieu_suffix = %s
              AND (%s::int IS NULL OR c.khoan_so = %s OR c.cap = 'dieu')
              AND d.den_loai <> 'chu_de'
            """,
            [x.tvpl_id, x.dieu, x.ht, x.khoan, x.khoan],
        ).fetchall()
        for loai, khoa, so_hieu, link in rows:
            if khoa in dan_chieu.BO_QUA_HIEN_THI or so_hieu in dan_chieu.BO_QUA_HIEN_THI:
                continue
            ten = f"Luật {khoa}" if loai == "ten_luat" else ten_ngan(khoa)
            them(so_hieu or khoa, ten, "được dẫn chiếu", link)
    return list(ra.values())


def quy_dinh_tai(conn: psycopg.Connection, tl: TraLoi) -> str | None:
    """Tin "📋 Quy định tại" (nút dưới câu trả lời): căn cứ đầy đủ, chạm để chép.
    None: câu trả lời không có căn cứ (không tìm thấy / ngoài phạm vi)."""
    vb = VanBan(conn)
    khoi, vt_ds, chu = ["📋 <b>Quy định tại</b>"], [], []
    if tl.loai == "quy_dinh" and tl.trich:
        for i, x in enumerate(tl.trich, 1):
            d = x.doan
            vt = ViTri(d.tvpl_id, d.dieu_so, d.dieu_suffix, d.khoan_so)
            vt_ds.append(vt)
            khoi.append(
                f"<b>{i}. {escape(d.dieu_ten)}</b>\n" + "\n".join(_dong_can_cu(conn, [vt], chu))
            )
    elif tl.loai == "hanh_vi" and tl.chon:
        for i, h in enumerate(tl.chon, 1):
            dong = []
            if len(tl.chon) > 1:
                dong.append(f"<b>Hành vi {i}:</b> {escape(ten_hanh_vi(h.uv.hanh_vi))}")
            for j, mc in enumerate(chuoi_vi_tri(tl, h), 1):
                vt_ds += mc.vi_tri
                cu = _dong_can_cu(conn, mc.vi_tri, chu) or ["Không quy định"]
                dong.append(f"{j}. {mc.ten}:\n" + "\n".join(cu))
            khoi.append("\n".join(dong))
    else:
        return None
    if lien_quan := van_ban_lien_quan(conn, vb, vt_ds, chu):
        khoi.append("🔗 <b>Văn bản liên quan:</b>\n" + "\n".join(lien_quan))
    khoi.append("<i>Chạm vào khối căn cứ để chép.</i>")
    return "\n\n".join(khoi)
