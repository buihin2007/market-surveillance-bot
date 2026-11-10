"""Mã văn bản trên thuvienphapluat.vn (tvpl_id): khóa nối dòng sheet với file docx."""

import re

_LINK = re.compile(r"-(\d+)\.aspx", re.IGNORECASE)
_TEN_FILE = re.compile(r"(\d+)(?:\s*\(\d+\))?(?:\.docx?)?$", re.IGNORECASE)


def id_tu_link(link: str) -> int | None:
    """.../Nghi-dinh-98-2020-ND-CP-...-406627.aspx → 406627"""
    m = _LINK.search(link or "")
    return int(m.group(1)) if m else None


def id_tu_ten_file(ten: str) -> int | None:
    """Nhóm số cuối của tên file: 24_2025_ND-CP_m_644186.docx → 644186.

    Chịu được bản tải trùng "... (1).docx" và file mất đuôi do Drive đổi sang Google Docs.
    """
    m = _TEN_FILE.search((ten or "").strip())
    return int(m.group(1)) if m else None


def doi_chieu(ma_sheet: list[int], ma_file: list[int]) -> dict[str, list[int]]:
    """So mã TVPL giữa các dòng sheet và các file trên Drive."""
    sheet, file = set(ma_sheet), set(ma_file)
    return {
        "khop": sorted(sheet & file),
        "dong_thieu_file": sorted(sheet - file),
        "file_thieu_dong": sorted(file - sheet),
        "dong_trung_ma": sorted({m for m in sheet if ma_sheet.count(m) > 1}),
        "file_trung_ma": sorted({m for m in file if ma_file.count(m) > 1}),
    }
