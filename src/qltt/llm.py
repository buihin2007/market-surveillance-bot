"""Gọi LLM qua API kiểu OpenAI (OpenRouter): cache theo khóa, đo token, chi phí thật, thời gian.

Mọi lần gọi LLM của bot đi qua goi(): cache ở bảng llm_cache (khóa do nơi gọi tính, gồm model +
phiên bản prompt + đầu vào), chỉ lưu khi đầu ra qua hàm kiểm. OpenRouter: gửi
provider.data_collection = deny, xin usage.cost (tiền thật theo provider đã chạy) và tắt suy nghĩ
nếu được yêu cầu.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

# True: không đọc cache, luôn gọi API (đo thời gian / chi phí thật ở `qltt eval tong
# --khong-cache`). Vẫn ghi cache như thường.
BO_QUA_CACHE = False


@dataclass
class KetQuaLLM:
    dau_ra: dict | None  # None: LLM trả lời không đọc được (không lưu cache)
    tu_cache: bool
    token_vao: int = 0
    token_ra: int = 0
    chi_phi: float | None = None  # USD OpenRouter tính; None nếu API không trả
    giay: float = 0.0  # thời gian gọi API; 0 nếu lấy từ cache
    tho: str = ""  # chữ LLM trả về (để gỡ lỗi khi dau_ra None)


def goi(
    conn: psycopg.Connection,
    client,
    model: str,
    tin: list[dict],
    khoa: str,
    kiem: Callable[[str], dict | None],
    tat_suy_nghi: bool = False,
) -> KetQuaLLM:
    """tin: messages kiểu OpenAI. kiem(chữ trả về) → dict để lưu, hoặc None nếu hỏng."""
    if not BO_QUA_CACHE:
        co = conn.execute("SELECT dau_ra FROM llm_cache WHERE hash = %s", [khoa]).fetchone()
        if co:
            return KetQuaLLM(co[0], tu_cache=True)
    extra = {}
    if "openrouter" in str(client.base_url):
        extra["provider"] = {"data_collection": "deny"}
        extra["usage"] = {"include": True}
        if tat_suy_nghi:
            extra["reasoning"] = {"effort": "none"}
    bat_dau = time.perf_counter()
    r = client.chat.completions.create(
        model=model, messages=tin, temperature=0, extra_body=extra or None
    )
    giay = time.perf_counter() - bat_dau
    tho = r.choices[0].message.content or ""
    dau_ra = kiem(tho)
    u = r.usage
    phi = getattr(u, "cost", None) if u else None
    kq = KetQuaLLM(
        dau_ra,
        False,
        u.prompt_tokens if u else 0,
        u.completion_tokens if u else 0,
        float(phi) if isinstance(phi, (int, float)) else None,
        giay,
        tho,
    )
    if dau_ra is not None:  # trả lời hỏng thì không lưu, lần sau gọi lại
        with conn.transaction():
            conn.execute(
                "INSERT INTO llm_cache (hash, model, dau_ra) VALUES (%s, %s, %s)"
                " ON CONFLICT (hash) DO NOTHING",
                [khoa, model, Jsonb(dau_ra)],
            )
    return kq
