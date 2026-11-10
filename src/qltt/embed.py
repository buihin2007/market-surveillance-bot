"""Tạo embedding cho chunk, qua API kiểu OpenAI (mặc định OpenRouter).

Tra embed_cache trước, chỉ gọi API cho phần thiếu. Mỗi lô ghi trong một transaction riêng (gọi
với kết nối autocommit): đứt giữa chừng thì chạy lại, làm tiếp từ chỗ dừng. Không có gì mới → 0
lời gọi API.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

import psycopg

SO_CHIEU = 1536  # text-embedding-3-small; khớp vector(1536) trong schema
LO_TOI_DA = 96  # số chunk mỗi request
KY_TU_LO_TOI_DA = 150_000  # ~ 75-150 nghìn token tiếng Việt mỗi request


@dataclass
class KetQuaEmbed:
    can: int = 0  # chunk cần vector
    tu_cache: int = 0
    tu_api: int = 0
    so_lan_goi: int = 0
    token: int = 0


def khoa(model: str, text: str) -> str:
    """Khóa cache gồm cả tên model: đổi model thì không dùng nhầm vector cũ."""
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def _lo(cac: list[tuple[int, str, str]]):
    """Chia (id, khóa, text) thành lô theo số lượng và tổng ký tự."""
    lo, ky_tu = [], 0
    for x in cac:
        if lo and (len(lo) >= LO_TOI_DA or ky_tu + len(x[2]) > KY_TU_LO_TOI_DA):
            yield lo
            lo, ky_tu = [], 0
        lo.append(x)
        ky_tu += len(x[2])
    if lo:
        yield lo


def tao_client(api_key: str, base_url: str):
    from openai import OpenAI

    # SDK tự thử lại khi 429 (giới hạn tốc độ) và lỗi 5xx, có giãn cách
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=6, timeout=120)


def goi_api(client, model: str, texts: list[str]) -> tuple[list[list[float]], int]:
    extra = None
    if "openrouter" in str(client.base_url):
        extra = {"provider": {"data_collection": "deny"}}  # chỉ qua nhà cung cấp không lưu dữ liệu
    r = client.embeddings.create(model=model, input=texts, extra_body=extra)
    vec = [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
    if len(vec) != len(texts) or any(len(v) != SO_CHIEU for v in vec):
        raise ValueError(f"API trả {len(vec)} vector, cần {len(texts)} vector {SO_CHIEU} chiều")
    return vec, (r.usage.total_tokens if r.usage else 0)


def embed_tat_ca(
    conn: psycopg.Connection,
    client,
    model: str,
    bao: Callable[[KetQuaEmbed], None] = lambda kq: None,
) -> KetQuaEmbed:
    kq = KetQuaEmbed()
    rows = conn.execute(
        "SELECT id, noi_dung_embed FROM chunk WHERE embed AND embedding IS NULL ORDER BY id"
    ).fetchall()
    cac = [(cid, khoa(model, t), t) for cid, t in rows]
    kq.can = len(cac)

    # 1. lấy từ cache
    co_san: set[str] = set()
    for i in range(0, len(cac), 1000):
        phan = cac[i : i + 1000]
        co_san |= {
            h
            for (h,) in conn.execute(
                "SELECT hash FROM embed_cache WHERE hash = ANY(%s)", [[x[1] for x in phan]]
            ).fetchall()
        }
    with conn.transaction():
        for cid, h, _ in cac:
            if h in co_san:
                conn.execute(
                    "UPDATE chunk c SET embedding = e.embedding, embed_hash = e.hash"
                    " FROM embed_cache e WHERE c.id = %s AND e.hash = %s",
                    [cid, h],
                )
                kq.tu_cache += 1

    # 2. gọi API cho phần còn thiếu; text trùng nhau chỉ gửi một lần
    thieu: dict[str, tuple[int, str, str]] = {}
    cho_khoa: dict[str, list[int]] = {}
    for cid, h, t in cac:
        if h not in co_san:
            thieu.setdefault(h, (cid, h, t))
            cho_khoa.setdefault(h, []).append(cid)
    for lo in _lo(list(thieu.values())):
        vec, token = goi_api(client, model, [x[2] for x in lo])
        with conn.transaction():
            for (_, h, _), v in zip(lo, vec, strict=True):
                s = _vec(v)
                conn.execute(
                    "INSERT INTO embed_cache (hash, model, embedding) VALUES (%s, %s, %s::vector)"
                    " ON CONFLICT (hash) DO NOTHING",
                    [h, model, s],
                )
                conn.execute(
                    "UPDATE chunk SET embedding = %s::vector, embed_hash = %s WHERE id = ANY(%s)",
                    [s, h, cho_khoa[h]],
                )
                kq.tu_api += len(cho_khoa[h])
        kq.so_lan_goi += 1
        kq.token += token
        bao(kq)
    return kq
