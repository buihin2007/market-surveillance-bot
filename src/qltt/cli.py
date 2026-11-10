"""Lệnh dòng lệnh. Xem: uv run qltt --help"""

import sys
from typing import Annotated

import psycopg
import typer
from pydantic import ValidationError

from qltt import db, tvpl
from qltt.config import CauHinh, cau_hinh

app = typer.Typer(help="Chatbot tra cứu xử phạt QLTT.", no_args_is_help=True, add_completion=False)
db_app = typer.Typer(help="Cơ sở dữ liệu Postgres.", no_args_is_help=True)
google_app = typer.Typer(help="Google Sheet + Drive (chỉ đọc).", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(google_app, name="google")


def dung(thong_bao: str) -> typer.Exit:
    """In lỗi cho người đọc rồi thoát mã 1, không in traceback."""
    typer.echo(thong_bao, err=True)
    return typer.Exit(1)


def lay_cau_hinh() -> CauHinh:
    try:
        return cau_hinh()
    except ValidationError as e:
        bien = ", ".join(str(loi["loc"][0]).upper() for loi in e.errors())
        raise dung(f"Cấu hình thiếu hoặc sai: {bien}. Xem .env.example.") from None


@db_app.command("init")
def db_init(
    xoa_dan_xuat: Annotated[
        bool,
        typer.Option(
            "--xoa-dan-xuat",
            help="Xóa các bảng dẫn xuất rồi tạo lại. Bảng gốc và cache giữ nguyên.",
        ),
    ] = False,
):
    """Tạo extension, bảng, index. Chạy lại nhiều lần không sao."""
    c = lay_cau_hinh()
    try:
        conn = db.ket_noi()
    except psycopg.OperationalError as e:
        dong_dau = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise dung(
            f"Không kết nối được Postgres ở {c.db_host}:{c.db_port}: {dong_dau}\n"
            "Đã chạy `docker compose up -d db` chưa? Mật khẩu trong .env có đúng không?"
        ) from None
    with conn:
        db.khoi_tao(conn, xoa_dan_xuat=xoa_dan_xuat)
        tt = db.thong_tin(conn)
    typer.echo(f"Postgres {tt['postgres']} tại {c.db_host}:{c.db_port}/{c.db_name}")
    typer.echo("Extension: " + ", ".join(f"{k} {v}" for k, v in sorted(tt["extension"].items())))
    nhom = (("Dẫn xuất", db.BANG_DAN_XUAT), ("Gốc", db.BANG_GOC), ("Cache", db.BANG_CACHE))
    for nhan, bang in nhom:
        typer.echo(f"Bảng {nhan.lower()}: " + ", ".join(f"{b} ({tt['so_dong'][b]})" for b in bang))


@google_app.command("kiem-tra")
def google_kiem_tra():
    """Đọc thử sheet và thư mục Drive, đối chiếu mã TVPL giữa hai bên."""
    from googleapiclient.errors import HttpError

    from qltt import google_io

    c = lay_cau_hinh()
    if not c.google_sa_key.exists():
        raise dung(f"Chưa có file khóa service account ở {c.google_sa_key}.")
    if not (c.sheet_id and c.folder_id):
        raise dung("Chưa điền SHEET_ID và FOLDER_ID trong .env.")
    email = google_io.email_service_account()
    typer.echo(f"Service account: {email}")
    try:
        dong = google_io.doc_sheet()
        files = google_io.liet_ke_file()
    except google_io.LoiTieuDe as e:
        raise dung(f"Sheet '{c.sheet_tab}': {e}") from None
    except HttpError as e:
        goi_y = {
            403: f"Đã share thư mục cho {email} (quyền Người xem) chưa? "
            "Đã bật Sheets API và Drive API chưa?",
            404: "Kiểm tra SHEET_ID, FOLDER_ID, SHEET_TAB và việc share thư mục.",
        }.get(e.status_code, "")
        raise dung(f"Google trả lỗi {e.status_code}: {e.reason}\n{goi_y}") from None

    ma_dong = [tvpl.id_tu_link(str(d["link_tvpl"])) for d in dong]
    ma_file = [tvpl.id_tu_ten_file(f["name"]) for f in files]
    so_md5 = sum("md5Checksum" in f for f in files)
    typer.echo(f"Sheet '{c.sheet_tab}': đủ 7 cột, {len(dong)} dòng.")
    typer.echo(f"Drive: {len(files)} file, {so_md5} có md5.")
    if dong:
        d = dong[0]
        ngay = d["ngay_ban_hanh"]
        if isinstance(ngay, int | float):
            ngay = f"{google_io.ngay_tu_serial(ngay):%d/%m/%Y}"
        typer.echo(
            f"Dòng {d['dong']}: {d['so_hieu']}, ban hành {ngay}, "
            f"tick {d['con_hieu_luc']!r}, mã {ma_dong[0]}"
        )

    canh_bao = {
        "Dòng có link không chứa mã TVPL": [
            d["dong"] for d, m in zip(dong, ma_dong, strict=True) if m is None
        ],
        "Dòng có ngày ban hành không phải kiểu ngày": [
            d["dong"] for d in dong if not isinstance(d["ngay_ban_hanh"], int | float)
        ],
        "Dòng có ô tick không phải hộp kiểm": [
            d["dong"] for d in dong if not isinstance(d["con_hieu_luc"], bool)
        ],
        "File không đọc được mã TVPL từ tên": [
            f["name"] for f, m in zip(files, ma_file, strict=True) if m is None
        ],
        "File không có md5 (có thể đã bị đổi sang Google Docs)": [
            f["name"] for f in files if "md5Checksum" not in f
        ],
    }
    kq = tvpl.doi_chieu([m for m in ma_dong if m], [m for m in ma_file if m])
    ten_file = {m: f["name"] for f, m in zip(files, ma_file, strict=True)}
    so_hieu = {m: d["so_hieu"] for d, m in zip(dong, ma_dong, strict=True)}
    canh_bao |= {
        "Dòng chưa có file": [f"{so_hieu[m]} ({m})" for m in kq["dong_thieu_file"]],
        "File chưa có dòng": [ten_file[m] for m in kq["file_thieu_dong"]],
        "Mã lặp trên sheet": kq["dong_trung_ma"],
        "Mã lặp trên Drive": kq["file_trung_ma"],
    }
    typer.echo(f"Đối chiếu: {len(kq['khop'])} văn bản khớp giữa sheet và Drive.")
    for nhan, ds in canh_bao.items():
        if ds:
            typer.echo(f"  {nhan} ({len(ds)}): " + ", ".join(map(str, ds)))
    if not any(canh_bao.values()):
        typer.echo("  Không có cảnh báo.")


def main() -> None:
    for luong in (sys.stdout, sys.stderr):
        # Windows: in được tiếng Việt cả khi đầu ra bị chuyển hướng sang file
        luong.reconfigure(encoding="utf-8")
    app()
