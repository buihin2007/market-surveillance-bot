"""Đồng bộ Sheet + Drive → DB (GĐ 3.5–3.6). Lõi của `qltt dong-bo` và `/dong-bo` trên Telegram.

3.5 So sánh (lap_ke_hoach), mỗi văn bản rơi vào một trường hợp:
  moi            dòng sheet + file, chưa có trong DB              → nạp
  doi_file       file trên Drive đổi (md5 khác)                   → nạp lại
  khong_doi      file không đổi                                   → chỉ chép 7 cột sheet
                 (doi_sheet: cột nào đổi, để báo cáo)
  thieu_file     dòng sheet chưa có file trên Drive               → báo chú
  thua_file      file trên Drive chưa có dòng sheet               → báo chú
  go_khoi_sheet  có trong DB nhưng dòng sheet đã bị xóa           → thôi dùng để tra (giữ dữ liệu)
  + loi_sheet (dòng sai định dạng) và nham_ma (file mở ra số hiệu khác sheet: gate báo).

3.6 chay(): khóa (pg advisory lock, hai lần đồng bộ không chạy chồng) → tải file → nạp → tính lại
toàn kho (trạng thái, sửa đổi, mức phạt, biện pháp, dẫn chiếu) → embed (nếu có client) → báo cáo
→ nhat_ky_dong_bo. Chạy lần 2 không có gì đổi → "Không có gì mới."
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from qltt import kho_file, nap, tvpl

KHOA_DONG_BO = 7_042_026  # pg_advisory_lock, chung cho mọi tiến trình dùng DB này


@dataclass
class Viec:
    d: nap.DongSheet
    f: dict
    md5: str


@dataclass
class KeHoach:
    moi: list[Viec] = field(default_factory=list)
    doi_file: list[Viec] = field(default_factory=list)
    khong_doi: list[Viec] = field(default_factory=list)
    doi_sheet: list[str] = field(default_factory=list)  # "98/2020/NĐ-CP: bỏ tick còn hiệu lực"
    thieu_file: list[str] = field(default_factory=list)
    thua_file: list[str] = field(default_factory=list)
    go_khoi_sheet: list[tuple[int, str]] = field(default_factory=list)
    loi_sheet: list[str] = field(default_factory=list)


COT_SHEET = {
    "so_hieu": "số hiệu",
    "ngay_ban_hanh": "ngày ban hành",
    "loai": "loại",
    "con_hieu_luc": "ô còn hiệu lực",
    "ngay_hieu_luc": "ngày có hiệu lực",
    "ngay_het_hieu_luc": "ngày hết hiệu lực",
}


def _ngay(x) -> str:
    return f"{x:%d/%m/%Y}" if isinstance(x, date) else "trống"


def mo_ta_doi(cu: dict, moi: nap.DongSheet) -> list[str]:
    ra = []
    for k, ten in COT_SHEET.items():
        a, b = cu[k], getattr(moi, k)
        if a == b:
            continue
        if k == "con_hieu_luc":
            ra.append("tick còn hiệu lực" if b else "bỏ tick còn hiệu lực")
        elif k.startswith("ngay"):
            ra.append(f"{ten} {_ngay(a)} → {_ngay(b)}")
        else:
            ra.append(f"{ten} {a} → {b}")
    return ra


def gom_file(files: list[dict]) -> dict[int, dict]:
    """Mỗi mã TVPL một file: bản sửa gần nhất trên Drive."""
    theo_ma: dict[int, dict] = {}
    for f in sorted(files, key=lambda f: f.get("modifiedTime", "")):
        if (m := tvpl.id_tu_ten_file(f["name"])) is not None:
            theo_ma[m] = f
    return theo_ma


def lap_ke_hoach(
    conn: psycopg.Connection, dong: list[dict], files: list[dict], ngay_tu_serial,
    lam_lai: bool = False,
) -> KeHoach:  # fmt: skip
    kh = KeHoach()
    theo_ma = gom_file(files)
    cot = ["tvpl_id", "file_hash", *COT_SHEET]
    db = {
        r[0]: dict(zip(cot, r, strict=True))
        for r in conn.execute(f"SELECT {', '.join(cot)} FROM van_ban WHERE NOT go_khoi_sheet")
    }
    ma_sheet = set()
    for d in dong:
        ma = tvpl.id_tu_link(str(d.get("link_tvpl", "")))
        if ma is None:
            kh.loi_sheet.append(f"dòng {d.get('dong')}: link không có mã TVPL")
            continue
        ma_sheet.add(ma)
        ds = nap.dong_tu_sheet(d, ma, ngay_tu_serial)
        if isinstance(ds, str):
            kh.loi_sheet.append(ds)
            continue
        f = theo_ma.get(ma)
        if f is None:
            kh.thieu_file.append(f"{ds.so_hieu} (dòng {ds.dong})")
            continue
        v = Viec(ds, f, kho_file.ten_ban_sao(f))
        cu = db.get(ma)
        if cu is None:
            kh.moi.append(v)
        elif cu["file_hash"] != v.md5 or lam_lai:
            kh.doi_file.append(v)
        else:
            kh.khong_doi.append(v)
            if doi := mo_ta_doi(cu, ds):
                kh.doi_sheet.append(f"{ds.so_hieu}: {', '.join(doi)}")
    kh.thua_file = sorted(f["name"] for m, f in theo_ma.items() if m not in ma_sheet)
    kh.go_khoi_sheet = sorted(
        (m, r["so_hieu"]) for m, r in db.items() if m not in ma_sheet
    )  # fmt: skip
    return kh


@dataclass
class KetQua:
    ke_hoach: KeHoach
    da_nap: list[str] = field(default_factory=list)  # số hiệu nạp / nạp lại thành công
    so_chunk: int = 0
    truot_gate: list[str] = field(default_factory=list)
    nham_ma: list[str] = field(default_factory=list)
    loi_tai: list[str] = field(default_factory=list)
    thong_ke: dict = field(default_factory=dict)
    embed: str | None = None  # tóm tắt embed, None nếu không chạy
    lech_sheet: list[str] = field(default_factory=list)
    dang_chay: bool = False  # lần đồng bộ khác đang giữ khóa

    @property
    def co_gi_moi(self) -> bool:
        kh = self.ke_hoach
        return bool(kh.moi or kh.doi_file or kh.doi_sheet or kh.go_khoi_sheet)


def chay(
    conn: psycopg.Connection,
    dong: list[dict],
    files: list[dict],
    thu_muc_raw: Path,
    tai: Callable[[dict], bytes],
    ngay_tu_serial,
    hom_nay: date,
    embed_fn: Callable[[psycopg.Connection], str] | None = None,
    lam_lai: bool = False,
    nguoi: int | None = None,
) -> KetQua:
    """Một lần đồng bộ trọn vẹn. conn không ở chế độ autocommit; hàm tự commit từng bước."""
    if not conn.execute("SELECT pg_try_advisory_lock(%s)", [KHOA_DONG_BO]).fetchone()[0]:
        conn.rollback()
        return KetQua(KeHoach(), dang_chay=True)
    try:
        nk = conn.execute(
            "INSERT INTO nhat_ky_dong_bo (nguoi) VALUES (%s) RETURNING id", [nguoi]
        ).fetchone()[0]
        conn.commit()
        try:
            kq = _chay(
                conn, dong, files, thu_muc_raw, tai, ngay_tu_serial, hom_nay, embed_fn, lam_lai
            )
        except Exception as e:
            conn.rollback()
            conn.execute(
                "UPDATE nhat_ky_dong_bo SET ket_thuc = now(), bao_cao = %s WHERE id = %s",
                [f"Lỗi: {type(e).__name__}: {e}", nk],
            )
            conn.commit()
            raise
        conn.execute(
            "UPDATE nhat_ky_dong_bo SET ket_thuc = now(), tom_tat = %s, bao_cao = %s WHERE id = %s",
            [Jsonb(tom_tat(kq)), bao_cao(kq), nk],
        )
        conn.commit()
        return kq
    finally:
        conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", [KHOA_DONG_BO])
        conn.commit()


def _chay(conn, dong, files, thu_muc_raw, tai, ngay_tu_serial, hom_nay, embed_fn, lam_lai):
    from qltt import bien_phap, dan_chieu, muc_phat, sua_doi

    kh = lap_ke_hoach(conn, dong, files, ngay_tu_serial, lam_lai)
    kq = KetQua(kh)
    can_tai = [v.f for v in kh.moi + kh.doi_file]
    t = kho_file.dong_bo_file(can_tai, thu_muc_raw, tai)
    kq.loi_tai = t.loi
    for v in kh.khong_doi:
        nap.cap_nhat_dong(conn, v.d)
    for v in kh.moi + kh.doi_file:
        p = kho_file.duong_dan(thu_muc_raw, v.d.tvpl_id, v.md5)
        if not p.exists():
            continue  # tải lỗi, đã ghi trong loi_tai
        r = nap.nap_van_ban(conn, v.d, p, v.md5, v.f.get("id"))
        if r.loi:
            dong_loi = f"{v.d.so_hieu}: " + "; ".join(r.loi[:3])
            (kq.nham_ma if any("tải nhầm file" in x for x in r.loi) else kq.truot_gate).append(
                dong_loi
            )
        else:
            kq.da_nap.append(v.d.so_hieu)
            kq.so_chunk += r.so_chunk
    # văn bản có lại dòng sheet (từng bị gỡ) → dùng lại
    conn.execute(
        "UPDATE van_ban SET go_khoi_sheet = false WHERE tvpl_id = ANY(%s)",
        [[v.d.tvpl_id for v in kh.moi + kh.doi_file + kh.khong_doi]],
    )
    if kh.go_khoi_sheet:
        conn.execute(
            "UPDATE van_ban SET go_khoi_sheet = true, dung_de_tra = false WHERE tvpl_id = ANY(%s)",
            [[m for m, _ in kh.go_khoi_sheet]],
        )
    conn.commit()

    nap.tinh_lai(conn, hom_nay)
    sua_doi.dung_lai(conn)  # quan hệ thay thế đọc từ chunk vừa nạp → tính lại dung_de_tra
    nap.tinh_lai(conn, hom_nay)
    muc_phat.dung_lai(conn)
    bien_phap.dung_lai(conn)
    sua_doi.dung_chi_tiet(conn)
    dan_chieu.dung_lai(conn)
    conn.commit()
    kq.thong_ke = nap.thong_ke(conn)
    kq.lech_sheet = [
        f"{x.so_hieu} (bị {x.bi_thay_boi} {'thay thế' if x.loai == 'thay_the' else 'bãi bỏ'})"
        for x in sua_doi.lech_sheet(conn)
    ]
    if embed_fn is not None:
        conn.commit()
        conn.autocommit = True  # embed tự commit từng lô: đứt giữa chừng không mất phần đã làm
        try:
            kq.embed = embed_fn(conn)
        finally:
            conn.autocommit = False
    return kq


def tom_tat(kq: KetQua) -> dict:
    kh = kq.ke_hoach
    return {
        "moi": [v.d.so_hieu for v in kh.moi],
        "doi_file": [v.d.so_hieu for v in kh.doi_file],
        "khong_doi": len(kh.khong_doi),
        "doi_sheet": kh.doi_sheet,
        "thieu_file": kh.thieu_file,
        "thua_file": kh.thua_file,
        "go_khoi_sheet": [s for _, s in kh.go_khoi_sheet],
        "loi_sheet": kh.loi_sheet,
        "da_nap": kq.da_nap,
        "so_chunk": kq.so_chunk,
        "truot_gate": kq.truot_gate,
        "nham_ma": kq.nham_ma,
        "loi_tai": kq.loi_tai,
        "lech_sheet": kq.lech_sheet,
        "embed": kq.embed,
        "thong_ke": {k: v for k, v in kq.thong_ke.items() if k != "trang_thai"},
    }


def bao_cao(kq: KetQua) -> str:
    """Báo cáo cho chú (chữ thường, không Markdown, gửi được qua Telegram)."""
    if kq.dang_chay:
        return "Đang có một lần đồng bộ khác chạy. Chú đợi vài phút rồi thử lại."
    kh, dong = kq.ke_hoach, []

    def muc(ten: str, ds: list[str]):
        if ds:
            dong.append(f"{ten} ({len(ds)}):")
            dong.extend(f"  - {x}" for x in ds[:30])
            if len(ds) > 30:
                dong.append(f"  … và {len(ds) - 30} mục khác")

    if not kq.co_gi_moi:
        dong.append("Không có gì mới.")
    else:
        muc("Văn bản mới đã nạp", [v.d.so_hieu for v in kh.moi if v.d.so_hieu in kq.da_nap])
        muc("File đổi, đã nạp lại", [v.d.so_hieu for v in kh.doi_file if v.d.so_hieu in kq.da_nap])
        muc("Sửa trên sheet", kh.doi_sheet)
        muc("Dòng đã xóa khỏi sheet, thôi dùng để tra", [s for _, s in kh.go_khoi_sheet])
    # lỗi / việc cần chú làm: in mỗi lần cho tới khi hết
    muc("File mở ra không đúng số hiệu trên sheet (có thể tải nhầm file)", kq.nham_ma)
    muc("File không đọc được, chưa nạp (giữ bản cũ nếu có)", kq.truot_gate)
    muc("Tải file lỗi", kq.loi_tai)
    muc("Dòng sheet chưa có file trên Drive", kh.thieu_file)
    muc("File trên Drive chưa có dòng sheet", kh.thua_file)
    muc("Dòng sheet sai định dạng", kh.loi_sheet)
    muc("Sheet ghi còn hiệu lực nhưng đã bị văn bản mới thay (nên bỏ tick)", kq.lech_sheet)
    tk = kq.thong_ke
    if tk:
        dong.append(
            f"Kho: {tk['van_ban']} văn bản, {tk['dung_de_tra']} đang dùng để tra,"
            f" {tk['chunk_tim_kiem']} đoạn tìm kiếm."
        )
    if kq.embed:
        dong.append(kq.embed)
    return "\n".join(dong)


def ham_embed(client, model: str, gia_1m: float) -> Callable[[psycopg.Connection], str]:
    """Bước embed cho chay(): chunk mới / đổi chữ, tra cache trước."""

    def f(conn: psycopg.Connection) -> str:
        from qltt import embed

        kq = embed.embed_tat_ca(conn, client, model)
        if not kq.can:
            return "Vector: không có đoạn mới."
        return (
            f"Vector: {kq.can} đoạn mới ({kq.tu_cache} lấy lại từ cache, {kq.tu_api} gọi API,"
            f" ~{kq.token / 1e6 * gia_1m:.3f} USD)."
        )

    return f
