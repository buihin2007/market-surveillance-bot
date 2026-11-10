from datetime import date

import pytest

from qltt import google_io

TIEU_DE = [
    "Số hiệu",
    "Ngày ban hành",
    "Loại văn bản",
    "Còn hiệu lực",
    "Ngày có hiệu lực",
    "Hiệu lực đến",
    "Link TVPL",
]


def test_bo_dau():
    assert google_io.bo_dau("  Hiệu lực   đến ") == "hieu luc den"
    assert {google_io.bo_dau(t) for t in TIEU_DE} == set(google_io.COT)


def test_ngay_tu_serial():
    assert google_io.ngay_tu_serial(44069) == date(2020, 8, 26)


def test_dong_tu_values():
    values = [
        TIEU_DE,
        ["98/2020/NĐ-CP", 44069, "Nghị định", True, 44119, "", "https://x/a-406627.aspx"],
        ["17/2022/NĐ-CP", 44592, "Nghị định", True],  # Sheets cắt các ô trống cuối dòng
        ["", "", "", False],  # dòng trống của bảng, chỉ có ô tick
    ]
    dong = google_io.dong_tu_values(values)
    assert [d["dong"] for d in dong] == [2, 3]
    assert dong[0]["so_hieu"] == "98/2020/NĐ-CP"
    assert dong[0]["con_hieu_luc"] is True
    assert dong[1]["link_tvpl"] == ""


def test_doc_theo_ten_cot_khong_theo_vi_tri():
    values = [list(reversed(TIEU_DE)), ["link", "", 1, True, "Luật", 2, "88/2025/QH15"]]
    dong = google_io.dong_tu_values(values)
    assert dong[0]["so_hieu"] == "88/2025/QH15"
    assert dong[0]["link_tvpl"] == "link"


@pytest.mark.parametrize(
    "tieu_de",
    [TIEU_DE[:-1], [*TIEU_DE[:-1], "Ghi chú"], []],
    ids=["thieu_cot", "cot_la", "tab_trong"],
)
def test_tieu_de_sai_thi_dung(tieu_de):
    with pytest.raises(google_io.LoiTieuDe):
        google_io.dong_tu_values([tieu_de] if tieu_de else [])


# --- Thư viện Google thật, câu trả lời giả: kiểm tên tham số gửi đi và việc phân trang ---


def test_doc_sheet_gui_dung_tham_so(gia_lap_google):
    values = [TIEU_DE, ["98/2020/NĐ-CP", 44069, "Nghị định", True, 44119, "", "l-406627.aspx"]]
    http = gia_lap_google([(200, {"values": values})])

    dong = google_io.doc_sheet()

    assert dong[0]["ngay_ban_hanh"] == 44069
    uri = http.request_sequence[0][0]
    assert "/spreadsheets/ma_sheet/values/%27Van_ban%27%21A1%3AG" in uri
    assert "valueRenderOption=UNFORMATTED_VALUE" in uri
    assert "dateTimeRenderOption=SERIAL_NUMBER" in uri


def test_liet_ke_file_di_het_cac_trang(gia_lap_google):
    http = gia_lap_google(
        [
            (200, {"files": [{"id": "1", "name": "a_1.docx"}], "nextPageToken": "trang2"}),
            (200, {"files": [{"id": "2", "name": "b_2.docx"}]}),
        ]
    )

    files = google_io.liet_ke_file()

    assert [f["id"] for f in files] == ["1", "2"]
    uri_1, uri_2 = (r[0] for r in http.request_sequence)
    assert "%27ma_thu_muc%27+in+parents+and+trashed+%3D+false" in uri_1
    assert "pageToken=trang2" in uri_2


def test_tai_noi_dung_file_docx(gia_lap_google):
    http = gia_lap_google([(200, b"PK noi dung")])

    assert google_io.tai_noi_dung({"id": "abc", "mimeType": "docx"}) == b"PK noi dung"
    assert "/files/abc?" in http.request_sequence[0][0]
    assert "alt=media" in http.request_sequence[0][0]


def test_tai_noi_dung_google_docs_thi_xuat_docx(gia_lap_google):
    http = gia_lap_google([(200, b"PK xuat ra")])

    f = {"id": "abc", "mimeType": "application/vnd.google-apps.document"}
    assert google_io.tai_noi_dung(f) == b"PK xuat ra"
    uri = http.request_sequence[0][0]
    assert "/files/abc/export?" in uri
    assert "wordprocessingml" in uri
