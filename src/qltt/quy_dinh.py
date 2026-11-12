"""Trả lời câu hỏi quy định (GĐ 2.4) và kiểm trích dẫn (GĐ 2.5).

câu hỏi (+ câu viết lại) → tìm chunk quy phạm, gom 6 Điều → mỗi khoản (hoặc cả Điều nếu không chia
khoản) một mã Q1, Q2… → [LLM] chọn 1–3 mã, mỗi mã có thể chép một phần NGUYÊN VĂN cần nhấn → code
kiểm phần chép có đúng nguyên văn trong khoản: sai thì nhắc LLM chép lại một lần; vẫn sai thì in cả
khoản. Chữ đưa cho chú luôn là chữ của văn bản; căn cứ là mã có thật nên không bịa được.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

import psycopg

from qltt import llm
from qltt.ngu_canh import HanhVi

SO_DIEU = 6
TOI_DA_CHON = 3
DAI_TOI_DA = 1500  # ký tự mỗi đoạn đưa LLM (khoản dài hơn bị cắt khi đưa, vẫn kiểm trên bản đủ)
PHIEN_BAN = "q2"

HE_THONG = """Bạn hỗ trợ cán bộ Quản lý thị trường tra cứu quy định pháp luật.
Đầu vào: một câu hỏi và các ĐOẠN văn bản, mỗi đoạn có mã (Q1, Q2…).

Việc cần làm:
- Chọn 1 đến 3 đoạn trả lời trực tiếp câu hỏi, đoạn liên quan nhất trước.
- Với mỗi đoạn, "trich" là phần chép NGUYÊN VĂN từ đoạn đó (không sửa chữ, không tóm tắt, không \
thêm chữ) khi chỉ một phần đoạn trả lời câu hỏi; để "" nếu cần cả đoạn.
- Chỉ chọn đoạn nói đúng đối tượng câu hỏi hỏi. Đoạn về đối tượng khác chỉ gần giống (vd câu hỏi \
về hộ kinh doanh mà đoạn nói về doanh nghiệp tư nhân, câu hỏi về thực phẩm mà đoạn nói về cơ sở \
sản xuất) thì không chọn.
- Không đoạn nào trả lời được câu hỏi: "chon" để rỗng; bot sẽ báo không tìm thấy.
- Không viết thêm lời giải thích.

Chỉ trả về JSON: {"chon": [{"ma": "Q1", "trich": ""}]}"""


@dataclass
class Doan:
    ma: str
    tvpl_id: int
    so_hieu: str
    dieu_so: int
    dieu_suffix: str
    dieu_ten: str
    khoan_so: int | None  # None: cả Điều
    noi_dung: str

    @property
    def vi_tri(self) -> str:
        k = f"khoản {self.khoan_so} " if self.khoan_so is not None else ""
        return f"{k}Điều {self.dieu_so}{self.dieu_suffix}"


@dataclass
class Trich:
    doan: Doan
    trich: str | None  # phần chép đã kiểm đúng nguyên văn; None: in cả đoạn
    loi_trich: bool = False  # LLM chép sai 2 lần → in cả đoạn


def doan(conn: psycopg.Connection, dieu: list[HanhVi]) -> list[Doan]:
    ra: list[Doan] = []
    for hv in dieu:
        tvpl, so, ht = hv.khoa
        rows = conn.execute(
            "SELECT khoan_so, noi_dung FROM chunk WHERE tvpl_id = %s AND dieu_so = %s"
            " AND dieu_suffix = %s AND cap = 'khoan' ORDER BY khoan_so, khoan_suffix",
            [tvpl, so, ht],
        ).fetchall() or [(None, hv.noi_dung)]
        for k, nd in rows:
            ra.append(Doan(f"Q{len(ra) + 1}", tvpl, hv.so_hieu, so, ht, hv.ten, k, nd))
    return ra


def tin(cau_hoi: str, ds: list[Doan]) -> str:
    dong, truoc = [f"CÂU HỎI: {cau_hoi}", "", "CÁC ĐOẠN:"], None
    for d in ds:
        if (d.tvpl_id, d.dieu_so, d.dieu_suffix) != truoc:
            truoc = (d.tvpl_id, d.dieu_so, d.dieu_suffix)
            dong.append(f"[{d.so_hieu} Điều {d.dieu_so}{d.dieu_suffix}. {d.dieu_ten}]")
        nd = " ".join(d.noi_dung.split())
        dong.append(f"{d.ma}: {nd[:DAI_TOI_DA]}{'…' if len(nd) > DAI_TOI_DA else ''}")
    return "\n".join(dong)


def chuan_hoa(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"[“”\"'‘’]", "", s)
    return " ".join(s.split()).strip(" .;:…").lower()


def dung_nguyen_van(trich: str, noi_dung: str) -> bool:
    t = chuan_hoa(trich)
    return len(t) >= 8 and t in chuan_hoa(noi_dung)


def doc(s: str, ma_hop_le: set[str]) -> dict | None:
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
        ma = str((x.get("ma") if isinstance(x, dict) else x) or "").strip().upper()
        if ma not in ma_hop_le:
            return None
        if ma not in da:
            da.add(ma)
            t = x.get("trich", "") if isinstance(x, dict) else ""
            chon.append({"ma": ma, "trich": " ".join(str(t or "").split())})
    return {"chon": chon[:TOI_DA_CHON]}


def chon(
    conn: psycopg.Connection, client, model: str, tat_suy_nghi: bool, cau_hoi: str, ds: list[Doan]
) -> tuple[list[Trich], list[llm.KetQuaLLM]]:
    """LLM chọn đoạn + kiểm trích dẫn. Trả (trích, các lần gọi LLM)."""
    theo_ma = {d.ma: d for d in ds}
    noi_dung = tin(cau_hoi, ds)
    tin_nhan = [{"role": "system", "content": HE_THONG}, {"role": "user", "content": noi_dung}]
    goi = []
    for lan in range(2):
        khoa = hashlib.sha256(
            f"chon_quy_dinh\n{PHIEN_BAN}\n{model}\n{tat_suy_nghi}\n"
            f"{json.dumps(tin_nhan, ensure_ascii=False)}".encode()
        ).hexdigest()
        kq = llm.goi(
            conn, client, model, tin_nhan, khoa, lambda s: doc(s, set(theo_ma)), tat_suy_nghi
        )
        goi.append(kq)
        if kq.dau_ra is None:
            continue  # trả lời hỏng: thử lần nữa (lần hỏng không được cache)
        sai = [
            x for x in kq.dau_ra["chon"]
            if x["trich"] and not dung_nguyen_van(x["trich"], theo_ma[x["ma"]].noi_dung)
        ]  # fmt: skip
        if not sai or lan == 1:
            sai_ma = {x["ma"] for x in sai}
            return [
                Trich(theo_ma[x["ma"]], None if x["ma"] in sai_ma or not x["trich"] else x["trich"],
                      x["ma"] in sai_ma)
                for x in kq.dau_ra["chon"]
            ], goi  # fmt: skip
        # 2.5: nhắc chép lại đúng nguyên văn (tin nhắn khác → khóa cache khác)
        tin_nhan = [
            *tin_nhan,
            {"role": "assistant", "content": json.dumps(kq.dau_ra, ensure_ascii=False)},
            {
                "role": "user",
                "content": "Phần trích của "
                + ", ".join(x["ma"] for x in sai)
                + " không có nguyên văn trong đoạn. Chép lại đúng từng chữ trong đoạn, hoặc để"
                " trích rỗng. Trả lại JSON như trên.",
            },
        ]
    return [], goi
