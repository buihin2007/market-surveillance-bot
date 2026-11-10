"""Viết lại câu hỏi đời thường thành cụm hành vi theo câu chữ nghị định xử phạt (1 lần gọi LLM).

Lý do (bộ eval 10/11/2026): câu nguyên văn kiểu luật đạt recall@8 1,00, câu đời thường 0,64. Trượt
chủ yếu vì câu hỏi thiếu thuật ngữ ("logo giả" ≠ "giả mạo nhãn hiệu") hoặc tên mặt hàng át hành vi.
Tìm bằng cả câu gốc lẫn câu viết lại rồi gộp: LLM viết sai thì câu gốc vẫn còn.

Prompt không dùng ví dụ nào trong bộ eval. Đổi prompt thì tăng PHIEN_BAN (khóa cache đổi theo).
"""

import hashlib
import json
import re
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

PHIEN_BAN = "v1"
TOI_DA = 3

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


@dataclass
class KetQuaVietLai:
    cau: list[str]
    tu_cache: bool
    token_vao: int = 0
    token_ra: int = 0


def khoa(model: str, cau_hoi: str) -> str:
    return hashlib.sha256(f"viet_lai\n{PHIEN_BAN}\n{model}\n{cau_hoi}".encode()).hexdigest()


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


def viet_lai(conn: psycopg.Connection, client, model: str, cau_hoi: str) -> KetQuaVietLai:
    h = khoa(model, cau_hoi)
    co = conn.execute("SELECT dau_ra FROM llm_cache WHERE hash = %s", [h]).fetchone()
    if co:
        return KetQuaVietLai(co[0]["hanh_vi"], tu_cache=True)
    tin = [{"role": "system", "content": HE_THONG}]
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
