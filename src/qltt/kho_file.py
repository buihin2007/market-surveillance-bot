"""Bản sao docx trên máy: data/raw/{tvpl_id}/{md5}.docx

Drive là nguồn chuẩn; thư mục này chỉ là bản sao để parse, xóa đi tải lại được.
Đặt tên theo md5 nên file đổi trên Drive (md5 đổi) thành file mới, file cũ không bị ghi đè.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from qltt import tvpl

GDOC_MIME = "application/vnd.google-apps.document"


@dataclass
class KetQuaTai:
    moi: list[Path] = field(default_factory=list)  # vừa tải
    da_co: list[Path] = field(default_factory=list)  # đã có từ trước, không tải lại
    bo_qua: list[str] = field(default_factory=list)  # "tên file: lý do"
    loi: list[str] = field(default_factory=list)  # "tên file: lý do"


def duong_dan(goc: Path, tvpl_id: int, ten: str) -> Path:
    return goc / str(tvpl_id) / f"{ten}.docx"


def ten_ban_sao(f: dict) -> str:
    """md5 nếu Drive có. File Google Docs không có md5: dùng thời điểm sửa cuối."""
    if f.get("md5Checksum"):
        return f["md5Checksum"]
    return "gdoc_" + re.sub(r"[^0-9A-Za-z]", "-", f.get("modifiedTime", "khong-ro"))


def ghi_nguyen_tu(dich: Path, noi_dung: bytes) -> None:
    """Ghi ra file tạm rồi đổi tên: mất điện giữa chừng không để lại file dở."""
    dich.parent.mkdir(parents=True, exist_ok=True)
    tam = dich.with_name(dich.name + ".part")
    tam.write_bytes(noi_dung)
    tam.replace(dich)


def dong_bo_file(files: list[dict], goc: Path, tai: Callable[[dict], bytes]) -> KetQuaTai:
    """Tải các file chưa có bản sao. `tai(f)` trả nội dung file f (bytes)."""
    kq = KetQuaTai()
    for f in files:
        ten = f.get("name", "?")
        ma = tvpl.id_tu_ten_file(ten)
        if ma is None:
            kq.bo_qua.append(f"{ten}: tên file không có mã TVPL")
            continue
        dich = duong_dan(goc, ma, ten_ban_sao(f))
        if dich.exists():
            kq.da_co.append(dich)
            continue
        try:
            noi_dung = tai(f)
        except Exception as e:  # một file lỗi không được chặn các file khác
            kq.loi.append(f"{ten}: tải lỗi ({type(e).__name__}: {e})")
            continue
        if not noi_dung.startswith(b"PK"):  # docx là file zip
            kq.loi.append(f"{ten}: nội dung không phải docx")
            continue
        md5 = f.get("md5Checksum")
        if md5 and hashlib.md5(noi_dung).hexdigest() != md5:
            kq.loi.append(f"{ten}: md5 không khớp, file tải về bị hỏng")
            continue
        ghi_nguyen_tu(dich, noi_dung)
        kq.moi.append(dich)
    return kq
