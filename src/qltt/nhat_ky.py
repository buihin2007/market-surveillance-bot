"""Vết câu trả lời (chat_log) và báo sai (bao_sai).

Mỗi câu trả lời ghi đủ để biết vì sao bot trả như vậy: loại câu hỏi, câu viết lại, 8 Điều ứng
viên, mã hành vi LLM chọn, chủ thể / giá trị, câu trả lời, phiên bản prompt / model, thời gian, chi
phí. Khi chú báo sai, đối chiếu căn cứ đúng với vết để biết khâu hỏng:
  Điều đúng không có trong ứng viên → tim_kiem; có mà không được chọn → chon;
  chọn đúng Điều → muc_phat (hoặc khoản / bậc sai) — người xem xác nhận.
Bot không tự sửa theo báo cáo: mọi sửa đi qua người xem + chạy lại eval.
"""

import json
import re
from dataclasses import asdict
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from qltt import danh_gia, tra_loi
from qltt.tra_loi import TraLoi

NGUYEN_NHAN = (
    "phan_loai", "tim_kiem", "chon", "muc_phat", "bien_phap", "kho_thieu", "khong_loi", "khac",
)  # fmt: skip
# Loại lỗi chú chọn khi bấm "Báo sai" (một nút, lời của chú; không bắt chú biết khâu nào hỏng).
KIEU = {
    "sai_hanh_vi": "Sai hành vi (không phải vi phạm này)",
    "sai_muc_phat": "Đúng hành vi, sai mức phạt / bậc",
    "sai_bien_phap": "Thiếu / sai xử phạt bổ sung, khắc phục",
    "van_ban_cu": "Văn bản đã hết hiệu lực / có văn bản mới",
    "khong_tim_thay": "Có quy định mà bot báo không tìm thấy",  # chỉ hiện khi bot không tìm thấy
    "sai_quy_dinh": "Trích sai / không trả lời đúng câu hỏi",  # câu trả lời quy định
    "khac": "Khác",
}


def kieu_cho(loai_ket_qua: str | None) -> list[str]:
    """Các nút hiện cho chú theo loại câu trả lời."""
    if loai_ket_qua == "khong_tim_thay":
        return ["khong_tim_thay", "van_ban_cu", "khac"]
    if loai_ket_qua == "quy_dinh":
        return ["sai_quy_dinh", "van_ban_cu", "khac"]
    return [k for k in KIEU if k not in ("khong_tim_thay", "sai_quy_dinh")]


TRANG_THAI = ("moi", "da_sua", "khong_loi", "chua_sua_duoc")


def loai_ket_qua(tl: TraLoi) -> str:
    if tl.loai in ("ngoai_pham_vi", "khac"):
        return tl.loai
    if tl.loai == "quy_dinh":
        return "quy_dinh" if tl.trich else "khong_tim_thay"
    return "tra_loi" if tl.chon else "khong_tim_thay"


def ghi(
    conn: psycopg.Connection, tl: TraLoi, c, kenh: str = "cli", nguoi: int | None = None
) -> int:
    """Ghi một câu trả lời vào chat_log; trả id (mã câu trả lời để báo sai)."""
    ket_qua = {
        "loai": tl.loai,
        "chon": [
            {
                "ma": h.uv.ma, "so_hieu": h.uv.so_hieu, "tvpl_id": h.uv.tvpl_id,
                "dieu": f"{h.uv.dieu_so}{h.uv.dieu_suffix}", "khoan": h.uv.khoan_so,
                "diem": h.uv.diem, "hanh_vi": h.uv.hanh_vi, "dieu_kien": h.dieu_kien,
            }
            for h in tl.chon
        ],
        "trich": [
            {
                "ma": x.doan.ma, "so_hieu": x.doan.so_hieu, "tvpl_id": x.doan.tvpl_id,
                "dieu": f"{x.doan.dieu_so}{x.doan.dieu_suffix}", "khoan": x.doan.khoan_so,
                "trich": x.trich, "loi_trich": x.loi_trich,
            }
            for x in tl.trich
        ],
        "chu_the": tl.chu_the, "gia_tri": tl.gia_tri, "so_luong": tl.so_luong,
        "don_vi": tl.don_vi, "van_ban": tl.van_ban,
    }  # fmt: skip
    vet = {
        "viet_lai": tl.viet_lai,
        "ung_vien_dieu": [
            {"so_hieu": h.so_hieu, "tvpl_id": h.khoa[0], "dieu": f"{h.khoa[1]}{h.khoa[2]}",
             "ten": h.ten}
            for h in tl.dieu_gan
        ],
        "so_ung_vien": tl.so_ung_vien,
        "buoc": [asdict(b) for b in tl.buoc],
        "phien_ban": {
            "llm_model": c.llm_model, "embed_model": c.embed_model,
            "viet_lai_prompt": c.viet_lai_prompt, "tat_suy_nghi": c.llm_tat_suy_nghi,
            "chon": tra_loi.PHIEN_BAN_CHON, "so_dieu": tra_loi.SO_DIEU,
        },
        "chi_phi": tl.chi_phi,
    }  # fmt: skip
    (i,) = conn.execute(
        "INSERT INTO chat_log (kenh, nguoi, cau_hoi, loai_ket_qua, ket_qua, vet, thoi_gian_ms)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        [
            kenh,
            nguoi,
            tl.cau_hoi,
            loai_ket_qua(tl),
            Jsonb(ket_qua),
            Jsonb(vet),
            int(tl.giay * 1000),
        ],
    ).fetchone()
    return i


def bao_sai(
    conn: psycopg.Connection,
    chat_log_id: int,
    ly_do: str = "",
    nguoi=None,
    kieu: str | None = None,
) -> int:
    """kieu: nút chú bấm (KIEU); ly_do: căn cứ đúng / ghi chú chú gõ thêm (có thể trống)."""
    if kieu is not None and kieu not in KIEU:
        raise ValueError(f"loại lỗi phải là: {', '.join(KIEU)}")
    co = conn.execute("SELECT 1 FROM chat_log WHERE id = %s", [chat_log_id]).fetchone()
    if not co:
        raise ValueError(f"không có câu trả lời #{chat_log_id}")
    (i,) = conn.execute(
        "INSERT INTO bao_sai (chat_log_id, nguoi, ly_do, kieu) VALUES (%s, %s, %s, %s)"
        " RETURNING id",
        [chat_log_id, nguoi, ly_do.strip() or None, kieu],
    ).fetchone()
    conn.execute("UPDATE chat_log SET bao_sai = true WHERE id = %s", [chat_log_id])
    return i


def them_ly_do(conn: psycopg.Connection, bao_sai_id: int, ly_do: str) -> None:
    """Chú gõ căn cứ đúng sau khi đã bấm loại lỗi (bước 2 của nút Báo sai)."""
    conn.execute(
        "UPDATE bao_sai SET ly_do = nullif(%s, '') WHERE id = %s", [ly_do.strip(), bao_sai_id]
    )


def tom_tat(conn: psycopg.Connection, bao_sai_id: int) -> str:
    """Tin nhắn cho ikm khi chú báo sai."""
    r = conn.execute(
        "SELECT b.chat_log_id, b.kieu, b.ly_do, l.cau_hoi, l.loai_ket_qua, l.ket_qua"
        " FROM bao_sai b JOIN chat_log l ON l.id = b.chat_log_id WHERE b.id = %s",
        [bao_sai_id],
    ).fetchone()
    if not r:
        return f"Báo sai #{bao_sai_id}: không tìm thấy"
    lid, kieu, ly_do, cau, lkq, kq = r
    chon = "; ".join(
        f"{x['so_hieu']} Đ{x['dieu']} k{x['khoan']}{(' đ' + x['diem']) if x.get('diem') else ''}"
        for x in (kq or {}).get("chon", []) + (kq or {}).get("trich", [])
    )
    g = goi_y(conn, bao_sai_id)
    return "\n".join([
        f"⚠️ Báo sai #{bao_sai_id} (câu trả lời #{lid}, {lkq})",
        f"Câu hỏi: {cau}",
        f"Bot đã chọn: {chon or '(không)'}",
        f"Chú chọn: {KIEU.get(kieu, '-') if kieu else '-'}",
        f"Chú ghi: {ly_do or '-'}",
        *([f"Gợi ý khâu hỏng: {g}"] if g else []),
        "Xem: uv run qltt bao-sai ds",
    ])  # fmt: skip


R_DIEU = re.compile(r"Điều\s+(\d+[a-zđ]?)", re.I)
R_SO_HIEU = re.compile(r"\b(\d{1,4}/(?:\d{4}/)?[A-ZĐ][A-ZĐ0-9\-]+)", re.I)


def doan_khau_hong(vet: dict, ket_qua: dict, dieu_dung: str, tvpl_id: int | None = None) -> str:
    """Căn cứ đúng (Điều; văn bản đang tra nếu biết) → khâu hỏng có khả năng nhất.

    tvpl_id: văn bản dùng để tra của căn cứ (văn bản gốc đã quy sang VBHN; số Điều giữ nguyên)."""

    def khop(x: dict) -> bool:
        return x["dieu"] == dieu_dung and (tvpl_id is None or x["tvpl_id"] == tvpl_id)

    if ket_qua.get("loai") in ("ngoai_pham_vi", "khac"):
        return "phan_loai"
    if any(khop(x) for x in ket_qua.get("chon", []) + ket_qua.get("trich", [])):
        return "muc_phat"  # chọn đúng Điều: sai ở khoản / bậc / mức → người xem xác nhận
    if any(khop(x) for x in vet.get("ung_vien_dieu", [])):
        return "chon"
    return "tim_kiem"


def goi_y(conn: psycopg.Connection, bao_sai_id: int) -> str | None:
    """Đoán khâu hỏng từ loại lỗi chú chọn + căn cứ chú gõ ("Điều N", số hiệu) + vết.

    Văn bản cũ → kho_thieu; biện pháp → bien_phap. Có căn cứ → so với vết (căn cứ thắng loại lỗi:
    chú chọn "sai mức phạt" mà căn cứ là Điều khác thì lỗi ở chọn / tìm). Không căn cứ: sai mức
    phạt → muc_phat; còn lại None (ikm xem)."""
    r = conn.execute(
        "SELECT b.ly_do, l.vet, l.ket_qua, b.kieu FROM bao_sai b"
        " JOIN chat_log l ON l.id = b.chat_log_id WHERE b.id = %s",
        [bao_sai_id],
    ).fetchone()
    if not r:
        return None
    kieu = r[3]
    if kieu == "van_ban_cu":
        return "kho_thieu"
    if kieu == "sai_bien_phap":
        return "bien_phap"
    if not r[0] or not (m := R_DIEU.search(r[0])):
        return "muc_phat" if kieu == "sai_muc_phat" else None
    tvpl = None
    if sh := R_SO_HIEU.search(r[0]):
        tvpl, _, loi = danh_gia._van_ban_tra(conn, sh.group(1))
        if loi:
            tvpl = None  # số hiệu không có trong kho: chỉ so theo số Điều
    return doan_khau_hong(r[1] or {}, r[2] or {}, m.group(1), tvpl)


def xu_ly(
    conn: psycopg.Connection,
    bao_sai_id: int,
    trang_thai: str,
    nguyen_nhan: str | None = None,
    ghi_chu: str = "",
    case_id: str | None = None,
) -> None:
    if trang_thai not in TRANG_THAI:
        raise ValueError(f"trạng thái phải là: {', '.join(TRANG_THAI)}")
    if nguyen_nhan is not None and nguyen_nhan not in NGUYEN_NHAN:
        raise ValueError(f"nguyên nhân phải là: {', '.join(NGUYEN_NHAN)}")
    n = conn.execute(
        "UPDATE bao_sai SET trang_thai = %s, nguyen_nhan = coalesce(%s, nguyen_nhan),"
        " ghi_chu_xu_ly = nullif(%s, ''), case_id = coalesce(%s, case_id), xu_ly_luc = now()"
        " WHERE id = %s",
        [trang_thai, nguyen_nhan, ghi_chu, case_id, bao_sai_id],
    ).rowcount
    if not n:
        raise ValueError(f"không có báo sai #{bao_sai_id}")


def thanh_case(
    conn: psycopg.Connection,
    bao_sai_id: int,
    file: Path,
    van_ban: str,
    dieu: str,
    khoan: list[int] = (),
    diem: list[str] = (),
) -> str:
    """Thêm câu hỏi bị báo sai vào bộ eval (kiem = nguoi_da_kiem). Cứ 4 case từ báo sai thì case
    thứ 4 vào nhóm giữ lại, để đo bản sửa có tổng quát không. Trả id case (BS-xxx)."""
    (cau,) = conn.execute(
        "SELECT l.cau_hoi FROM bao_sai b JOIN chat_log l ON l.id = b.chat_log_id WHERE b.id = %s",
        [bao_sai_id],
    ).fetchone()
    dong = [json.loads(x) for x in file.read_text(encoding="utf-8").splitlines() if x.strip()]
    da_co = [d for d in dong if d["id"].startswith("BS-")]
    ma = f"BS-{len(da_co) + 1:03d}"
    case = {
        "id": ma, "nhom": "chinh", "loai": "hanh_vi", "linh_vuc": "", "cau_hoi": cau,
        "cau_hoi_nguyen_van": cau,
        "can_cu": [{"van_ban": van_ban, "dieu": dieu, "khoan": list(khoan), "diem": list(diem)}],
        "cap_cham": "khoan" if khoan else "dieu", "kiem": "nguoi_da_kiem",
        "giu_lai": (len(da_co) + 1) % 4 == 0, "ghi_chu": f"từ báo sai #{bao_sai_id}",
    }  # fmt: skip
    with file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(case, ensure_ascii=False) + "\n")
    conn.execute("UPDATE bao_sai SET case_id = %s WHERE id = %s", [ma, bao_sai_id])
    return ma
