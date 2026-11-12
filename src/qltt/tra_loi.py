"""Trả lời một câu hỏi (GĐ 2.3: luồng hanh_vi).

câu hỏi → [LLM 1] viết lại + phân loại → tìm 8 Điều xử phạt ứng viên → liệt kê hành vi (khoản /
điểm) của các Điều đó từ bảng muc_phat, mỗi hành vi một mã H1, H2… → [LLM 2] chọn ≤ 3 mã (hoặc
không mã nào) + chủ thể, giá trị hàng, số lượng nếu câu hỏi nói rõ → code tra muc_phat, bien_phap
→ điền mẫu. LLM chỉ chọn mã nên không bịa được Điều / khoản; LLM không viết con số tiền.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

import psycopg

from qltt import (
    bien_phap,
    dan_chieu,
    llm,
    muc_phat,
    ngu_canh,
    quy_dinh,
    sua_doi,
    tim_kiem,
    viet_lai,
)
from qltt.ngu_canh import HanhVi

SO_DIEU = 8  # eval 1.6: Điều đúng trong 8 Điều đầu ở 97% câu đời thường
TOI_DA_CHON = 3
PHIEN_BAN_CHON = "c2"  # đổi khi sửa prompt chọn hành vi (khóa cache đổi theo)
CHU_THE = ("ca_nhan", "to_chuc", "khong_ro")


# ---------- hành vi ứng viên ----------


@dataclass
class UngVien:
    ma: str  # "H1"
    tvpl_id: int
    dieu_so: int
    dieu_suffix: str
    khoan_so: int
    khoan_suffix: str
    diem: str | None  # None: cả khoản (khoản không chia điểm, hoặc điểm là bậc phạt)
    so_hieu: str
    dieu_ten: str
    hanh_vi: str

    @property
    def vi_tri(self) -> str:
        d = f"điểm {self.diem} " if self.diem else ""
        return f"{d}khoản {self.khoan_so}{self.khoan_suffix} Điều {self.dieu_so}{self.dieu_suffix}"


R_DAU_PHAT = re.compile(
    r"^(?:phạt cảnh cáo hoặc )?phạt (?:tiền|cảnh cáo)[^:]*?\bđối với\s+(?:một trong các\s+)?"
    r"(?:hành vi\s+)?(?:vi phạm\s+)?(?:sau đây\s*)?:?\s*",
    re.I,
)


def gon(hanh_vi: str, toi_da: int = 350) -> str:
    """Bỏ phần "Phạt tiền từ … đối với hành vi" ở đầu: LLM chỉ cần mô tả hành vi."""
    s = " ".join(hanh_vi.split())
    s = re.sub(r"^\d+[a-zđ]?\.\s*", "", s)
    s = R_DAU_PHAT.sub("", s) or s
    return s[:toi_da]


def ung_vien(conn: psycopg.Connection, dieu: list[HanhVi]) -> list[UngVien]:
    """Hành vi (khoản / điểm) của các Điều ứng viên, theo thứ tự Điều rồi khoản."""
    ra: list[UngVien] = []
    for hv in dieu:
        tvpl, so, ht = hv.khoa
        rows = conn.execute(
            "SELECT khoan_so, khoan_suffix, diem, hanh_vi, loai, he_so, hanh_vi_tai"
            " FROM muc_phat WHERE tvpl_id = %s AND dieu_so = %s AND dieu_suffix = %s"
            " AND loai <> 'sua_doi' ORDER BY khoan_so, khoan_suffix, diem NULLS FIRST",
            [tvpl, so, ht],
        ).fetchall()
        theo_khoan: dict[tuple, list] = {}
        for k, kht, d, txt, loai, he_so, tai in rows:
            if tai:  # bậc phạt của hành vi ở khoản khác: tra() tự kéo vào
                continue
            if loai == "gap_lan" and he_so is not None and float(he_so) > 1:
                continue  # tình tiết tăng nặng: tra() trả trong tang_nang
            theo_khoan.setdefault((k, kht or ""), []).append((d, txt))
        for (k, kht), ds in theo_khoan.items():
            if len(ds) > 1 and len({t for _, t in ds}) == 1:  # dạng B: điểm là bậc phạt
                ds = [(None, ds[0][1])]
            for d, txt in ds:
                ra.append(
                    UngVien(
                        f"H{len(ra) + 1}", tvpl, so, ht, k, kht, d, hv.so_hieu, hv.ten, gon(txt)
                    )
                )
    return ra


# ---------- LLM 2: chọn hành vi ----------

HE_THONG_CHON = """Bạn hỗ trợ cán bộ Quản lý thị trường xác định hành vi vi phạm hành chính.
Đầu vào: một tình huống và danh sách HÀNH VI ỨNG VIÊN, mỗi hành vi có mã (H1, H2…) lấy từ các \
nghị định xử phạt.

Việc cần làm:
1. Chọn hành vi mà tình huống vi phạm. Chỉ chọn mã có trong danh sách.
   - Đủ tình tiết để xác định: chọn 1 mã.
   - Tình huống thiếu tình tiết để phân định giữa vài hành vi gần nhau (vd hàng giả hay hàng không \
rõ nguồn gốc): chọn tối đa 3 mã, mỗi mã ghi "dieu_kien" là tình tiết làm hành vi đó đúng (dựa vào \
định nghĩa nếu có). Không chọn thêm khi đã rõ.
   - Chỉ chọn hành vi mô tả đúng việc làm trong tình huống. Hành vi khác chỉ cùng mặt hàng, cùng \
lĩnh vực (vd tình huống "thiếu giấy chứng nhận A" mà danh sách chỉ có "thiếu quyết định B") thì \
không chọn.
   - Không hành vi nào khớp: "chon" để rỗng; bot sẽ báo không tìm thấy quy định.
2. Lấy từ câu hỏi, CHỈ khi câu hỏi nói rõ, không đoán:
   - "chu_the": "ca_nhan" (cá nhân, người bán, hộ kinh doanh: hộ kinh doanh bị phạt như cá nhân), \
"to_chuc" (công ty, doanh nghiệp, hợp tác xã, chi nhánh…), không rõ thì "khong_ro".
   - "gia_tri": trị giá hàng hóa / tang vật vi phạm, số đồng (vd "60 triệu" → 60000000), không có \
thì null.
   - "so_luong" và "don_vi": số lượng hàng vi phạm khi câu hỏi nêu (vd 30 bao, 5 kilôgam), không \
có thì null.
3. Không viết số tiền phạt, không nêu số Điều.

Chỉ trả về JSON: {"chon": [{"ma": "H1", "dieu_kien": ""}], "chu_the": "khong_ro", \
"gia_tri": null, "so_luong": null, "don_vi": null}"""


def tin_chon(cau_hoi: str, uv: list[UngVien], dinh_nghia: list[tim_kiem.DongKetQua]) -> str:
    phan = [f"TÌNH HUỐNG: {cau_hoi}"]
    if dinh_nghia:
        dn = [
            f"- {d.so_hieu} {d.duong_dan}: {' '.join(d.noi_dung.split())[:500]}" for d in dinh_nghia
        ]
        phan.append("ĐỊNH NGHĨA (trích):\n" + "\n".join(dn))
    dong, dieu_truoc = [], None
    for u in uv:
        if (u.tvpl_id, u.dieu_so, u.dieu_suffix) != dieu_truoc:
            dieu_truoc = (u.tvpl_id, u.dieu_so, u.dieu_suffix)
            dong.append(f"[{u.so_hieu} Điều {u.dieu_so}{u.dieu_suffix}. {u.dieu_ten}]")
        dong.append(f"{u.ma}: {u.hanh_vi}")
    phan.append("HÀNH VI ỨNG VIÊN:\n" + "\n".join(dong))
    return "\n\n".join(phan)


def _so(x) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x) if x > 0 else None
    try:
        v = float(str(x).replace(".", "").replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None


def doc_chon(s: str, ma_hop_le: set[str]) -> dict | None:
    m = re.search(r"\{.*\}", s or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0), strict=False)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("chon"), list):
        return None
    chon, da = [], set()
    for x in d["chon"]:
        ma = (x.get("ma") if isinstance(x, dict) else x) or ""
        ma = str(ma).strip().upper()
        if ma not in ma_hop_le:
            return None  # mã không có trong danh sách: coi như hỏng, gọi lại
        if ma not in da:
            da.add(ma)
            dk = x.get("dieu_kien", "") if isinstance(x, dict) else ""
            chon.append({"ma": ma, "dieu_kien": " ".join(str(dk or "").split())[:300]})
    chu_the = d.get("chu_the") if d.get("chu_the") in CHU_THE else "khong_ro"
    don_vi = d.get("don_vi")
    return {
        "chon": chon[:TOI_DA_CHON],
        "chu_the": chu_the,
        "gia_tri": _so(d.get("gia_tri")),
        "so_luong": _so(d.get("so_luong")),
        "don_vi": str(don_vi).strip().lower()
        if isinstance(don_vi, str) and don_vi.strip()
        else None,
    }


# ---------- câu trả lời ----------


@dataclass
class HanhViChon:
    uv: UngVien
    dieu_kien: str
    muc: muc_phat.KetQuaTra
    bien_phap: list[bien_phap.KetQuaBienPhap]


@dataclass
class Buoc:
    ten: str
    giay: float
    chi_phi: float | None = None
    tu_cache: bool = False
    token_vao: int = 0  # 0 khi lấy từ cache
    token_ra: int = 0


def buoc_llm(ten: str, giay: float, goi: list) -> "Buoc":
    """Gộp các lần gọi LLM của một bước (kể cả lần gọi lại) thành một Buoc."""
    return Buoc(
        ten, giay, sum(g.chi_phi or 0 for g in goi), all(g.tu_cache for g in goi),
        sum(g.token_vao for g in goi), sum(g.token_ra for g in goi),
    )  # fmt: skip


@dataclass
class TraLoi:
    cau_hoi: str
    loai: str
    viet_lai: list[str] = field(default_factory=list)
    chon: list[HanhViChon] = field(default_factory=list)
    trich: list[quy_dinh.Trich] = field(default_factory=list)  # câu hỏi quy_dinh
    dieu_gan: list[HanhVi] = field(default_factory=list)  # Điều ứng viên (để báo khi không có)
    so_ung_vien: int = 0
    chu_the: str = "khong_ro"
    gia_tri: float | None = None
    so_luong: float | None = None
    don_vi: str | None = None
    buoc: list[Buoc] = field(default_factory=list)
    van_ban: str = ""

    @property
    def giay(self) -> float:
        return sum(b.giay for b in self.buoc)

    @property
    def chi_phi(self) -> float:
        return sum(b.chi_phi or 0 for b in self.buoc)


def kiem_cau_hinh(c) -> None:
    if c.viet_lai_prompt not in viet_lai.PHAN_LOAI:
        raise ValueError(
            f"VIET_LAI_PROMPT={c.viet_lai_prompt} không phân loại câu hỏi; bot cần prompt có phân"
            f" loại ({', '.join(sorted(viet_lai.PHAN_LOAI))}). Sửa .env: VIET_LAI_PROMPT=v5"
            " (hoặc xóa dòng đó)."
        )


# ---------- các bước (do_thi.py nối thành đồ thị LangGraph) ----------


def b_hieu_cau_hoi(conn: psycopg.Connection, client, c, cau_hoi: str) -> TraLoi:
    """LLM 1: phân loại + viết lại."""
    t = time.perf_counter()
    vl = viet_lai.viet_lai(
        conn, client, c.llm_model, cau_hoi, c.viet_lai_prompt, c.llm_tat_suy_nghi
    )
    tl = TraLoi(cau_hoi, vl.loai or "hanh_vi", vl.cau)
    tl.buoc.append(buoc_llm("hiểu câu hỏi", time.perf_counter() - t, [vl]))
    return tl


def _vector(conn: psycopg.Connection, client, c, tl: TraLoi) -> list[list[float]]:
    vecs, _ = tim_kiem.vector_cau_hoi(conn, client, c.embed_model, [tl.cau_hoi, *tl.viet_lai])
    return vecs


def b_tim_hanh_vi(
    conn: psycopg.Connection, client, c, tl: TraLoi
) -> tuple[list[UngVien], list[tim_kiem.DongKetQua]]:
    """8 Điều xử phạt ứng viên → hành vi gắn mã. Trả (ứng viên, định nghĩa)."""
    t = time.perf_counter()
    vecs = _vector(conn, client, c, tl)
    nc = ngu_canh.lap(
        conn, tl.cau_hoi, vecs[0], list(zip(tl.viet_lai, vecs[1:], strict=True)), SO_DIEU, False
    )
    tl.dieu_gan = nc.hanh_vi
    uv = ung_vien(conn, nc.hanh_vi)
    tl.so_ung_vien = len(uv)
    tl.buoc.append(Buoc("tìm hành vi ứng viên", time.perf_counter() - t))
    return uv, nc.dinh_nghia


def b_chon_hanh_vi(
    conn: psycopg.Connection,
    client,
    c,
    tl: TraLoi,
    uv: list[UngVien],
    dinh_nghia: list[tim_kiem.DongKetQua],
) -> dict:
    """LLM 2: chọn ≤ 3 mã + chủ thể / giá trị / số lượng. Trả lời hỏng thì gọi lại một lần."""
    t = time.perf_counter()
    noi_dung = tin_chon(tl.cau_hoi, uv, dinh_nghia)
    tin = [
        {"role": "system", "content": HE_THONG_CHON},
        {"role": "user", "content": noi_dung},
    ]
    khoa = hashlib.sha256(
        f"chon_hanh_vi\n{PHIEN_BAN_CHON}\n{c.llm_model}\n{c.llm_tat_suy_nghi}\n"
        f"{HE_THONG_CHON}\n{noi_dung}".encode()
    ).hexdigest()
    ma = {u.ma for u in uv}
    goi = [
        llm.goi(conn, client, c.llm_model, tin, khoa, lambda s: doc_chon(s, ma), c.llm_tat_suy_nghi)
    ]
    if goi[0].dau_ra is None:  # lần hỏng không được cache nên gọi lại là gọi mới
        goi.append(
            llm.goi(
                conn, client, c.llm_model, tin, khoa, lambda s: doc_chon(s, ma),
                c.llm_tat_suy_nghi,
            )
        )  # fmt: skip
    kq = goi[-1]
    tl.buoc.append(buoc_llm("chọn hành vi", time.perf_counter() - t, goi))
    d = kq.dau_ra or {"chon": [], "chu_the": "khong_ro"}
    tl.chu_the = d.get("chu_the", "khong_ro")
    tl.gia_tri, tl.so_luong, tl.don_vi = d.get("gia_tri"), d.get("so_luong"), d.get("don_vi")
    return d


def b_tra_muc_phat(conn: psycopg.Connection, tl: TraLoi, uv: list[UngVien], d: dict) -> None:
    """Code tra muc_phat + bien_phap theo mã LLM chọn."""
    t = time.perf_counter()
    ma = {u.ma: u for u in uv}
    for x in d["chon"]:
        u = ma[x["ma"]]
        if tl.gia_tri is not None:
            gt, dv = tl.gia_tri, "đồng"
        elif tl.so_luong is not None and tl.don_vi:
            gt, dv = tl.so_luong, tl.don_vi
        else:
            gt, dv = None, "đồng"
        muc = muc_phat.tra(conn, u.tvpl_id, u.dieu_so, u.dieu_suffix, u.khoan_so, u.diem, gt, dv)
        bp = bien_phap.tra_bien_phap(
            conn, u.tvpl_id, u.dieu_so, u.dieu_suffix, u.khoan_so, u.diem, u.khoan_suffix
        )
        tl.chon.append(HanhViChon(u, x["dieu_kien"], muc, bp))
    tl.buoc.append(Buoc("tra mức phạt", time.perf_counter() - t))


def b_tim_quy_dinh(conn: psycopg.Connection, client, c, tl: TraLoi) -> list[quy_dinh.Doan]:
    t = time.perf_counter()
    vecs = _vector(conn, client, c, tl)
    cau = [tl.cau_hoi, *tl.viet_lai]
    ids = tim_kiem.tim_nhieu(conn, cau, vecs, tim_kiem.Loc(vai_tro="quy_pham"))
    tl.dieu_gan = ngu_canh.hanh_vi(conn, ids, quy_dinh.SO_DIEU)
    ds = quy_dinh.doan(conn, tl.dieu_gan)
    tl.so_ung_vien = len(ds)
    tl.buoc.append(Buoc("tìm quy định", time.perf_counter() - t))
    return ds


def b_chon_trich(conn: psycopg.Connection, client, c, tl: TraLoi, ds: list[quy_dinh.Doan]) -> None:
    """LLM chọn đoạn + kiểm trích dẫn (quy_dinh.chon)."""
    t = time.perf_counter()
    tl.trich, goi = quy_dinh.chon(conn, client, c.llm_model, c.llm_tat_suy_nghi, tl.cau_hoi, ds)
    tl.buoc.append(buoc_llm("chọn đoạn trích", time.perf_counter() - t, goi))


def hoi(conn: psycopg.Connection, client, c, cau_hoi: str) -> TraLoi:
    """Trả lời một câu hỏi qua đồ thị LangGraph (do_thi.py).

    c: cấu hình (llm_model, embed_model, viet_lai_prompt, llm_tat_suy_nghi)."""
    from qltt import do_thi

    return do_thi.chay(conn, client, c, cau_hoi)


# ---------- định dạng (chữ thường; Telegram định dạng sau ở GĐ 4) ----------


def tien(x: int | None) -> str:
    return "?" if x is None else f"{x:,}".replace(",", ".")


def khung(a: int | None, b: int | None) -> str:
    if a is None:
        return f"đến {tien(b)} đồng"
    return f"{tien(a)} – {tien(b)} đồng"


def ten_van_ban(conn: psycopg.Connection, tvpl_id: int, so_hieu: str) -> str:
    goc = conn.execute(
        "SELECT den_so_hieu FROM quan_he_van_ban WHERE tu = %s AND loai = 'hop_nhat' LIMIT 1",
        [tvpl_id],
    ).fetchone()
    return f"{so_hieu} (hợp nhất {goc[0]})" if goc else so_hieu


R_TINH_TIET = re.compile(r"\b(?:trong trường hợp|trường hợp|đối với)\b\s*(?P<t>.+)$", re.I)


def tinh_tiet(hanh_vi: str) -> str:
    """'Phạt tiền gấp hai lần … trong trường hợp hàng là thực phẩm' → phần tình tiết."""
    s = " ".join(hanh_vi.split())
    m = R_TINH_TIET.search(s)
    t = m.group("t") if m else s
    t = re.split(r"\s+(?:tương ứng|quy định tại)\b", t)[0]
    return t.strip(" .;:")[:200]


def dong_muc(m: muc_phat.MucPhat, chu_the: str, cua: str | None) -> str:
    if m.loai == "canh_cao":
        return "Phạt cảnh cáo"
    if m.loai == "khong_tach":
        return "Mức phạt: xem nguyên văn bên dưới"
    truoc = "Cảnh cáo hoặc phạt tiền " if m.loai == "canh_cao_hoac_tien" else ""
    if m.loai == "gap_lan" and m.tu is None:
        return f"Phạt tiền {m.ghi_chu}"
    if m.loai == "lan_gia_tri" and m.tu is None:
        return f"{truoc}Phạt tiền {m.ghi_chu} hàng hóa vi phạm"
    if m.ca_nhan is None:  # văn bản không nói mức là của ai
        return f"{truoc}{khung(m.tu, m.den)} (văn bản không nói rõ mức này cho cá nhân hay tổ chức)"
    cn, tc = khung(*m.ca_nhan), khung(*m.to_chuc)
    if chu_the == "ca_nhan":
        return f"{truoc}Cá nhân: {cn}"
    if chu_the == "to_chuc":
        return f"{truoc}Tổ chức: {tc}"
    return f"{truoc}Cá nhân: {cn}; tổ chức: {tc}"


def canh_bao_mot_lan(
    conn: psycopg.Connection,
    da: dict,
    muc: int,
    tvpl: int,
    dieu: int,
    ht: str,
    khoan: int | None,
    trich: str,
) -> list[str]:
    """Cảnh báo sửa đổi cho một mục; mục sau có đúng cảnh báo như mục trước (3 khoản cùng Điều 24)
    → một dòng "như mục i" thay vì lặp lại."""
    cb = sua_doi.canh_bao(conn, tvpl, dieu, ht, khoan)
    if not cb:
        return []
    k = sua_doi.khoa_canh_bao(cb)
    if k in da:
        return [f"   ⚠ Cùng cảnh báo sửa đổi như mục {da[k]}."]
    da[k] = muc
    return sua_doi.dong_canh_bao(cb, trich=trich)


def dinh_dang(conn: psycopg.Connection, tl: TraLoi) -> str:
    if tl.loai == "khac":
        return (
            'Chú gõ tình huống vi phạm (vd "tạp hóa bán thuốc lá ngoại không có hóa đơn") để tra'
            " hành vi và mức phạt, hoặc hỏi nội dung một quy định."
        )
    if tl.loai == "ngoai_pham_vi":
        return (
            "Câu hỏi này ngoài phạm vi tra cứu của bot (bot không trả lời về thẩm quyền xử phạt,"
            " hiệu lực văn bản, trách nhiệm hình sự hay lĩnh vực ngoài quản lý thị trường)."
        )
    if tl.loai == "quy_dinh":
        if not tl.trich:
            gan = "; ".join(f"{h.so_hieu} {h.dieu}. {h.ten}" for h in tl.dieu_gan[:3])
            return "Không tìm thấy quy định trả lời câu hỏi trong kho văn bản." + (
                f"\nCác Điều gần nhất: {gan}" if gan else ""
            )
        phan = ["Quy định liên quan (trích nguyên văn):"]
        da_canh_bao: dict = {}
        for i, x in enumerate(tl.trich, 1):
            d = x.doan
            vb = ten_van_ban(conn, d.tvpl_id, d.so_hieu)
            phan.append(f"{i}. {d.vi_tri} {vb} – {d.dieu_ten}")
            phan += canh_bao_mot_lan(
                conn, da_canh_bao, i, d.tvpl_id, d.dieu_so, d.dieu_suffix, d.khoan_so, d.noi_dung
            )
            phan += dan_chieu.dong_dan_chieu(conn, d.tvpl_id, d.dieu_so, d.dieu_suffix, d.khoan_so)
            if x.trich:
                phan.append(f"   «…{x.trich}…»")
            else:
                nd = " ".join(d.noi_dung.split())
                phan.append(f"   «{nd[:2000]}{'…' if len(nd) > 2000 else ''}»")
                if x.loi_trich:
                    phan.append("   (không trích được câu cụ thể nên in cả đoạn)")
        return "\n".join(phan)
    if not tl.chon:
        gan = "; ".join(f"{h.so_hieu} {h.dieu}. {h.ten}" for h in tl.dieu_gan[:3])
        return "Không tìm thấy quy định xử phạt khớp tình huống trong kho văn bản." + (
            f"\nCác Điều gần nhất: {gan}" if gan else ""
        )
    phan = []
    da_canh_bao = {}
    if len(tl.chon) > 1:
        phan.append(f"Tình huống có thể thuộc {len(tl.chon)} hành vi; tùy tình tiết thực tế:")
    for i, h in enumerate(tl.chon, 1):
        u, m = h.uv, h.muc
        dong = [f"{i}. {u.hanh_vi}" if len(tl.chon) > 1 else f"Hành vi: {u.hanh_vi}"]
        if h.dieu_kien and len(tl.chon) > 1:
            dong.append(f"   Khi: {h.dieu_kien}")
        vb = ten_van_ban(conn, u.tvpl_id, u.so_hieu)
        dong.append(f"   Căn cứ: {u.vi_tri} {vb}")
        dong += canh_bao_mot_lan(
            conn, da_canh_bao, i, u.tvpl_id, u.dieu_so, u.dieu_suffix, u.khoan_so, u.hanh_vi
        )
        dong += dan_chieu.dong_dan_chieu(conn, u.tvpl_id, u.dieu_so, u.dieu_suffix, u.khoan_so)
        nhieu_bac = len(m.muc) > 1
        if nhieu_bac and not m.da_loc_gia_tri:
            dong.append("   Mức phạt (theo từng trường hợp):")
        for x in m.muc:
            nhan = f"{x.dieu_kien}: " if nhieu_bac and x.dieu_kien else ""
            # một bậc đã lọc theo giá trị vẫn ghi điểm để chú đối chiếu
            vt = (
                f" [{'điểm ' + x.diem + ' ' if x.diem else ''}khoản {x.khoan}]"
                if nhieu_bac or (x.diem and x.diem != u.diem)
                else ""
            )
            dau = "     - " if nhieu_bac else "   Mức phạt: "
            dong.append(f"{dau}{nhan}{dong_muc(x, tl.chu_the, m.mucphat_cua)}{vt}")
        if m.da_loc_gia_tri:
            dong.append("   (đã chọn bậc theo giá trị / số lượng nêu trong câu hỏi)")
        for x in m.tang_nang:
            dong.append(
                f"   Nếu {tinh_tiet(x.dieu_kien or '')}: {dong_muc(x, tl.chu_the, m.mucphat_cua)}"
                f" [{'điểm ' + x.diem + ' ' if x.diem else ''}khoản {x.khoan}]"
            )
        bs = [b for b in h.bien_phap if b.loai == "bo_sung"]
        kp = [b for b in h.bien_phap if b.loai == "khac_phuc"]
        for ten, ds in (("Xử phạt bổ sung", bs), ("Biện pháp khắc phục", kp)):
            if ds:
                dong.append(f"   {ten}:")
                for b in ds:
                    note = "" if b.chac else f" ({b.ghi_chu or 'cần xem nguyên văn'})"
                    vt = f"điểm {b.diem} khoản {b.khoan_so}" if b.diem else f"khoản {b.khoan_so}"
                    nd = b.noi_dung.rstrip(' ”".')  # bỏ ngoặc đóng của khối sửa đổi trong VBHN
                    dong.append(f"     - {nd} [{vt}]{note}")
        for k, d, nd in m.nguyen_van:
            if (k, d) == (u.khoan_so, u.diem):
                continue
            dong.append(f"   Lưu ý (nguyên văn khoản {k}): {' '.join(nd.split())}")
        if any(x.loai == "khong_tach" for x in m.muc):
            nd = conn.execute(
                "SELECT c.noi_dung FROM chunk c WHERE c.id = %s", [m.muc[0].chunk_id]
            ).fetchone()
            if nd:
                dong.append(f"   Nguyên văn: {' '.join(nd[0].split())}")
        phan.append("\n".join(dong))
    if tl.chu_the == "khong_ro" and any(x.ca_nhan for h in tl.chon for x in h.muc.muc):
        phan.append("(Câu hỏi không nói rõ cá nhân hay tổ chức nên nêu cả hai mức.)")
    return "\n\n".join(phan)
