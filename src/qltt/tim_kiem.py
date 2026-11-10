"""Tìm kiếm lai: vector (pgvector, quét hết, không index) + từ khóa (FTS Postgres), gộp bằng RRF.

Chỉ trả chunk được tìm kiếm (embed) của văn bản đang dùng để tra (dung_de_tra), lọc thêm theo Loc.
Mặc định chỉ chunk xử phạt (vai_tro = xu_phat: điều khoản gọi tên hành vi vi phạm kèm mức phạt):
đây là bước tìm hành vi ứng viên; định nghĩa và quy phạm lấy ở bước sau (ngu_canh.py).
Đo 10/11/2026 trên bộ eval: lọc xử phạt nâng recall@20 câu đời thường của nhánh từ khóa
0,41 → 0,59, của vector 0,08 → 0,46 (text-embedding-3-small).
"""

import re
from dataclasses import dataclass, field

import psycopg

from qltt import embed
from qltt.parse import chuan

SO_UNG_VIEN = 50  # mỗi nhánh lấy bấy nhiêu chunk trước khi gộp
K_RRF = 60  # hằng số RRF chuẩn: điểm = Σ trọng số / (60 + hạng)
# Chọn trên 30 câu dev (10/11/2026, bge-m3): nhánh từ khóa nặng bằng vector kéo tụt câu đời thường
# (từ khóa khớp nhầm "đại lý", "treo biển"…). 0,3 / 0,5 / 0 chênh nhau 1 câu; giữ 0,5 để nhánh từ
# khóa vẫn có tiếng khi câu hỏi dùng đúng thuật ngữ luật (câu đã được viết lại ở GĐ 2).
TRONG_SO_TU_KHOA = 0.5
NHANH = ("vector", "tu_khoa", "lai")


@dataclass(frozen=True)
class Loc:
    """Giới hạn tập chunk được tìm. Trường để trống = không lọc theo trường đó."""

    vai_tro: str | None = "xu_phat"  # "xu_phat" | "quy_pham" | None
    loai_chunk: tuple[str, ...] = ()  # chỉ các loại này, vd ("giai_thich",)
    bo_loai: tuple[str, ...] = ()  # trừ các loại này
    tvpl_ids: tuple[int, ...] = field(default=())  # chỉ trong các văn bản này

    def sql(self) -> tuple[str, list]:
        dk, ts = ["c.embed", "v.dung_de_tra"], []
        if self.vai_tro:
            dk.append("c.vai_tro = %s")
            ts.append(self.vai_tro)
        if self.loai_chunk:
            dk.append("c.loai_chunk = ANY(%s)")
            ts.append(list(self.loai_chunk))
        if self.bo_loai:
            dk.append("NOT (c.loai_chunk = ANY(%s))")
            ts.append(list(self.bo_loai))
        if self.tvpl_ids:
            dk.append("c.tvpl_id = ANY(%s)")
            ts.append(list(self.tvpl_ids))
        return " AND ".join(dk), ts


# Tìm hành vi: chunk xử phạt, trừ khoản "Hình thức xử phạt bổ sung" và "Biện pháp khắc phục hậu
# quả": chúng mô tả chế tài, không mô tả hành vi (vd "đình chỉ hoạt động" khớp nhầm câu "lén mở bán
# khi bị đình chỉ"); vẫn tới LLM qua chữ cả Điều. Trên 30 câu dev: recall@20 24/30 → 29/30 (cùng
# trọng số từ khóa 0,5); 9 câu giữ lại không đổi (4/9).
XU_PHAT = Loc(bo_loai=("xu_phat_bo_sung", "khac_phuc"))


def truy_van_tu_khoa(cau_hoi: str) -> str:
    """Câu hỏi → tsquery: các cặp âm tiết liền nhau, nối bằng HOẶC ('thuốc' <-> 'lá').

    Đo trên bộ eval (10/11/2026, chỉ từ khóa): cặp âm tiết recall@20 0,41 / 0,92 (câu đời thường /
    nguyên văn); từ đơn 0,33 / 0,62 và chậm gấp mấy lần; cặp + từ đơn kém như từ đơn.
    """
    t = re.findall(r"\w+", chuan(cau_hoi).lower())
    if len(t) < 2:
        return " | ".join(f"'{x}'" for x in t)
    return " | ".join(f"('{a}' <-> '{b}')" for a, b in zip(t, t[1:], strict=False))


def nhanh_vector(
    conn: psycopg.Connection, vec: list[float], n: int = SO_UNG_VIEN, loc: Loc = XU_PHAT
) -> list[int]:
    dk, ts = loc.sql()
    # vector_dims: bỏ qua chunk còn vector của model cũ (đang đổi model dở dang)
    return [
        r[0]
        for r in conn.execute(
            f"SELECT c.id FROM chunk c JOIN van_ban v USING (tvpl_id) WHERE {dk}"
            " AND vector_dims(c.embedding) = %s"
            " ORDER BY c.embedding <=> %s::vector, c.id LIMIT %s",
            [*ts, len(vec), embed._vec(vec), n],
        )
    ]


def nhanh_tu_khoa(
    conn: psycopg.Connection, cau_hoi: str, n: int = SO_UNG_VIEN, loc: Loc = XU_PHAT
) -> list[int]:
    q = truy_van_tu_khoa(cau_hoi)
    if not q:
        return []
    dk, ts = loc.sql()
    return [
        r[0]
        for r in conn.execute(
            f"SELECT c.id FROM chunk c JOIN van_ban v USING (tvpl_id),"
            f" to_tsquery('simple', %s) q WHERE {dk} AND c.tsv @@ q"
            " ORDER BY ts_rank_cd(c.tsv, q) DESC, c.id LIMIT %s",
            [q, *ts, n],
        )
    ]


def rrf(*danh_sach: list[int], trong_so: tuple[float, ...] = (), k: int = K_RRF) -> list[int]:
    diem: dict[int, float] = {}
    for ds, w in zip(danh_sach, trong_so or (1.0,) * len(danh_sach), strict=True):
        for hang, cid in enumerate(ds, 1):
            diem[cid] = diem.get(cid, 0.0) + w / (k + hang)
    return sorted(diem, key=lambda c: (-diem[c], c))


def tim(
    conn: psycopg.Connection, cau_hoi: str, vec: list[float] | None, loc: Loc = XU_PHAT
) -> dict[str, list[int]]:
    """Trả id chunk xếp hạng theo từng nhánh và kết quả gộp. vec = None: chỉ từ khóa."""
    v = nhanh_vector(conn, vec, loc=loc) if vec is not None else []
    t = nhanh_tu_khoa(conn, cau_hoi, loc=loc)
    lai = rrf(v, t, trong_so=(1.0, TRONG_SO_TU_KHOA)) if v else t
    return {"vector": v, "tu_khoa": t, "lai": lai}


def tim_nhieu(
    conn: psycopg.Connection,
    cau: list[str],
    vecs: list[list[float] | None],
    loc: Loc = XU_PHAT,
) -> list[int]:
    """Tìm bằng nhiều cách diễn đạt (câu gốc + câu viết lại), gộp kết quả lai bằng RRF."""
    ds = [tim(conn, q, v, loc)["lai"] for q, v in zip(cau, vecs, strict=True)]
    return ds[0] if len(ds) == 1 else rrf(*ds)


def vector_cau_hoi(
    conn: psycopg.Connection, client, model: str, cau_hoi: list[str]
) -> tuple[list[list[float]], int]:
    """Vector cho các câu hỏi, qua embed_cache (hỏi lại không tốn tiền). Trả (vector, token)."""
    khoa = [embed.khoa(model, q) for q in cau_hoi]
    co = dict(
        conn.execute(
            "SELECT hash, embedding::text FROM embed_cache WHERE hash = ANY(%s)", [khoa]
        ).fetchall()
    )
    thieu = [(h, q) for h, q in dict(zip(khoa, cau_hoi, strict=True)).items() if h not in co]
    token = 0
    if thieu:
        vecs, token = embed.goi_api(client, model, [q for _, q in thieu])
        with conn.transaction():
            for (h, _), v in zip(thieu, vecs, strict=True):
                s = embed._vec(v)
                conn.execute(
                    "INSERT INTO embed_cache (hash, model, embedding) VALUES (%s, %s, %s::vector)"
                    " ON CONFLICT (hash) DO NOTHING",
                    [h, model, s],
                )
                co[h] = s
    return [[float(x) for x in co[h].strip("[]").split(",")] for h in khoa], token


@dataclass
class DongKetQua:
    id: int
    so_hieu: str
    ngay_ban_hanh: str
    duong_dan: str
    noi_dung: str
    vi_tri: tuple[int, int, str, int | None]  # (tvpl_id, dieu_so, dieu_suffix, khoan_so)


def chi_tiet(conn: psycopg.Connection, ids: list[int]) -> list[DongKetQua]:
    rows = conn.execute(
        "SELECT c.id, v.so_hieu, v.ngay_ban_hanh::text, c.duong_dan, c.noi_dung,"
        " c.tvpl_id, c.dieu_so, c.dieu_suffix, c.khoan_so"
        " FROM chunk c JOIN van_ban v USING (tvpl_id) WHERE c.id = ANY(%s)",
        [ids],
    ).fetchall()
    theo_id = {r[0]: DongKetQua(*r[:5], vi_tri=(r[5], r[6], r[7] or "", r[8])) for r in rows}
    return [theo_id[i] for i in ids if i in theo_id]
