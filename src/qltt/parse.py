"""Đọc file docx tải từ TVPL thành cấu trúc: đầu văn bản, Điều, khoản, phụ lục, chú thích.

Chỉ nhận cấu trúc, không phân loại nội dung (xử phạt / quy phạm làm ở bước chunk).
Quy tắc rút từ khảo sát 109 file ngày 10/11/2026 (qltt-tien-do.md).
"""

import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import docx
from docx.oxml.ns import qn

# ---------- chuẩn hóa ----------

_KY_TU = str.maketrans(
    {
        "\u00d0": "Đ",
        "\u00f0": "đ",
        "\u0420": "P",
        "\u0421": "C",
        "\xa0": " ",
        "\u200b": "",
        "\xad": "",
    }
)


def chuan(s: str) -> str:
    """NFC + sửa ký tự lạ của TVPL + gộp khoảng trắng. 16/109 file có chữ dạng tổ hợp (NFD)."""
    s = unicodedata.normalize("NFC", s).translate(_KY_TU)
    s = s.replace("’’", "”").replace("‘‘", "“")  # 90/2026: “Thực hành tốt…’’
    return re.sub(r"[ \t]+", " ", s).strip()


def chuan_so_hieu(s: str) -> str:
    """'98/2020/NĐ-CP' và '98 / 2020 / NĐ-CP' → cùng một khóa."""
    return re.sub(r"\s+", "", chuan(s)).upper()


# ---------- mẫu nhận dạng ----------

R_SO = re.compile(r"(?:Luật\s+số|Số)\s*:\s*([0-9][^\s,;]*)")
R_NGAY = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})")
R_PHAN = re.compile(r"^(?:PHẦN|Phần)\s+(?:THỨ|thứ)\s+\S+|^(?:PHẦN|Phần)\s+[IVXLC]+\b")
R_CHUONG = re.compile(r"^(?:CHƯƠNG|Chương)\s+([IVXLCDM]+|\d+)\b\.?\s*(.*)$")
R_MUC = re.compile(r"^(?:MỤC|Mục)\s+(\d+)\s*[.:]?\s*(.*)$")
# Tiêu đề Điều phải có "." hoặc ":" sau số; "Điền" là lỗi gõ có thật của TVPL
R_DIEU = re.compile(r"^Đi(?:ều|ền)\s+(\d+)([a-zđ]?)\s*[.:]\s*((?:\[\d+\])*)\s*(.*)$")
R_KHOAN = re.compile(r"^((?:\[\d+\]\s*)?)(\d+)([a-zđ]?)\.((?:\[\d+\])*)(?:\s+|$)(.*)$")
R_KHOAN_LECH = re.compile(
    r"^(\d+)\s*(?:\)|;|\s)\s*(\S.*)$"
)  # "3 Phạt", "3) Thời hạn", "12; Thay đổi"
# Câu lệnh sửa đổi ở cấp khoản/Điều của văn bản sửa đổi: dùng để thoát khối trích bị đóng sai
R_LENH = re.compile(
    r"^(?:Sửa đổi|Bổ sung|Bãi bỏ|Thay thế|Thay cụm|Thay đổi|Đính chính)"
    r"|^(?:Điều|Khoản|Điểm|Các khoản|Các điểm|Tên|Một số)\b.{0,150}"
    r"\b(?:được|đã được)\s+(?:sửa đổi|bổ sung|bãi bỏ|thay)"
)
R_DIEU_KET = re.compile(r"Sửa đổi|Bổ sung|Bãi bỏ|[Hh]iệu lực|[Tt]rách nhiệm|thi hành|Điều khoản")
LOAI_GOC = (
    "THÔNG TƯ LIÊN TỊCH",
    "NGHỊ ĐỊNH",
    "THÔNG TƯ",
    "LUẬT",
    "PHÁP LỆNH",
    "QUYẾT ĐỊNH",
    "NGHỊ QUYẾT",
)
# "sô" là lỗi gõ có thật (52/VBHN-BCT: "Nghị định sô 17/2020/NĐ-CP"); 66.18/2026/NQ-CP có dấu chấm
R_SO_TRONG_CAU = re.compile(r"s[ốô]\s+(\d+(?:\.\d+)?/\d{4}/[A-ZĐ0-9-]*[A-ZĐ0-9])")
R_HET_GIOI_THIEU = re.compile(
    r"^(?:Căn cứ|Theo đề nghị|Chính phủ ban hành|Quốc hội ban hành|Bộ trưởng)"
)
R_PHU_LUC = re.compile(r"^(?:PHỤ\s*LỤC|Phụ\s*lục)\b(.*)$")
R_ENDNOTE = re.compile(r"^\[(\d+)\]\s*(.*)$")
R_CHU_THICH = re.compile(r"\[(\d+)\]")
R_KET = re.compile(r"^(?:Nơi nhận|XÁC THỰC VĂN BẢN|FILE ĐƯỢC ĐÍNH KÈM|(?:TM|KT|Q|TL)\.\s)")
R_KEM_THEO = re.compile(r"^\((?:Ban hành )?[Kk]èm theo|^\(Ban hành kèm")
R_MAU = re.compile(
    r"mẫu|biểu|tờ khai|bảng kê|báo cáo|đơn đề nghị|biên bản|tình hình|kết quả|"
    r"bảng nội dung đánh giá|giấy chứng nhận|giấy phép",
    re.IGNORECASE,
)


# ---------- kết quả ----------


@dataclass
class Khoan:
    so: int
    suffix: str
    text: str  # cả các điểm a), b)... và nội dung sửa đổi trong ngoặc kép
    chu_thich: list[int] = field(default_factory=list)
    # VBHN: chú thích "[n]" nằm ở dòng điểm nào ("b)[91] Phạt tiền …") → n: "b"
    diem_chu_thich: dict[int, str] = field(default_factory=dict)


@dataclass
class Dieu:
    so: int
    suffix: str
    ten: str
    phan: str | None
    chuong: str | None
    muc: str | None
    dau: str  # phần trước khoản đầu tiên (Điều không chia khoản thì là toàn bộ nội dung)
    khoan: list[Khoan] = field(default_factory=list)
    chu_thich: list[int] = field(default_factory=list)  # chú thích gắn ở tiêu đề Điều

    @property
    def ky_hieu(self) -> str:
        return f"{self.so}{self.suffix}"

    @property
    def text(self) -> str:
        phan = [f"Điều {self.ky_hieu}. {self.ten}".rstrip(), self.dau]
        return "\n".join(p for p in phan + [k.text for k in self.khoan] if p)


@dataclass
class PhuLuc:
    so: str  # "I", "01", "" nếu không đánh số
    ten: str
    text: str
    la_danh_muc: bool  # False = biểu mẫu, không đưa vào tìm kiếm


@dataclass
class VanBanParse:
    so_hieu: str | None
    ngay_ky: date | None
    dieu: list[Dieu]
    phu_luc: list[PhuLuc]
    chu_thich: dict[int, str]  # VBHN: số → nội dung
    co_file_nhung: bool
    ky_tu_tong: int
    ky_tu_dieu: int
    loai_goc: str | None = (
        None  # dòng tên loại ở đầu: "NGHỊ ĐỊNH", "LUẬT"... (VBHN: loại của văn bản gốc)
    )
    ten: str = ""  # tên văn bản (dòng chữ in hoa sau tên loại)
    hop_nhat: list[str] = field(default_factory=list)  # VBHN: số hiệu văn bản gốc + các văn bản sửa


# ---------- đọc docx ----------


_W_T, _W_NGAT = qn("w:t"), {qn("w:br"), qn("w:cr"), qn("w:tab")}


def _text_p(p) -> str:
    """Chữ của một đoạn; xuống dòng mềm và tab thành dấu cách ("LUẬT<br>THỦY SẢN")."""
    return "".join(
        (x.text or "") if x.tag == _W_T else " "
        for x in p.iter()
        if x.tag == _W_T or x.tag in _W_NGAT
    )


def _footnote_ids(p) -> list[int]:
    return [int(r.get(qn("w:id"))) for r in p.iter(qn("w:footnoteReference"))]


def _phan_tu(doc) -> list[tuple[str, str, list[int]]]:
    """Phần tử body theo thứ tự: ('p'|'t', chữ đã chuẩn hóa, id footnote Word)."""
    out = []
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            out.append(("p", chuan(_text_p(el)), _footnote_ids(el)))
        elif el.tag == qn("w:tbl"):
            dong = []
            for tr in el.iter(qn("w:tr")):
                o = [
                    chuan(" ".join(_text_p(p) for p in tc.iter(qn("w:p"))))
                    for tc in tr.iter(qn("w:tc"))
                ]
                dong.append(" | ".join(x for x in o if x))
            out.append(("t", "\n".join(d for d in dong if d), []))
    return out


def _footnotes_word(path: Path) -> dict[int, str]:
    with zipfile.ZipFile(path) as z:
        if "word/footnotes.xml" not in z.namelist():
            return {}
        from lxml import etree

        goc = etree.fromstring(z.read("word/footnotes.xml"))
    out = {}
    for fn in goc.iter(qn("w:footnote")):
        so = int(fn.get(qn("w:id")))
        if so > 0:
            out[so] = chuan(" ".join(_text_p(p) for p in fn.iter(qn("w:p"))))
    return out


def _co_file_nhung(path: Path) -> bool:
    with zipfile.ZipFile(path) as z:
        return any(n.startswith("word/embeddings/") for n in z.namelist())


# ---------- máy trạng thái ----------


def _tach_chu_thich(s: str) -> tuple[str, list[int]]:
    so = [int(x) for x in R_CHU_THICH.findall(s)]
    return (re.sub(r"\s*\[\d+\]", "", s).strip(), so) if so else (s, [])


def _dau_van_ban(pt) -> tuple[str | None, date | None]:
    so = ngay = None
    for _, t, _ in pt[:40]:
        if so is None and (m := R_SO.search(t)):
            so = m.group(1).rstrip(".")
        if ngay is None and (m := R_NGAY.search(t)):
            try:
                ngay = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        if so and ngay:
            break
    return so, ngay


def _gioi_thieu(dau_dong: list[str]) -> tuple[str | None, str, list[str]]:
    """Từ các đoạn trước Điều 1: tên loại, tên văn bản, danh sách số hiệu VBHN hợp nhất."""
    loai = None
    ten: list[str] = []
    hop_nhat: list[str] = []
    for t in dau_dong:
        if loai is None:
            loai = next((x for x in LOAI_GOC if t == x or t.startswith(x + " ")), None)
            if loai and t != loai:
                ten.append(t[len(loai) :].strip())  # "LUẬT GIÁ" trên một dòng
            continue
        if R_HET_GIOI_THIEU.match(t):
            break
        if t.isupper() and not hop_nhat:
            ten.append(t)
        elif m := R_SO_TRONG_CAU.search(t):
            hop_nhat.append(m.group(1))
    return loai, " ".join(ten), hop_nhat


def _thoat_khoi(t: str, dieu: list[Dieu]) -> bool:
    """Đoạn đang bị coi là trong khối trích nhưng thực ra là câu lệnh cấp văn bản sửa đổi:
    khoản số kế tiếp chứa "như sau"/"Sửa đổi…", hoặc Điều số kế tiếp của chính văn bản."""
    if not dieu or t[0] in '“"':
        return False
    d = dieu[-1]
    if (m := R_KHOAN.match(t)) and not m.group(3):
        ke_tiep = d.khoan[-1].so + 1 if d.khoan else 1
        return int(m.group(2)) == ke_tiep and bool(R_LENH.search(m.group(5)))
    if m := R_DIEU.match(t):
        return int(m.group(1)) == d.so + 1 and bool(R_DIEU_KET.search(m.group(4)))
    return False


def parse(path: str | Path) -> VanBanParse:
    path = Path(path)
    pt = _phan_tu(docx.Document(str(path)))
    so_hieu, ngay_ky = _dau_van_ban(pt)
    fn_word = _footnotes_word(path)

    dieu: list[Dieu] = []
    phu_luc: list[PhuLuc] = []
    endnote: dict[int, list[str]] = {}
    phan = chuong = muc = None
    cho_ten_chuong = False
    trang = "dau"  # dau → than → ket → (phu_luc | endnote)
    trong_ngoac = False  # đang trong khối trích dẫn nhiều đoạn (nội dung sửa đổi)
    pl: dict | None = None
    note_hien_tai: int | None = None
    dau_dong: list[str] = []

    def them_vao_dieu(t: str, cac_fn: list[int]):
        d = dieu[-1]
        t, ct = _tach_chu_thich(t)
        ct += cac_fn
        if d.khoan:
            k = d.khoan[-1]
            k.text = f"{k.text}\n{t}" if t else k.text
            k.chu_thich += ct
            if ct and (md := re.match(r"^([a-zđ])\)", t)):
                k.diem_chu_thich |= dict.fromkeys(ct, md.group(1))
        else:
            d.dau = f"{d.dau}\n{t}".strip()
            d.chu_thich += ct

    def dong_phu_luc():
        nonlocal pl
        if pl:
            dong = pl["dong"]
            ten = " ".join(x for x in dong[:2] if x and not R_KEM_THEO.match(x))
            ten = re.sub(r"^\s*(?:SỐ|số)?\s*(?:[IVXLC]+|\d+)\b\s*", "", ten)  # bỏ số phụ lục ở đầu
            ten = re.split(r"\s*\((?:Ban hành )?[Kk]èm theo", ten)[0].strip()
            noi_dung = "\n".join(dong)
            mau = bool(R_MAU.search(ten)) or bool(
                re.search(r"^(Mẫu|MẪU)", "\n".join(dong[1:5]), re.M)
            )
            phu_luc.append(PhuLuc(pl["so"], ten, noi_dung, la_danh_muc=not mau))
        pl = None

    for kieu, t, cac_fn in pt:
        if not t:
            continue
        if trang == "dau" and kieu == "p":
            dau_dong.append(t)

        # --- chuyển trạng thái (chỉ ngoài khối ngoặc kép) ---
        if not trong_ngoac and trang != "dau":
            if (m := R_ENDNOTE.match(t)) and int(m.group(1)) == 1 and trang in ("than", "ket"):
                dong_phu_luc()
                trang = "endnote"
            elif (
                (m := R_PHU_LUC.match(t))
                and len(t) < 200
                and (trang in ("than", "ket", "phu_luc") or (trang == "endnote" and t.isupper()))
            ):
                dong_phu_luc()
                trang = "phu_luc"
                so_pl = re.match(r"\s*(?:SỐ|số)?\s*([IVXLC]+|\d+)\b", m.group(1))
                pl = {"so": so_pl.group(1) if so_pl else "", "dong": [chuan(m.group(1))]}
                continue
            elif trang == "than" and R_KET.match(t):
                trang = "ket"

        if trang == "phu_luc":
            pl["dong"].append(t)
            continue
        if trang == "endnote":
            if m := R_ENDNOTE.match(t):
                note_hien_tai = int(m.group(1))
                endnote[note_hien_tai] = [m.group(2)]
            elif note_hien_tai is not None:
                endnote[note_hien_tai].append(t)
            continue
        if trang == "ket":
            continue

        # Khối trích mở bằng đoạn bắt đầu “ mà chưa đóng trong chính đoạn đó, đóng ở đoạn kết thúc
        # bằng ” có số ” nhiều hơn “. Ngoặc kép giữa câu ("được gọi là “ABC”") không tính.
        mo, dong = t.count("“"), t.count("”")
        thang = t.count('"')  # một số văn bản dùng ngoặc thẳng: theo tính chẵn lẻ
        dong_khoi = trong_ngoac and (
            (dong > mo and re.search(r"”[\s.;,]*$", t))
            or (thang % 2 == 1 and re.search(r'"[\s.;,]*$', t))
        )
        if trong_ngoac and kieu == "p" and trang == "than" and _thoat_khoi(t, dieu):
            trong_ngoac = dong_khoi = False  # khối trước bị đóng sai, câu này là cấp văn bản
        if (
            kieu == "p"
            and not trong_ngoac
            and ((t[0] == "“" and mo > dong) or (t[0] == '"' and thang % 2 == 1))
        ):
            trong_ngoac = True

        if not trong_ngoac and kieu == "p":
            if R_PHAN.match(t):
                phan, chuong, muc = t, None, None
                continue
            if m := R_CHUONG.match(t):
                chuong, muc = f"Chương {m.group(1)}", None
                if m.group(2):
                    chuong += f". {m.group(2)}"
                cho_ten_chuong = not m.group(2)
                continue
            if cho_ten_chuong and not R_DIEU.match(t) and not R_MUC.match(t):
                chuong += f". {t}"
                cho_ten_chuong = False
                continue
            cho_ten_chuong = False
            if m := R_MUC.match(t):
                muc = f"Mục {m.group(1)}" + (f". {m.group(2)}" if m.group(2) else "")
                continue
            if m := R_DIEU.match(t):
                trang = "than"
                ten, ct = _tach_chu_thich(m.group(4))
                ct = [int(x) for x in R_CHU_THICH.findall(m.group(3))] + ct + cac_fn
                dieu.append(Dieu(int(m.group(1)), m.group(2), ten, phan, chuong, muc, "", [], ct))
                continue

        if trang == "than":
            d = dieu[-1]
            ke_tiep = d.khoan[-1].so + 1 if d.khoan else 1
            if not trong_ngoac and kieu == "p" and (m := R_KHOAN.match(t)):
                ct = [int(x) for x in R_CHU_THICH.findall(m.group(1) + m.group(4))]
                noi, ct2 = _tach_chu_thich(m.group(5))
                so_k = f"{m.group(2)}{m.group(3)}"
                d.khoan.append(
                    Khoan(int(m.group(2)), m.group(3), f"{so_k}. {noi}".strip(), ct + ct2 + cac_fn)
                )
            elif (
                not trong_ngoac
                and kieu == "p"
                and d.khoan
                and (m := R_KHOAN_LECH.match(t))
                and int(m.group(1)) == ke_tiep
            ):
                # lỗi gõ trong nguồn: "3 Phạt tiền..." (thiếu dấu chấm), "3) Thời hạn..."
                noi, ct = _tach_chu_thich(m.group(2))
                d.khoan.append(Khoan(ke_tiep, "", f"{ke_tiep}. {noi}", ct + cac_fn))
            else:
                them_vao_dieu(t, cac_fn)

        if dong_khoi:
            trong_ngoac = False

    dong_phu_luc()
    chu_thich = {k: chuan(" ".join(v)) for k, v in endnote.items()} or fn_word
    ky_tu_tong = sum(len(t) for _, t, _ in pt)
    loai_goc, ten, hop_nhat = _gioi_thieu(dau_dong)
    return VanBanParse(
        so_hieu=so_hieu,
        ngay_ky=ngay_ky,
        dieu=dieu,
        phu_luc=phu_luc,
        chu_thich=chu_thich,
        co_file_nhung=_co_file_nhung(path),
        ky_tu_tong=ky_tu_tong,
        ky_tu_dieu=sum(len(d.text) for d in dieu),
        loai_goc=loai_goc,
        ten=ten,
        hop_nhat=hop_nhat,
    )
