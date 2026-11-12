"""Dẫn chiếu (GĐ 3.3b): chỗ nào trong văn bản đang tra trỏ sang văn bản khác, và văn bản đó có trong
kho không.

Ba dạng (kiến trúc dữ liệu mục 4.9):
  ten_luat  "theo quy định tại khoản 2 Điều 3 Luật Xử lý vi phạm hành chính" → luật trong kho
            (văn bản gốc đã có VBHN → VBHN đang tra)
  so_hieu   "Nghị định số 17/2023/NĐ-CP" → văn bản trong kho
  chu_de    "quy định của pháp luật về thẩm định giá" → bảng CHU_DE (tay) hoặc tên luật trùng chủ đề

Mỗi dẫn chiếu: ok (văn bản đích đang dùng để tra), thieu_van_ban (không có / không dùng để tra:
nhờ chú bổ sung), chua_anh_xa (chủ đề chưa có trong bảng CHU_DE). Dựng lại toàn bộ sau nạp.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

import psycopg

from qltt.parse import chuan_so_hieu
from qltt.sua_doi import R_SO_BAT_KY

# Luật hay được nhắc mà tên có "và" / dấu phẩy (không cắt được theo dấu câu), và luật ngoài kho
# (để báo thiếu đúng tên thay vì cụm chữ dài)
TEN_LUAT_THEM = [
    "Bảo vệ và kiểm dịch thực vật", "Tiêu chuẩn và quy chuẩn kỹ thuật", "Phí và lệ phí",
    "Phòng, chống tác hại của thuốc lá", "Phòng, chống tác hại của rượu, bia",
    "Ban hành văn bản quy phạm pháp luật", "Chất lượng sản phẩm, hàng hóa",
    "Hóa chất", "Đầu tư", "Hợp tác xã", "Ngân sách nhà nước", "Quản lý thuế", "Người khuyết tật",
    "Di sản văn hóa", "Điện ảnh", "Bảo hiểm y tế", "Báo chí", "Cán bộ, công chức", "Kế toán",
    "Đấu thầu", "Bảo vệ môi trường", "Lao động", "Quy hoạch", "An ninh mạng", "Hải quan",
    "Xây dựng", "Đất đai", "Giao dịch điện tử", "Khám bệnh, chữa bệnh", "Dân sự",
    "Phòng cháy, chữa cháy", "Khoa học và công nghệ", "An toàn, vệ sinh lao động",
]  # fmt: skip

# "pháp luật về X" → tên luật (khóa so khớp chữ thường, bỏ dấu câu cuối)
CHU_DE = {
    "thẩm định giá": "Giá",
    "giá": "Giá",
    "quản lý giá": "Giá",
    "bảo vệ quyền lợi người tiêu dùng": "Bảo vệ quyền lợi người tiêu dùng",
    "xử lý vi phạm hành chính": "Xử lý vi phạm hành chính",
    "quyền tác giả": "Sở hữu trí tuệ",
    "quyền tác giả, quyền liên quan": "Sở hữu trí tuệ",
    "sở hữu trí tuệ": "Sở hữu trí tuệ",
    "sở hữu công nghiệp": "Sở hữu trí tuệ",
    "quảng cáo": "Quảng cáo",
    "an toàn thực phẩm": "An toàn thực phẩm",
    "dược": "Dược",
    "thú y": "Thú y",
    "trồng trọt": "Trồng trọt",
    "chăn nuôi": "Chăn nuôi",
    "thương mại": "Thương mại",
    "hoạt động thương mại": "Thương mại",
    "doanh nghiệp": "Doanh nghiệp",
    "đo lường": "Đo lường",
    "chất lượng sản phẩm, hàng hóa": "Chất lượng sản phẩm, hàng hóa",
    "tiêu chuẩn và quy chuẩn kỹ thuật": "Tiêu chuẩn và quy chuẩn kỹ thuật",
    "đấu thầu": "Đấu thầu",
    "thuế": "Quản lý thuế",
    "bảo vệ môi trường": "Bảo vệ môi trường",
    "lao động": "Lao động",
    "kế toán": "Kế toán",
    "bảo hiểm y tế": "Bảo hiểm y tế",
    "quy hoạch": "Quy hoạch",
    "dân sự": "Dân sự",
    "xuất bản": "Xuất bản",
    "du lịch": "Du lịch",
    "thủy sản": "Thủy sản",
    "xử phạt vi phạm hành chính": "Xử lý vi phạm hành chính",
    "giá thuốc": "Dược",
    "nhãn hàng hóa": "43/2017/NĐ-CP",
    "ghi nhãn hàng hóa": "43/2017/NĐ-CP",
    "khuyến mại": "81/2018/NĐ-CP",
    "thương mại điện tử": "52/2013/NĐ-CP",
    "phòng cháy": "Phòng cháy, chữa cháy",
    "phòng cháy và chữa cháy": "Phòng cháy, chữa cháy",
    "phòng cháy, chữa cháy": "Phòng cháy, chữa cháy",
    "khiếu nại": "Khiếu nại",
    "thanh tra": "Thanh tra",
    "chứng khoán": "Chứng khoán",
    "ngoại hối": "Pháp lệnh Ngoại hối",
    "lưu trữ": "Lưu trữ",
    "đa dạng sinh học": "Đa dạng sinh học",
    "môi trường": "Bảo vệ môi trường",
    "chất lượng": "Chất lượng sản phẩm, hàng hóa",
    "khoa học và công nghệ": "Khoa học và công nghệ",
    "đầu tư công": "Đầu tư công",
    "an toàn vệ sinh lao động": "An toàn, vệ sinh lao động",
    "bảo vệ bí mật nhà nước": "Bảo vệ bí mật nhà nước",
    "tố tụng dân sự": "Bộ luật Tố tụng dân sự",
    "tố tụng hình sự": "Bộ luật Tố tụng hình sự",
    "thuế thu nhập doanh nghiệp": "Thuế thu nhập doanh nghiệp",
    "cạnh tranh": "Cạnh tranh",
    "kinh doanh thuốc lá": "67/2013/NĐ-CP",
    "kinh doanh rượu": "105/2017/NĐ-CP",
    "kinh doanh xăng dầu": "83/2014/NĐ-CP",
    "kinh doanh khí": "87/2018/NĐ-CP",
    "bảo đảm an toàn thực phẩm": "An toàn thực phẩm",
    "quỹ bình ổn giá": "Giá",
    "giám định": "Thương mại",
}

R_LUAT = re.compile(r"\bLuật ([A-ZĐ][^\d;.:()“”\n]{1,90})")
R_PHAP_LUAT_VE = re.compile(r"pháp luật về ([^;.:()“”\n]{2,90})")
# phần chữ sau tên chủ đề không thuộc tên: "thẩm định giá sau thời gian 15 ngày …"
R_CAT_CHU_DE = re.compile(
    r"\s+(?:sau|trước|khi|thì|mà|đối với|theo|trong|tại|quy định|có|là|để|và các|hoặc"
    r"|không|với|của|và các)\b|\s+và$|\s*,\s+(?!quyền|hàng hóa|bia|công chức|chữa|chống|vệ sinh)"
)
R_CAT_TEN = re.compile(
    r"\s+(?:số|năm|ngày|và|được|để|là|có|bao gồm|gồm|về|đứng|thì|lại|phải|trong|quy định|với"
    r"|theo|hoặc|này|các|đối với)\b|;|,(?!\s*(?:chống|chữa|vệ sinh|công chức|bia))"
)
R_VI_TRI_TRUOC = re.compile(
    r"(?:khoản\s+(\d+)[a-zđ]?\s+)?Điều\s+(\d+)([a-zđ]?)\s*(?:của\s+)?$", re.I
)


def bo_dau(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


@dataclass
class DanChieu:
    tu_chunk_id: int
    den_loai: str
    den_khoa: str
    den_tvpl_id: int | None
    den_dieu: int | None
    den_dieu_suffix: str
    den_khoan: int | None
    trang_thai: str


class BangLuat:
    """Tên luật → văn bản đang tra (gốc có VBHN thì lấy VBHN)."""

    def __init__(self, conn: psycopg.Connection):
        self.tra: dict[str, int] = {}  # so_hieu_chuan → tvpl đang tra
        for sh, tvpl, tra in conn.execute(
            "SELECT so_hieu_chuan, tvpl_id, dung_de_tra FROM van_ban"
        ):
            if tra:
                self.tra[sh] = tvpl
        # văn bản gốc không tra nhưng có VBHN đang tra
        for den_sh, vbhn in conn.execute(
            "SELECT q.den_so_hieu, q.tu FROM quan_he_van_ban q JOIN van_ban h ON h.tvpl_id = q.tu"
            " WHERE q.loai IN ('hop_nhat', 'hop_nhat_sua') AND h.dung_de_tra"
        ):
            self.tra.setdefault(den_sh, vbhn)  # gốc hoặc văn bản sửa đổi đã hợp nhất → VBHN
        self.luat: dict[str, str] = {}  # tên chuẩn (bỏ dấu) → so_hieu_chuan
        self.ten: dict[str, str] = {}  # tên chuẩn → tên hiển thị
        for sh, ten in conn.execute(
            "SELECT so_hieu_chuan, ten FROM van_ban WHERE loai = 'luat' AND ten IS NOT NULL"
            " AND ten !~* '^(LUẬT\\s+)?SỬA ĐỔI'"
        ):
            t = re.sub(r"^LUẬT\s+", "", ten.strip(), flags=re.I)
            t = re.split(r"\s+QUỐC HỘI\b", t)[0].strip(" ,")
            self.luat[bo_dau(t)] = sh
            self.ten[bo_dau(t)] = t[:1] + t[1:].lower()
        for t in TEN_LUAT_THEM:
            self.ten.setdefault(bo_dau(t), t)

    def ten_dai_nhat(self, chu: str) -> str | None:
        """Tên luật biết được dài nhất mà chu bắt đầu bằng nó."""
        k = bo_dau(chu)
        hop = [t for t in self.ten if k == t or k.startswith(t + " ") or k.startswith(t + ",")]
        return max(hop, key=len) if hop else None

    def giai(self, ten_khoa: str) -> tuple[int | None, str]:
        sh = self.luat.get(ten_khoa)
        if sh and sh in self.tra:
            return self.tra[sh], "ok"
        return None, "thieu_van_ban"


R_LOAI_TRUOC_SO = re.compile(
    r"(?:Nghị định|Luật|Thông tư(?: liên tịch)?|Quyết định|Nghị quyết|Pháp lệnh)[^\d]{0,40}?"
    r"(?:số\s*)?$"
)


SO_HIEU = r"\d{1,4}(?:\.\d{1,3})?/\d{4}/\s?[A-ZĐa-zđ][A-ZĐa-zđ0-9\-]*"


def _ten_goc(chu: str, ten: str) -> str:
    """Phần đầu của chu ứng với tên luật (giữ nguyên hoa thường / dấu như trong văn bản)."""
    return chu[: len(ten)]


def _vi_tri_truoc(text: str, dau: int) -> tuple[int | None, str, int | None]:
    """'khoản 2 Điều 3' đứng ngay trước tên / số hiệu văn bản ở vị trí dau."""
    truoc = R_LOAI_TRUOC_SO.sub("", text[max(0, dau - 90) : dau])
    m = R_VI_TRI_TRUOC.search(truoc[-50:])
    if not m:
        return None, "", None
    return int(m.group(2)), m.group(3), int(m.group(1)) if m.group(1) else None


def tim(bang: BangLuat, chunk_id: int, so_hieu_tu: str, text: str) -> list[DanChieu]:
    ra: list[DanChieu] = []
    da: set[tuple] = set()

    def them(x: DanChieu):
        k = (x.den_loai, x.den_khoa, x.den_dieu, x.den_khoan)
        if k not in da:
            da.add(k)
            ra.append(x)

    luat_co_so: dict[int, DanChieu] = {}  # vị trí số hiệu → dẫn chiếu tên luật đứng ngay trước
    for m in R_LUAT.finditer(text):
        chu = m.group(1)
        if re.match(r"(?i)số\b|sửa đổi", chu):
            continue  # "Luật số 56/2024" → dạng số hiệu; "Luật sửa đổi …" → bỏ
        t = bang.ten_dai_nhat(chu)
        if t is None:
            ten = R_CAT_TEN.split(chu, maxsplit=1)[0].strip()
            if len(ten) < 3:
                continue
            t = bo_dau(ten)
            bang.ten.setdefault(t, ten)
        tvpl, tt = bang.giai(t)
        d, h, k = _vi_tri_truoc(text, m.start())
        x = DanChieu(chunk_id, "ten_luat", bang.ten[t], tvpl, d, h, k, tt)
        them(x)
        # "Luật Di sản văn hóa số 45/2024/QH15": số hiệu ngay sau tên là của chính luật này
        if so := re.match(
            rf"\s*(?:số\s*)?({SO_HIEU})", text[m.start() + 5 + len(_ten_goc(chu, bang.ten[t])) :]
        ):
            luat_co_so[so.start(1) + m.start() + 5 + len(_ten_goc(chu, bang.ten[t]))] = x
    for m in R_SO_BAT_KY.finditer(text):
        sh = chuan_so_hieu(re.sub(r"\s+", "", m.group()))
        if sh == so_hieu_tu:
            continue
        tvpl = bang.tra.get(sh)
        if (x := luat_co_so.get(m.start())) is not None:
            if x.trang_thai != "ok" and tvpl:
                x.den_tvpl_id, x.trang_thai = tvpl, "ok"
            continue
        d, h, k = _vi_tri_truoc(text, m.start())
        them(DanChieu(chunk_id, "so_hieu", sh, tvpl, d, h, k, "ok" if tvpl else "thieu_van_ban"))
    for m in R_PHAP_LUAT_VE.finditer(text):
        tho = m.group(1)
        t = bang.ten_dai_nhat(tho)  # "phòng, chống tác hại của thuốc lá …" → tên luật biết
        cd = (bang.ten[t].lower() if t else R_CAT_CHU_DE.split(tho, maxsplit=1)[0]).strip(" ,")
        cd = re.sub(r"\s+(?:và|tùy)$", "", cd).lower()
        if len(cd) < 2:
            continue
        goc = re.sub(r"^(?:hoạt động|quản lý)\s+", "", cd)  # "hoạt động quảng cáo" → quảng cáo
        dich = (CHU_DE.get(cd) or CHU_DE.get(goc) or (bang.ten[t] if t else None)
                or bang.ten.get(bo_dau(goc)))  # fmt: skip
        if not dich:
            them(DanChieu(chunk_id, "chu_de", f"pháp luật về {cd}", None, None, "", None,
                          "chua_anh_xa"))  # fmt: skip
            continue
        if R_SO_BAT_KY.fullmatch(dich):  # chủ đề → nghị định
            tvpl = bang.tra.get(dich)
            ten_dich, tt = dich, "ok" if tvpl else "thieu_van_ban"
        else:
            tvpl, tt = bang.giai(bo_dau(dich))
            bang.ten.setdefault(bo_dau(dich), dich)
            ten_dich = dich if dich.startswith(("Bộ luật", "Pháp lệnh")) else f"Luật {dich}"
        them(DanChieu(chunk_id, "chu_de", f"pháp luật về {cd} → {ten_dich}", tvpl, None, "", None,
                      tt))  # fmt: skip
    return ra


def dung_lai(conn: psycopg.Connection) -> int:
    """Xóa và ghi lại dan_chieu cho chunk lá (khoản, hoặc Điều không chia khoản) của văn bản đang
    tra; bỏ Điều hiệu lực / thẩm quyền (dẫn chiếu ở đó là văn bản cũ bị thay, không phải căn cứ)."""
    bang = BangLuat(conn)
    rows = conn.execute(
        """
        SELECT c.id, v.so_hieu_chuan, c.noi_dung FROM chunk c JOIN van_ban v USING (tvpl_id)
        WHERE v.dung_de_tra AND c.cap IN ('dieu', 'khoan') AND c.embed
            AND NOT EXISTS (SELECT 1 FROM chunk k WHERE k.cha_id = c.id)
        """
    ).fetchall()
    with conn.transaction():
        conn.execute("DELETE FROM dan_chieu")
        n = 0
        with conn.cursor() as cur:
            for cid, sh, nd in rows:
                ds = tim(bang, cid, sh, nd)
                n += len(ds)
                cur.executemany(
                    "INSERT INTO dan_chieu (tu_chunk_id, den_loai, den_khoa, den_tvpl_id, den_dieu,"
                    " den_dieu_suffix, den_khoan, trang_thai)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [(x.tu_chunk_id, x.den_loai, x.den_khoa, x.den_tvpl_id, x.den_dieu,
                      x.den_dieu_suffix, x.den_khoan, x.trang_thai) for x in ds],
                )  # fmt: skip
    return n


@dataclass
class BaoCao:
    theo_trang_thai: Counter
    thieu: list[tuple[str, str, int]]  # (loại, khóa, số chỗ nhắc)
    chua_anh_xa: list[tuple[str, int]]


def bao_cao(conn: psycopg.Connection, chi_qltt: bool = True) -> BaoCao:
    """chi_qltt: chỉ tính dẫn chiếu từ văn bản liên quan quản lý thị trường (qltt_lien_quan)."""
    loc = (
        " AND d.tu_chunk_id IN (SELECT c.id FROM chunk c JOIN van_ban v USING (tvpl_id)"
        " WHERE v.qltt_lien_quan)"
        if chi_qltt
        else ""
    )
    tt = Counter(dict(conn.execute(
        f"SELECT trang_thai, count(*) FROM dan_chieu d WHERE true{loc} GROUP BY 1"
    )))  # fmt: skip
    thieu = conn.execute(
        "SELECT den_loai, CASE WHEN den_loai = 'ten_luat' THEN 'Luật ' || den_khoa"
        " ELSE den_khoa END, count(*) FROM dan_chieu d"
        f" WHERE trang_thai = 'thieu_van_ban'{loc} GROUP BY 1, 2 ORDER BY 3 DESC, 2"
    ).fetchall()
    chua = conn.execute(
        f"SELECT den_khoa, count(*) FROM dan_chieu d WHERE trang_thai = 'chua_anh_xa'{loc}"
        " GROUP BY 1 ORDER BY 2 DESC, 1"
    ).fetchall()
    return BaoCao(tt, thieu, chua)


# dẫn chiếu thủ tục có ở gần như mọi khoản, không giúp chú tra cứu
BO_QUA_HIEN_THI = {"Xử lý vi phạm hành chính", "118/2021/NĐ-CP", "4749/VBHN-BTP"}
TOI_DA_HIEN_THI = 3


def dong_dan_chieu(
    conn: psycopg.Connection, tvpl: int, dieu: int, ht: str, khoan: int | None, thut: str = "   "
) -> list[str]:
    """Dòng "Dẫn chiếu: …" cho Điều / khoản được trích; Điều đích đã bị sửa thì kèm cảnh báo."""
    from qltt import sua_doi

    rows = conn.execute(
        """
        SELECT DISTINCT d.den_loai, d.den_khoa, d.den_tvpl_id, d.den_dieu, d.den_dieu_suffix,
            d.den_khoan, d.trang_thai, v.so_hieu
        FROM dan_chieu d JOIN chunk c ON c.id = d.tu_chunk_id
        LEFT JOIN van_ban v ON v.tvpl_id = d.den_tvpl_id
        WHERE c.tvpl_id = %s AND c.dieu_so = %s AND c.dieu_suffix = %s
            AND (%s::int IS NULL OR c.khoan_so = %s OR c.cap = 'dieu')
        """,
        [tvpl, dieu, ht or "", khoan, khoan],
    ).fetchall()
    phan, canh = [], []
    for loai, khoa, den, d, h, k, tt, so_hieu in rows:
        if khoa in BO_QUA_HIEN_THI or (so_hieu and so_hieu in BO_QUA_HIEN_THI):
            continue
        ten = f"Luật {khoa}" if loai == "ten_luat" else khoa
        vt = (f"khoản {k} " if k else "") + (f"Điều {d}{h} " if d else "")
        if tt == "ok":
            them = f" ({so_hieu})" if so_hieu and so_hieu not in ten else ""
            phan.append(f"{vt}{ten}{them}")
            if d:
                cb = sua_doi.canh_bao(conn, den, d, h, k)
                if cb:
                    canh += sua_doi.dong_canh_bao(cb, thut=thut + "  ")
        elif tt == "thieu_van_ban":
            phan.append(f"{vt}{ten} (chưa có trong kho)")
    if not phan:
        return []
    them = f" và {len(phan) - TOI_DA_HIEN_THI} chỗ khác" if len(phan) > TOI_DA_HIEN_THI else ""
    return [f"{thut}Dẫn chiếu: {'; '.join(phan[:TOI_DA_HIEN_THI])}{them}", *canh[:2]]
