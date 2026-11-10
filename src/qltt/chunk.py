"""Cắt văn bản đã parse thành chunk 2 cấp (Điều, khoản) + phụ lục danh mục, và phân loại.

Không đụng DB, không gọi API: nhận VanBanParse, trả danh sách Chunk.
"""

import re
from dataclasses import dataclass, field

from qltt.parse import Dieu, VanBanParse

# Luật XLVPHC Điều 4: chỉ nghị định (và pháp lệnh) quy định hành vi và mức phạt
LOAI_DUOC_QUY_DINH_PHAT = {"NGHỊ ĐỊNH", "PHÁP LỆNH"}
R_PHAT = re.compile(
    r"[Pp]hạt tiền|[Pp]hạt cảnh cáo|[Hh]ình thức xử phạt bổ sung|[Bb]iện pháp khắc phục hậu quả"
)
R_THAM_QUYEN = re.compile(r"^thẩm quyền|thẩm quyền (?:xử phạt|lập biên bản)|phân định thẩm quyền")
R_HIEU_LUC = re.compile(
    r"^(?:hiệu lực|điều khoản thi hành|trách nhiệm thi hành|tổ chức thực hiện|"
    r"trách nhiệm tổ chức thực hiện|trách nhiệm thực hiện|quy định chuyển tiếp|"
    r"điều khoản chuyển tiếp|quy định chi tiết)"
)
R_CHUNG = re.compile(r"^(?:phạm vi điều chỉnh|đối tượng áp dụng|đối tượng bị xử phạt)")
R_CHUONG_I = re.compile(r"^Chương (?:I|1)\b(?![IVX])")

TOI_DA_EMBED = 6000  # ký tự; text-embedding-3-small nhận tối đa 8191 token
TOI_DA_PHU_LUC = 3000  # phụ lục dài cắt thành nhiều chunk theo dòng


@dataclass
class Chunk:
    cap: str  # dieu | khoan | phu_luc
    duong_dan: str  # "Điều 9 khoản 1", "Phụ lục 01"
    loai_chunk: str
    vai_tro: str  # xu_phat | quy_pham
    noi_dung: str
    noi_dung_embed: str
    embed: bool
    dieu_so: int | None = None
    dieu_suffix: str = ""
    khoan_so: int | None = None
    khoan_suffix: str = ""
    phu_luc_so: str | None = None
    phan: str | None = None
    chuong: str | None = None
    muc: str | None = None
    dieu_ten: str | None = None
    cha: int | None = None  # vị trí chunk Điều trong danh sách (với khoản)
    chu_thich: list[int] = field(default_factory=list)


def ten_ngan(vb: VanBanParse, so_hieu: str) -> str:
    loai = (vb.loai_goc or "Văn bản").capitalize()
    ten = vb.ten.capitalize()[:150]
    return f"{loai} {so_hieu}" + (f": {ten}" if ten else "")


def loai_dieu(d: Dieu, co_phat: bool) -> str:
    ten = d.ten.lower()
    if R_THAM_QUYEN.search(ten) and "hành vi" not in ten:
        return "tham_quyen"
    if R_HIEU_LUC.match(ten):
        return "hieu_luc"
    if "giải thích từ ngữ" in ten:
        return "giai_thich"
    if (d.chuong and R_CHUONG_I.match(d.chuong)) or R_CHUNG.match(ten):
        return "quy_dinh_chung"
    return "hanh_vi" if co_phat else "khac"


def loai_khoan(text: str, loai_cua_dieu: str) -> str:
    dau = text[:60].lower()
    if "hình thức xử phạt bổ sung" in dau:
        return "xu_phat_bo_sung"
    if "biện pháp khắc phục hậu quả" in dau:
        return "khac_phuc"
    return loai_cua_dieu


def _cat_dong(text: str, toi_da: int) -> list[str]:
    """Cắt theo ranh giới dòng, mỗi phần không quá toi_da ký tự (trừ một dòng đơn quá dài)."""
    phan, hien_tai = [], ""
    for dong in text.split("\n"):
        if hien_tai and len(hien_tai) + len(dong) + 1 > toi_da:
            phan.append(hien_tai)
            hien_tai = dong
        else:
            hien_tai = f"{hien_tai}\n{dong}" if hien_tai else dong
    return phan + ([hien_tai] if hien_tai else [])


def cat(vb: VanBanParse, so_hieu: str) -> list[Chunk]:
    goc = ten_ngan(vb, so_hieu)
    duoc_phat = vb.loai_goc in LOAI_DUOC_QUY_DINH_PHAT
    out: list[Chunk] = []

    for d in vb.dieu:
        loai_d = loai_dieu(d, duoc_phat and bool(R_PHAT.search(d.text)))
        embed = loai_d not in ("tham_quyen", "hieu_luc") and "(được bãi bỏ)" not in d.ten
        ngu_canh = " › ".join(x for x in [goc, d.phan, d.chuong, d.muc] if x)
        tieu_de = f"Điều {d.ky_hieu}. {d.ten}".rstrip(". ")

        def vai_tro(text: str, loai: str) -> str:
            co = duoc_phat and loai not in ("tham_quyen", "hieu_luc") and R_PHAT.search(text)
            return "xu_phat" if co else "quy_pham"

        chung = dict(
            dieu_so=d.so,
            dieu_suffix=d.suffix,
            phan=d.phan,
            chuong=d.chuong,
            muc=d.muc,
            dieu_ten=d.ten,
        )
        i_dieu = len(out)
        out.append(
            Chunk(
                cap="dieu",
                duong_dan=f"Điều {d.ky_hieu}",
                loai_chunk=loai_d,
                vai_tro=vai_tro(d.text, loai_d),
                noi_dung=d.text,
                noi_dung_embed=f"{ngu_canh} › {tieu_de}\n{d.text}"[:TOI_DA_EMBED],
                embed=embed,
                chu_thich=list(d.chu_thich),
                **chung,
            )
        )
        for k in d.khoan:
            ky = f"{k.so}{k.suffix}"
            loai_k = loai_khoan(k.text, loai_d)
            out.append(
                Chunk(
                    cap="khoan",
                    duong_dan=f"Điều {d.ky_hieu} khoản {ky}",
                    loai_chunk=loai_k,
                    vai_tro=vai_tro(k.text, loai_k),
                    noi_dung=k.text,
                    noi_dung_embed=f"{ngu_canh} › {tieu_de} › khoản {ky}\n{k.text}"[:TOI_DA_EMBED],
                    embed=embed,
                    khoan_so=k.so,
                    khoan_suffix=k.suffix,
                    cha=i_dieu,
                    chu_thich=list(k.chu_thich),
                    **chung,
                )
            )

    for pl in vb.phu_luc:
        if not pl.la_danh_muc:
            continue
        ten_pl = f"Phụ lục {pl.so}".strip()
        phan = _cat_dong(pl.text, TOI_DA_PHU_LUC)
        for i, p in enumerate(phan, start=1):
            duong = ten_pl + (f" (phần {i}/{len(phan)})" if len(phan) > 1 else "")
            tieu = f"{goc} › {ten_pl}: {pl.ten}".rstrip(": ")
            out.append(
                Chunk(
                    cap="phu_luc",
                    duong_dan=duong,
                    loai_chunk="phu_luc",
                    vai_tro="quy_pham",  # không bao giờ lấy mức phạt từ phụ lục
                    noi_dung=p,
                    noi_dung_embed=f"{tieu}\n{p}"[:TOI_DA_EMBED],
                    embed=True,
                    phu_luc_so=pl.so or None,
                )
            )
    return out
