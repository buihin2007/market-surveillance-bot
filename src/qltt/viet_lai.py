"""Viết lại câu hỏi đời thường thành cụm hành vi theo câu chữ nghị định xử phạt (1 lần gọi LLM).

Lý do (bộ eval 10/11/2026): câu nguyên văn kiểu luật đạt recall@8 1,00, câu đời thường 0,64. Trượt
chủ yếu vì câu hỏi thiếu thuật ngữ ("logo giả" ≠ "giả mạo nhãn hiệu") hoặc tên mặt hàng át hành vi.
Tìm bằng cả câu gốc lẫn câu viết lại rồi gộp: LLM viết sai thì câu gốc vẫn còn.

Prompt không dùng ví dụ nào trong bộ eval. Các phiên bản prompt (PROMPT): v1 chỉ quy tắc; v2 thêm
định nghĩa (Điều "Giải thích từ ngữ" của các nghị định xử phạt); v3 thêm danh mục tên hành vi (tên
mọi Điều xử phạt trong kho); v4 cả hai. Phần thêm lấy từ kho, không viết tay, nên không chỉnh theo
bộ eval; kho đổi thì prompt đổi, khóa cache đổi theo.
"""

import hashlib
import json
import re
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

TOI_DA = 3
PROMPT = {
    "v1": (),
    "v2": ("dinh_nghia",),
    "v3": ("danh_muc",),
    "v4": ("dinh_nghia", "danh_muc"),
}

HE_THONG = """Bạn hỗ trợ cán bộ Quản lý thị trường tra cứu nghị định xử phạt vi phạm hành chính.
Người dùng mô tả một tình huống bằng lời thường. Viết lại thành 1 đến 3 cụm từ, mỗi cụm mô tả một \
HÀNH VI VI PHẠM theo cách diễn đạt của nghị định xử phạt Việt Nam.

Quy tắc:
- Dùng thuật ngữ pháp lý: "kinh doanh", "buôn bán", "hàng hóa", "giấy phép kinh doanh", \
"nhãn hàng hóa", "nguồn gốc, xuất xứ", "niêm yết", "đăng ký", "thông báo"...
- Giữ loại hàng hóa, dịch vụ khi nó có thể có quy định riêng (thuốc lá, rượu bia, xăng dầu, khí, \
thực phẩm, thuốc, mỹ phẩm, phân bón, thuốc bảo vệ thực vật, khoáng sản...).
- Bỏ chi tiết không làm đổi hành vi: tên thương hiệu, số lượng, địa điểm, thời gian cụ thể.
- Tình huống có thể là nhiều hành vi khác nhau thì viết mỗi hành vi một cụm.
- Không nêu số Điều, số hiệu văn bản, mức phạt.

Chỉ trả về JSON: {"hanh_vi": ["...", "..."]}"""

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
    return "\n\n".join([HE_THONG, *khoi])


@dataclass
class KetQuaVietLai:
    cau: list[str]
    tu_cache: bool
    token_vao: int = 0
    token_ra: int = 0


def khoa(model: str, cau_hoi: str, phien_ban: str = "v1", prompt: str = "") -> str:
    # v1 giữ khóa cũ (không có prompt trong khóa); bản khác: khóa gồm băm của prompt đầy đủ,
    # vì định nghĩa / danh mục lấy từ kho nên đổi theo kho.
    nhan = (
        phien_ban
        if phien_ban == "v1"
        else f"{phien_ban}:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"
    )
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


def viet_lai(
    conn: psycopg.Connection, client, model: str, cau_hoi: str, phien_ban: str = "v1"
) -> KetQuaVietLai:
    ht = HE_THONG if phien_ban == "v1" else he_thong(conn, phien_ban)
    h = khoa(model, cau_hoi, phien_ban, ht)
    co = conn.execute("SELECT dau_ra FROM llm_cache WHERE hash = %s", [h]).fetchone()
    if co:
        return KetQuaVietLai(co[0]["hanh_vi"], tu_cache=True)
    tin = [{"role": "system", "content": ht}]
    for hoi, dap in VI_DU:
        tin += [
            {"role": "user", "content": hoi},
            {"role": "assistant", "content": json.dumps(dap, ensure_ascii=False)},
        ]
    tin.append({"role": "user", "content": cau_hoi})
    extra = None
    if "openrouter" in str(client.base_url):
        extra = {"provider": {"data_collection": "deny"}}
    r = client.chat.completions.create(model=model, messages=tin, temperature=0, extra_body=extra)
    cau = doc_json(r.choices[0].message.content)
    u = r.usage
    kq = KetQuaVietLai(cau, False, u.prompt_tokens if u else 0, u.completion_tokens if u else 0)
    if cau:  # trả lời hỏng thì không lưu, lần sau gọi lại
        with conn.transaction():
            conn.execute(
                "INSERT INTO llm_cache (hash, model, dau_ra) VALUES (%s, %s, %s)"
                " ON CONFLICT (hash) DO NOTHING",
                [h, model, Jsonb({"hanh_vi": cau})],
            )
    return kq
