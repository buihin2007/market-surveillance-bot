"""Đọc Google Sheet và liệt kê thư mục Drive bằng service account (chỉ quyền đọc)."""

import io
import unicodedata
from datetime import date, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from qltt.config import cau_hinh
from qltt.kho_file import GDOC_MIME

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)

# Tiêu đề trên sheet (đã bỏ dấu, chữ thường) → khóa nội bộ. Bot đọc theo tên, không theo vị trí.
COT = {
    "so hieu": "so_hieu",
    "ngay ban hanh": "ngay_ban_hanh",
    "loai van ban": "loai",
    "con hieu luc": "con_hieu_luc",
    "ngay co hieu luc": "ngay_hieu_luc",
    "hieu luc den": "ngay_het_hieu_luc",
    "link tvpl": "link_tvpl",
}


class LoiTieuDe(ValueError):
    """Dòng tiêu đề của sheet thiếu cột hoặc có cột lạ: dừng, không đoán."""


def bo_dau(s: str) -> str:
    """ "Hiệu lực  đến" → "hieu luc den" """
    s = unicodedata.normalize("NFD", str(s).replace("đ", "d").replace("Đ", "D"))
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").lower().split())


def ngay_tu_serial(n: float) -> date:
    """Sheets trả ô ngày dưới dạng số ngày tính từ 30/12/1899."""
    return date(1899, 12, 30) + timedelta(days=int(n))


def dong_tu_values(values: list[list]) -> list[dict]:
    """Bảng thô của Sheets API → danh sách dòng dạng dict, kèm "dong" là số dòng trên sheet."""
    if not values:
        raise LoiTieuDe("Tab trống, không có dòng tiêu đề.")
    tieu_de = [bo_dau(o) for o in values[0]]
    la = [str(values[0][i]) for i, t in enumerate(tieu_de) if t and t not in COT]
    thieu = [t for t in COT if t not in tieu_de]
    if la or thieu:
        raise LoiTieuDe(f"Tiêu đề lạ: {la or 'không'}; thiếu: {thieu or 'không'}.")
    khoa = [COT.get(t) for t in tieu_de]
    dong = []
    for so, o in enumerate(values[1:], start=2):
        d = {k: (o[i] if i < len(o) else "") for i, k in enumerate(khoa) if k}
        # dòng trống của bảng vẫn có ô tick FALSE: coi là trống nếu mọi ô khác đều trống
        if any(v != "" for k, v in d.items() if k != "con_hieu_luc"):
            dong.append({"dong": so, **d})
    return dong


def _creds():
    return service_account.Credentials.from_service_account_file(
        str(cau_hinh().google_sa_key), scopes=SCOPES
    )


def email_service_account() -> str:
    return _creds().service_account_email


def doc_sheet() -> list[dict]:
    """Đọc tab văn bản. 1 request."""
    c = cau_hinh()
    sheets = build("sheets", "v4", credentials=_creds(), cache_discovery=False)
    kq = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=c.sheet_id,
            range=f"'{c.sheet_tab}'!A1:G",
            valueRenderOption="UNFORMATTED_VALUE",  # ô tick → True/False
            dateTimeRenderOption="SERIAL_NUMBER",  # ô ngày → số
        )
        .execute()
    )
    return dong_tu_values(kq.get("values", []))


def liet_ke_file() -> list[dict]:
    """Liệt kê file trong thư mục "Văn bản" (không tải nội dung)."""
    c = cau_hinh()
    drive = build("drive", "v3", credentials=_creds(), cache_discovery=False)
    files, trang = [], None
    while True:
        kq = (
            drive.files()
            .list(
                q=f"'{c.folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime, size)",
                pageSize=1000,
                pageToken=trang,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files += kq.get("files", [])
        trang = kq.get("nextPageToken")
        if not trang:
            return files


def tai_noi_dung(f: dict) -> bytes:
    """Tải nội dung một file Drive. File đã bị đổi sang Google Docs thì xuất lại ra docx."""
    drive = build("drive", "v3", credentials=_creds(), cache_discovery=False)
    if f.get("mimeType") == GDOC_MIME:
        yeu_cau = drive.files().export_media(fileId=f["id"], mimeType=DOCX_MIME)
    else:
        yeu_cau = drive.files().get_media(fileId=f["id"], supportsAllDrives=True)
    buf = io.BytesIO()
    tai = MediaIoBaseDownload(buf, yeu_cau)
    xong = False
    while not xong:
        _, xong = tai.next_chunk()
    return buf.getvalue()
