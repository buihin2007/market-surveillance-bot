"""Viết lại câu hỏi đời thường thành cụm hành vi theo câu chữ nghị định xử phạt (1 lần gọi LLM).

Lý do (bộ eval 10/11/2026): câu nguyên văn kiểu luật đạt recall@8 1,00, câu đời thường 0,64. Trượt
chủ yếu vì câu hỏi thiếu thuật ngữ ("logo giả" ≠ "giả mạo nhãn hiệu") hoặc tên mặt hàng át hành vi.
Tìm bằng cả câu gốc lẫn câu viết lại rồi gộp: LLM viết sai thì câu gốc vẫn còn.

Prompt không dùng ví dụ nào trong bộ eval. Các phiên bản prompt (PROMPT): v1 chỉ quy tắc; v2 thêm
định nghĩa (Điều "Giải thích từ ngữ" của các nghị định xử phạt); v3 thêm danh mục tên hành vi (tên
mọi Điều xử phạt trong kho); v4 cả hai; v5 = v2 + phân loại câu hỏi (hanh_vi / quy_dinh /
ngoai_pham_vi / khac) trong cùng lần gọi (nút hieu_cau_hoi của GĐ 2). Phần thêm lấy từ kho,
không viết tay, nên không chỉnh theo bộ eval; kho đổi thì prompt đổi, khóa cache đổi theo.
"""

import hashlib
import json
import re
from dataclasses import dataclass

import psycopg

from qltt import llm

TOI_DA = 3
PROMPT = {
    "v1": (),
    "v2": ("dinh_nghia",),
    "v3": ("danh_muc",),
    "v4": ("dinh_nghia", "danh_muc"),
    "v5": ("dinh_nghia",),  # v2 + phân loại câu hỏi trong cùng lần gọi (GĐ 2.2)
}
PHAN_LOAI = {"v5"}
LOAI = ("hanh_vi", "quy_dinh", "ngoai_pham_vi", "khac")

QUY_TAC = """\
- Dùng thuật ngữ pháp lý: "kinh doanh", "buôn bán", "hàng hóa", "giấy phép kinh doanh", "nhãn \
hàng hóa", "nguồn gốc, xuất xứ", "niêm yết", "đăng ký", "thông báo"...
- Giữ loại hàng hóa, dịch vụ khi nó có thể có quy định riêng (thuốc lá, rượu bia, xăng dầu, \
khí, thực phẩm, thuốc, mỹ phẩm, phân bón, thuốc bảo vệ thực vật, khoáng sản...).
- Bỏ chi tiết không làm đổi hành vi: tên thương hiệu, số lượng, địa điểm, thời gian cụ thể.
- Tình huống có thể là nhiều hành vi khác nhau thì viết mỗi hành vi một cụm.
- Không nêu số Điều, số hiệu văn bản, mức phạt."""

HE_THONG = (
    "Bạn hỗ trợ cán bộ Quản lý thị trường tra cứu nghị định xử phạt vi phạm hành chính.\n"
    "Người dùng mô tả một tình huống bằng lời thường. Viết lại thành 1 đến 3 cụm từ, mỗi cụm mô tả"
    " một HÀNH VI VI PHẠM theo cách diễn đạt của nghị định xử phạt Việt Nam.\n\n"
    f"Quy tắc:\n{QUY_TAC}\n\n"
    'Chỉ trả về JSON: {"hanh_vi": ["...", "..."]}'
)

# v5: phân loại + viết lại trong một lần gọi
HE_THONG_PHAN_LOAI = f"""Bạn hỗ trợ cán bộ Quản lý thị trường tra cứu văn bản pháp luật.

Bước 1. Phân loại câu của người dùng (loai):
- "hanh_vi": mô tả một tình huống, việc làm cụ thể của cá nhân, cửa hàng, doanh nghiệp (có \
hỏi "có sao không", "phạt bao nhiêu", "xử lý thế nào" hay không) → cần xác định vi phạm gì, \
phạt thế nào.
- "quy_dinh": hỏi nội dung một quy định: điều kiện, nghĩa vụ, định nghĩa, hồ sơ, thủ tục, \
điều cấm…; không mô tả một vụ việc cụ thể cần xử phạt.
- "ngoai_pham_vi": câu hỏi pháp luật mà bot không trả lời: thẩm quyền xử phạt của ai / cấp \
nào, hiệu lực hoặc lịch sử sửa đổi văn bản, trách nhiệm hình sự, lĩnh vực ngoài quản lý thị \
trường (giao thông, đất đai, hôn nhân, thuế thu nhập…).
- "khac": chào hỏi, cảm ơn, hỏi về bot, câu không rõ nghĩa.

Bước 2. Viết 1 đến 3 cụm từ để tìm trong văn bản (hanh_vi):
- loai hanh_vi: mỗi cụm mô tả một HÀNH VI VI PHẠM theo cách diễn đạt của nghị định xử phạt \
Việt Nam.
- loai quy_dinh: mỗi cụm nêu chủ đề quy định theo thuật ngữ văn bản (vd "điều kiện kinh doanh \
dịch vụ karaoke").
- loai ngoai_pham_vi, khac: danh sách rỗng.

Quy tắc viết cụm:
{QUY_TAC}

Chỉ trả về JSON: {{"loai": "...", "hanh_vi": ["..."]}}"""

VI_DU = [
    (
        "công ty rủ người tham gia mua hàng để hưởng hoa hồng theo tầng mà chưa đăng ký với Sở",
        {"hanh_vi": ["kinh doanh theo phương thức đa cấp khi chưa được cấp giấy chứng nhận "
                     "đăng ký hoạt động bán hàng đa cấp"]},
    ),
    (
        "shop online đăng ảnh kem bôi quảng cáo trắng da sau 3 ngày nhưng không đúng",
        {"hanh_vi": ["quảng cáo mỹ phẩm có nội dung không đúng tính năng, công dụng",
                     "quảng cáo gây nhầm lẫn về chất lượng, công dụng của hàng hóa"]},
    ),
]  # fmt: skip
# v5: thêm loai, một ví dụ quy_dinh, một ví dụ khac (đều không thuộc bộ eval)
VI_DU_PHAN_LOAI = [
    *((hoi, {"loai": "hanh_vi", **dap}) for hoi, dap in VI_DU),
    ("mở quán karaoke thì cần đáp ứng những gì",
     {"loai": "quy_dinh", "hanh_vi": ["điều kiện kinh doanh dịch vụ karaoke"]}),
    ("bot ơi giúp chú với", {"loai": "khac", "hanh_vi": []}),
]  # fmt: skip


def dinh_nghia(conn: psycopg.Connection) -> str:
    """Điều "Giải thích từ ngữ" của các văn bản có điều khoản xử phạt, đang dùng để tra."""
    rows = conn.execute(
        "SELECT v.so_hieu, c.noi_dung FROM chunk c JOIN van_ban v USING (tvpl_id)"
        " WHERE v.dung_de_tra AND c.cap = 'dieu' AND c.loai_chunk = 'giai_thich'"
        " AND c.tvpl_id IN (SELECT tvpl_id FROM chunk WHERE vai_tro = 'xu_phat')"
        " ORDER BY v.tvpl_id, c.dieu_so"
    ).fetchall()
    return "\n\n".join(f"[{so}]\n{' '.join(nd.split())}" for so, nd in rows)


def danh_muc(conn: psycopg.Connection) -> str:
    """Tên mọi Điều quy định hành vi vi phạm (Điều xử phạt) trong kho, theo văn bản."""
    rows = conn.execute(
        "SELECT v.so_hieu, c.dieu_ten FROM chunk c JOIN van_ban v USING (tvpl_id)"
        " WHERE v.dung_de_tra AND c.cap = 'dieu' AND c.vai_tro = 'xu_phat'"
        " AND c.loai_chunk = 'hanh_vi' AND c.dieu_ten IS NOT NULL"
        " ORDER BY v.tvpl_id, c.dieu_so, c.dieu_suffix"
    ).fetchall()
    theo_vb: dict[str, list[str]] = {}
    for so, ten in rows:
        theo_vb.setdefault(so, []).append(" ".join(ten.split()))
    return "\n".join(f"- {so}: {'; '.join(dict.fromkeys(ds))}" for so, ds in theo_vb.items())


KHOI = {
    "dinh_nghia": (
        "ĐỊNH NGHĨA trong các nghị định xử phạt (dùng để chọn đúng khái niệm):",
        dinh_nghia,
    ),
    "danh_muc": (
        "DANH MỤC tên các hành vi vi phạm có trong kho. Khi tình huống khớp, viết cụm hành vi"
        " theo đúng cách gọi trong danh mục (không ghi số hiệu văn bản):",
        danh_muc,
    ),
}


def he_thong(conn: psycopg.Connection, phien_ban: str) -> str:
    if phien_ban not in PROMPT:
        raise ValueError(f"prompt lạ: {phien_ban!r}; có: {', '.join(PROMPT)}")
    khoi = [f"{tieu_de}\n{lay(conn)}" for tieu_de, lay in (KHOI[k] for k in PROMPT[phien_ban])]
    goc = HE_THONG_PHAN_LOAI if phien_ban in PHAN_LOAI else HE_THONG
    return "\n\n".join([goc, *khoi])


@dataclass
class KetQuaVietLai:
    cau: list[str]
    tu_cache: bool
    token_vao: int = 0
    token_ra: int = 0
    chi_phi: float | None = None  # USD OpenRouter tính thật (usage.cost); None nếu API không trả
    giay: float = 0.0  # thời gian lần gọi API; 0 nếu lấy từ cache
    loai: str | None = None  # prompt có phân loại (v5); None: không phân loại hoặc LLM trả hỏng


def khoa(
    model: str, cau_hoi: str, phien_ban: str = "v1", prompt: str = "", tat_suy_nghi: bool = False
) -> str:
    # v1 giữ khóa cũ (không có prompt trong khóa); bản khác: khóa gồm băm của prompt đầy đủ,
    # vì định nghĩa / danh mục lấy từ kho nên đổi theo kho.
    nhan = (
        phien_ban
        if phien_ban == "v1"
        else f"{phien_ban}:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"
    )
    if tat_suy_nghi:
        nhan += "|khong_suy_nghi"
    return hashlib.sha256(f"viet_lai\n{nhan}\n{model}\n{cau_hoi}".encode()).hexdigest()


def doc_json(s: str) -> list[str]:
    """Lấy danh sách hành vi từ câu trả lời; chịu được ```json … ``` và chữ thừa quanh JSON."""
    m = re.search(r"\{.*\}", s or "", re.S)
    if not m:
        return []
    try:
        ds = json.loads(m.group(0), strict=False).get("hanh_vi", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    if not isinstance(ds, list):
        return []
    sach = [" ".join(str(x).split())[:300] for x in ds if isinstance(x, str) and x.strip()]
    return list(dict.fromkeys(sach))[:TOI_DA]


def doc_phan_loai(s: str) -> dict | None:
    """v5: {"loai", "hanh_vi"}. hanh_vi / quy_dinh phải có ít nhất một cụm; loại khác để rỗng."""
    m = re.search(r"\{.*\}", s or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0), strict=False)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or d.get("loai") not in LOAI:
        return None
    cau = doc_json(m.group(0))
    if d["loai"] in ("hanh_vi", "quy_dinh") and not cau:
        return None
    return {"loai": d["loai"], "hanh_vi": cau if d["loai"] in ("hanh_vi", "quy_dinh") else []}


def viet_lai(
    conn: psycopg.Connection,
    client,
    model: str,
    cau_hoi: str,
    phien_ban: str = "v1",
    tat_suy_nghi: bool = False,
) -> KetQuaVietLai:
    """tat_suy_nghi: gửi reasoning.effort = "none" (OpenRouter) cho model mặc định có suy nghĩ;
    model bắt buộc suy nghĩ sẽ báo lỗi. Prompt v5 trả thêm loai (phân loại câu hỏi)."""
    ht = HE_THONG if phien_ban == "v1" else he_thong(conn, phien_ban)
    phan_loai = phien_ban in PHAN_LOAI
    tin = [{"role": "system", "content": ht}]
    for hoi, dap in VI_DU_PHAN_LOAI if phan_loai else VI_DU:
        tin += [
            {"role": "user", "content": hoi},
            {"role": "assistant", "content": json.dumps(dap, ensure_ascii=False)},
        ]
    tin.append({"role": "user", "content": cau_hoi})

    def kiem(tho: str) -> dict | None:
        if phan_loai:
            return doc_phan_loai(tho)
        return {"hanh_vi": c} if (c := doc_json(tho)) else None

    kq = llm.goi(
        conn, client, model, tin, khoa(model, cau_hoi, phien_ban, ht, tat_suy_nghi), kiem,
        tat_suy_nghi,
    )  # fmt: skip
    d = kq.dau_ra or {}
    return KetQuaVietLai(
        d.get("hanh_vi", []), kq.tu_cache, kq.token_vao, kq.token_ra, kq.chi_phi, kq.giay,
        d.get("loai"),
    )  # fmt: skip
