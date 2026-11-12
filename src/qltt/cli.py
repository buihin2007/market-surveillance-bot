"""Lệnh dòng lệnh. Xem: uv run qltt --help"""

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import psycopg
import typer
from pydantic import ValidationError

from qltt import db, tvpl
from qltt.config import CauHinh, cau_hinh

app = typer.Typer(help="Chatbot tra cứu xử phạt QLTT.", no_args_is_help=True, add_completion=False)
db_app = typer.Typer(help="Cơ sở dữ liệu Postgres.", no_args_is_help=True)
google_app = typer.Typer(help="Google Sheet + Drive (chỉ đọc).", no_args_is_help=True)
parse_app = typer.Typer(help="Đọc docx thành Điều, khoản, phụ lục.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(google_app, name="google")
eval_app = typer.Typer(help="Bộ đánh giá eval/cases.jsonl.", no_args_is_help=True)
app.add_typer(parse_app, name="parse")
app.add_typer(eval_app, name="eval")
bao_sai_app = typer.Typer(
    help="Báo sai: ghi, xem, xử lý, đưa thành case eval (GĐ 4 nối vào nút Telegram).",
    no_args_is_help=True,
)
app.add_typer(bao_sai_app, name="bao-sai")


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


def ket_noi_db() -> psycopg.Connection:
    c = lay_cau_hinh()
    try:
        return db.ket_noi()
    except psycopg.OperationalError as e:
        dong_dau = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise dung(
            f"Không kết nối được Postgres ở {c.db_host}:{c.db_port}: {dong_dau}\n"
            "Đã chạy `docker compose up -d db` chưa? Mật khẩu trong .env có đúng không?"
        ) from None


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
    with ket_noi_db() as conn:
        db.khoi_tao(conn, xoa_dan_xuat=xoa_dan_xuat)
        tt = db.thong_tin(conn)
    typer.echo(f"Postgres {tt['postgres']} tại {c.db_host}:{c.db_port}/{c.db_name}")
    typer.echo("Extension: " + ", ".join(f"{k} {v}" for k, v in sorted(tt["extension"].items())))
    nhom = (("Dẫn xuất", db.BANG_DAN_XUAT), ("Gốc", db.BANG_GOC), ("Cache", db.BANG_CACHE))
    for nhan, bang in nhom:
        typer.echo(f"Bảng {nhan.lower()}: " + ", ".join(f"{b} ({tt['so_dong'][b]})" for b in bang))


def kiem_cau_hinh_google() -> CauHinh:
    from qltt import google_io

    c = lay_cau_hinh()
    if not c.google_sa_key.exists():
        raise dung(f"Chưa có file khóa service account ở {c.google_sa_key}.")
    if not (c.sheet_id and c.folder_id):
        raise dung("Chưa điền SHEET_ID và FOLDER_ID trong .env.")
    typer.echo(f"Service account: {google_io.email_service_account()}")
    return c


@contextmanager
def loi_google():
    """Đổi lỗi của Google thành thông báo dễ hiểu."""
    from googleapiclient.errors import HttpError

    from qltt import google_io

    c = cau_hinh()
    try:
        yield
    except google_io.LoiTieuDe as e:
        raise dung(f"Sheet '{c.sheet_tab}': {e}") from None
    except HttpError as e:
        goi_y = {
            403: f"Đã share thư mục cho {google_io.email_service_account()} (quyền Người xem) "
            "chưa? Đã bật Sheets API và Drive API chưa?",
            404: "Kiểm tra SHEET_ID, FOLDER_ID, SHEET_TAB và việc share thư mục.",
        }.get(e.status_code, "")
        raise dung(f"Google trả lỗi {e.status_code}: {e.reason}\n{goi_y}") from None


@google_app.command("kiem-tra")
def google_kiem_tra():
    """Đọc thử sheet và thư mục Drive, đối chiếu mã TVPL giữa hai bên."""
    from qltt import google_io

    c = kiem_cau_hinh_google()
    with loi_google():
        dong = google_io.doc_sheet()
        files = google_io.liet_ke_file()

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


@google_app.command("tai")
def google_tai():
    """Tải về máy các file docx chưa có bản sao (data/raw/{mã}/{md5}.docx)."""
    from qltt import google_io, kho_file

    c = kiem_cau_hinh_google()
    with loi_google():
        files = google_io.liet_ke_file()
    typer.echo(f"Drive: {len(files)} file. Đang tải file chưa có vào {c.thu_muc_raw} ...")

    def tai(f: dict) -> bytes:
        typer.echo(f"  tải {f['name']}")
        return google_io.tai_noi_dung(f)

    kq = kho_file.dong_bo_file(files, c.thu_muc_raw, tai)
    dung_luong = sum(p.stat().st_size for p in kq.moi) / 1e6
    typer.echo(
        f"Mới tải: {len(kq.moi)} file ({dung_luong:.1f} MB). Đã có sẵn: {len(kq.da_co)}. "
        f"Bỏ qua: {len(kq.bo_qua)}. Lỗi: {len(kq.loi)}."
    )
    for dong in kq.bo_qua + kq.loi:
        typer.echo(f"  {dong}")
    if kq.loi:
        raise typer.Exit(1)


@parse_app.command("kiem-tra")
def parse_kiem_tra(
    ma: Annotated[
        int | None, typer.Option("--ma", help="Chỉ một văn bản (mã TVPL), in danh sách Điều")
    ] = None,
):
    """Parse các docx đã tải về, chạy gate, ghi kết quả ra data/parse/{mã}.json để xem."""
    import dataclasses
    import json

    from qltt import gate, google_io
    from qltt import parse as ps
    from qltt.nap import LOAI

    c = kiem_cau_hinh_google()
    with loi_google():
        sheet = {tvpl.id_tu_link(str(d["link_tvpl"])): d for d in google_io.doc_sheet()}
    files = {}  # mã → bản sao mới nhất
    for p in sorted(c.thu_muc_raw.glob("*/*.docx"), key=lambda p: p.stat().st_mtime):
        if p.parent.name.isdigit():
            files[int(p.parent.name)] = p
    if ma is not None:
        files = {ma: files[ma]} if ma in files else {}
    if not files:
        raise dung(f"Không có docx nào trong {c.thu_muc_raw}. Chạy `qltt google tai` trước.")

    ra = c.thu_muc_raw.parent / "parse"
    ra.mkdir(parents=True, exist_ok=True)
    dem = {"qua": 0, "dieu": 0, "khoan": 0, "pl_giu": 0, "pl_bo": 0}
    for m, p in sorted(files.items()):
        d = sheet.get(m)
        if d is None:
            typer.echo(f"BỎ QUA {m}: không có dòng trên sheet")
            continue
        ngay = d["ngay_ban_hanh"]
        ngay = google_io.ngay_tu_serial(ngay) if isinstance(ngay, int | float) else None
        vb = ps.parse(p)
        la_vbhn = LOAI.get(google_io.bo_dau(str(d.get("loai", "")))) == "vbhn"
        g = gate.kiem(vb, str(d["so_hieu"]), ngay, la_vbhn)
        (ra / f"{m}.json").write_text(
            json.dumps(
                dataclasses.asdict(vb) | {"gate": dataclasses.asdict(g)},
                default=str,
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        dem["qua"] += g.qua
        dem["dieu"] += len(vb.dieu)
        dem["khoan"] += sum(len(x.khoan) for x in vb.dieu)
        dem["pl_giu"] += sum(x.la_danh_muc for x in vb.phu_luc)
        dem["pl_bo"] += sum(not x.la_danh_muc for x in vb.phu_luc)
        if g.loi or g.canh_bao:
            typer.echo(f"{'TRƯỢT' if g.loi else 'CẢNH BÁO'} {m} {d['so_hieu']}")
            for x in g.loi:
                typer.echo(f"    lỗi: {x}")
            for x in g.canh_bao:
                typer.echo(f"    cảnh báo: {x}")
        if ma is not None:
            for x in vb.dieu:
                typer.echo(f"  Điều {x.ky_hieu}. {x.ten[:70]} ({len(x.khoan)} khoản)")
            for x in vb.phu_luc:
                typer.echo(f"  Phụ lục {x.so} {x.ten[:60]} [{'giữ' if x.la_danh_muc else 'bỏ'}]")

    typer.echo(
        f"Qua gate: {dem['qua']}/{len(files)}. Điều: {dem['dieu']}, khoản: {dem['khoan']}, "
        f"phụ lục giữ: {dem['pl_giu']}, bỏ: {dem['pl_bo']}. Chi tiết từng văn bản: {ra}"
    )
    if dem["qua"] < len(files):
        raise typer.Exit(1)


@app.command("nap")
def nap_lenh(
    lam_lai: Annotated[
        bool, typer.Option("--lam-lai", help="Parse lại cả văn bản có file không đổi")
    ] = False,
):
    """Đọc sheet + Drive, tải file mới, parse, ghi vào DB, tính lại toàn kho. Chưa embed
    (dùng qltt dong-bo để làm cả embed)."""
    _dong_bo(lam_lai, embed=False)


@app.command("dong-bo")
def dong_bo_lenh(
    full: Annotated[
        bool, typer.Option("--full", help="Parse lại mọi văn bản (kể cả file không đổi).")
    ] = False,
    khong_embed: Annotated[
        bool, typer.Option("--khong-embed", help="Bỏ bước tạo vector (không gọi API).")
    ] = False,
):
    """Đồng bộ trọn vẹn: so Sheet / Drive / DB, nạp phần đổi, tính lại toàn kho, embed, báo cáo
    (ghi vào nhat_ky_dong_bo). Chạy lại khi không có gì đổi → "Không có gì mới"."""
    _dong_bo(full, embed=not khong_embed)


def _dong_bo(lam_lai: bool, embed: bool) -> None:
    from datetime import date

    from qltt import dong_bo, google_io

    c = kiem_cau_hinh_google()
    with loi_google():
        dong = google_io.doc_sheet()
        files = google_io.liet_ke_file()
    ham = None
    if embed:
        ham = dong_bo.ham_embed(client_embed(c), c.embed_model, c.embed_gia_1m_token)
    with ket_noi_db() as conn, loi_google(), loi_openai(c.embed_model):
        kq = dong_bo.chay(
            conn, dong, files, c.thu_muc_raw, google_io.tai_noi_dung, google_io.ngay_tu_serial,
            date.today(), embed_fn=ham, lam_lai=lam_lai,
        )  # fmt: skip
        if not kq.dang_chay:
            dem = dict(conn.execute("SELECT loai, count(*) FROM muc_phat GROUP BY 1").fetchall())
    typer.echo(dong_bo.bao_cao(kq))
    if kq.dang_chay:
        raise typer.Exit(1)
    kh = kq.ke_hoach
    typer.echo(
        f"(Chi tiết: nạp {len(kq.da_nap)} văn bản, {kq.so_chunk} chunk; file không đổi"
        f" {len(kh.khong_doi)}; khung phạt {sum(dem.values())} dòng, chưa tách được"
        f" {dem.get('khong_tach', 0)}.)"
    )
    if not embed:
        con = kq.thong_ke.get("chunk_tim_kiem")
        typer.echo(f"Chưa tạo vector cho đoạn mới (nếu có): chạy qltt embed. Đoạn tìm kiếm: {con}.")


@app.command("van-ban")
def van_ban_lenh(
    tim: Annotated[str, typer.Argument(help="Một phần số hiệu hoặc tên (bỏ trống: tất cả).")] = "",
):
    """Liệt kê văn bản trong kho: trạng thái, có dùng để tra không, vì sao không."""
    with ket_noi_db() as conn:
        rows = conn.execute(
            """
            SELECT v.so_hieu, v.trang_thai, v.dung_de_tra, v.go_khoi_sheet, left(v.ten, 70),
                v.so_chunk,
                (SELECT h.so_hieu FROM quan_he_van_ban q JOIN van_ban h ON h.tvpl_id = q.tu
                 WHERE q.den = v.tvpl_id AND q.loai = 'hop_nhat' AND h.dung_de_tra LIMIT 1),
                (SELECT h.so_hieu FROM quan_he_van_ban q JOIN van_ban h ON h.tvpl_id = q.tu
                 WHERE q.den = v.tvpl_id AND q.loai IN ('thay_the', 'bai_bo')
                   AND q.nguon IN ('dieu_hieu_luc', 'tay') AND h.trang_thai = 'hieu_luc' LIMIT 1)
            FROM van_ban v
            WHERE v.so_hieu ILIKE %(t)s OR v.ten ILIKE %(t)s
            ORDER BY v.dung_de_tra DESC, v.ngay_ban_hanh DESC
            """,
            {"t": f"%{tim}%"},
        ).fetchall()
    for sh, tt, tra, go, ten, n, vbhn, thay in rows:
        if tra:
            ly_do = "dùng để tra"
        elif go:
            ly_do = "đã xóa khỏi sheet"
        elif tt != "hieu_luc":
            ly_do = tt
        elif vbhn:
            ly_do = f"tra qua {vbhn}"
        elif thay:
            ly_do = f"bị {thay} thay"
        else:
            ly_do = "đã hợp nhất vào VBHN"
        typer.echo(f"  {sh:<24} {ly_do:<30} {n or 0:>5} đoạn  {ten or ''}")
    typer.echo(f"{len(rows)} văn bản.")


@app.command("embed")
def embed_lenh():
    """Tạo vector cho các chunk chưa có (tra cache trước, chỉ trả tiền cho phần thiếu)."""
    import openai

    from qltt import embed

    c = lay_cau_hinh()
    if not c.llm_api_key.get_secret_value():
        raise dung("Chưa điền LLM_API_KEY trong .env.")
    client = embed.tao_client(c.llm_api_key.get_secret_value(), c.llm_base_url)
    typer.echo(f"Model: {c.embed_model} qua {c.llm_base_url}")

    def bao(kq: embed.KetQuaEmbed):
        typer.echo(f"  {kq.tu_cache + kq.tu_api}/{kq.can} chunk, {kq.token:,} token")

    with ket_noi_db() as conn:
        conn.autocommit = True  # mỗi lô tự commit: dừng giữa chừng không mất phần đã làm
        try:
            kq = embed.embed_tat_ca(conn, client, c.embed_model, bao)
        except openai.AuthenticationError:
            raise dung("API key bị từ chối. Kiểm tra LLM_API_KEY trong .env.") from None
        except (openai.NotFoundError, openai.BadRequestError) as e:
            raise dung(f"API báo lỗi với model {c.embed_model}: {e}") from None
        except openai.APIError as e:
            raise dung(f"Gọi API lỗi: {e}. Chạy lại lệnh để làm tiếp từ chỗ dừng.") from None
        con_thieu = conn.execute(
            "SELECT count(*) FROM chunk WHERE embed AND embedding IS NULL"
        ).fetchone()[0]
    chi_phi = kq.token / 1e6 * c.embed_gia_1m_token
    typer.echo(
        f"Xong: {kq.can} chunk cần vector, {kq.tu_cache} lấy từ cache, {kq.tu_api} gọi API "
        f"({kq.so_lan_goi} lần, {kq.token:,} token, ~{chi_phi:.3f} USD). Còn thiếu: {con_thieu}."
    )


def client_embed(c: CauHinh):
    from qltt import embed

    if not c.llm_api_key.get_secret_value():
        raise dung("Chưa điền LLM_API_KEY trong .env (hoặc chạy với --chi-tu-khoa).")
    return embed.tao_client(c.llm_api_key.get_secret_value(), c.llm_base_url)


@contextmanager
def loi_openai(model: str):
    import openai

    try:
        yield
    except openai.AuthenticationError:
        raise dung("API key bị từ chối. Kiểm tra LLM_API_KEY trong .env.") from None
    except (openai.NotFoundError, openai.BadRequestError) as e:
        raise dung(f"API báo lỗi với model {model}: {e}") from None
    except openai.APIError as e:
        raise dung(f"Gọi API lỗi: {e}. Chạy lại lệnh.") from None


@app.command("hoi")
def hoi_lenh(
    cau_hoi: Annotated[str, typer.Argument(help="Câu hỏi, đặt trong ngoặc kép.")],
    chi_tiet: Annotated[
        bool, typer.Option("--chi-tiet", help="In thêm loại câu hỏi, câu viết lại, ứng viên.")
    ] = False,
):
    """Hỏi như chú sẽ hỏi bot: in câu trả lời, thời gian và chi phí; ghi vết vào chat_log."""
    from qltt import nhat_ky, tra_loi

    c = lay_cau_hinh()
    with ket_noi_db() as conn, loi_openai(c.llm_model):
        try:
            tl = tra_loi.hoi(conn, client_embed(c), c, cau_hoi)
        except ValueError as e:
            raise dung(str(e)) from None
        ma = nhat_ky.ghi(conn, tl, c)
    if chi_tiet:
        typer.echo(f"Loại: {tl.loai}; viết lại: {'; '.join(tl.viet_lai) or '-'}")
        typer.echo(
            f"Ứng viên: {len(tl.dieu_gan)} Điều, {tl.so_ung_vien} hành vi; chủ thể {tl.chu_the},"
            f" giá trị {tl.gia_tri}, số lượng {tl.so_luong} {tl.don_vi or ''}"
        )
        typer.echo("")
    typer.echo(tl.van_ban)
    buoc = ", ".join(f"{b.ten} {b.giay:.1f}s" + (" (cache)" if b.tu_cache else "") for b in tl.buoc)
    typer.echo(f"\n--- {tl.giay:.1f} s ({buoc}); {tl.chi_phi:.5f} USD")
    typer.echo(f'Mã câu trả lời #{ma}. Sai thì: uv run qltt bao-sai them {ma} "lý do"')


@bao_sai_app.command("them")
def bao_sai_them(
    ma: Annotated[int, typer.Argument(help="Mã câu trả lời (#id in sau câu trả lời).")],
    ly_do: Annotated[
        str, typer.Argument(help='Lý do, nên ghi căn cứ đúng: "phải là Điều 11".')
    ] = "",
    kieu: Annotated[
        str | None,
        typer.Option(
            help="Nút chú bấm: sai_hanh_vi | sai_muc_phat | sai_bien_phap | van_ban_cu |"
            " khong_tim_thay | khac"
        ),
    ] = None,
):
    """Ghi một báo sai (thay nút Báo sai trên Telegram khi thử bằng CLI)."""
    from qltt import nhat_ky

    with ket_noi_db() as conn:
        try:
            i = nhat_ky.bao_sai(conn, ma, ly_do, kieu=kieu)
        except ValueError as e:
            raise dung(str(e)) from None
        g = nhat_ky.goi_y(conn, i)
    typer.echo(
        f"Đã ghi báo sai #{i} cho câu trả lời #{ma}." + (f" Gợi ý khâu hỏng: {g}" if g else "")
    )


@bao_sai_app.command("ds")
def bao_sai_ds(
    tat_ca: Annotated[bool, typer.Option("--tat-ca", help="Cả báo sai đã xử lý.")] = False,
):
    """Liệt kê báo sai (mặc định: chưa xử lý) kèm vết: câu hỏi, viết lại, ứng viên, đã chọn."""
    from qltt import nhat_ky

    with ket_noi_db() as conn:
        rows = conn.execute(
            "SELECT b.id, b.luc, b.ly_do, b.trang_thai, b.nguyen_nhan, b.case_id, b.kieu, l.id,"
            " l.cau_hoi,"
            " l.loai_ket_qua, l.ket_qua, l.vet"
            " FROM bao_sai b JOIN chat_log l ON l.id = b.chat_log_id"
            + ("" if tat_ca else " WHERE b.trang_thai = 'moi'")
            + " ORDER BY b.id"
        ).fetchall()
        goi = {r[0]: nhat_ky.goi_y(conn, r[0]) for r in rows}
    if not rows:
        typer.echo("Không có báo sai" + ("." if tat_ca else " chưa xử lý."))
    for bid, luc, ly_do, tt, nn, case, kieu, lid, cau, lkq, kq, vet in rows:
        typer.echo(f"\n#{bid} [{tt}{', ' + nn if nn else ''}{', ' + case if case else ''}]"
                   f" {luc:%d/%m %H:%M} — câu trả lời #{lid} ({lkq})")  # fmt: skip
        typer.echo(f"  Câu hỏi: {cau}")
        typer.echo(f"  Chú chọn: {nhat_ky.KIEU.get(kieu, '-') if kieu else '-'}")
        typer.echo(f"  Chú ghi thêm: {ly_do or '-'}")
        typer.echo(f"  Viết lại: {'; '.join(vet.get('viet_lai', [])) or '-'}")
        uv = vet.get("ung_vien_dieu", [])
        typer.echo("  Điều ứng viên: " + "; ".join(f"{x['so_hieu']} Đ{x['dieu']}" for x in uv))
        for x in kq.get("chon", []):
            d = f"điểm {x['diem']} " if x.get("diem") else ""
            typer.echo(f"  Đã chọn: {d}khoản {x['khoan']} Điều {x['dieu']} {x['so_hieu']}"
                       f" — {x['hanh_vi'][:90]}")  # fmt: skip
        if goi[bid]:
            typer.echo(f"  Gợi ý khâu hỏng: {goi[bid]}")


@bao_sai_app.command("xu-ly")
def bao_sai_xu_ly(
    ma: Annotated[int, typer.Argument(help="Mã báo sai.")],
    trang_thai: Annotated[str, typer.Option(help="da_sua | khong_loi | chua_sua_duoc")],
    nguyen_nhan: Annotated[
        str | None,
        typer.Option(
            help="phan_loai | tim_kiem | chon | muc_phat | bien_phap | kho_thieu | khong_loi | khac"
        ),
    ] = None,
    ghi_chu: Annotated[str, typer.Option(help="Đã sửa gì / vì sao không phải lỗi.")] = "",
):
    """Đóng một báo sai sau khi xem; ghi khâu hỏng để thống kê."""
    from qltt import nhat_ky

    with ket_noi_db() as conn:
        try:
            nhat_ky.xu_ly(conn, ma, trang_thai, nguyen_nhan, ghi_chu)
        except ValueError as e:
            raise dung(str(e)) from None
    typer.echo(f"Báo sai #{ma}: {trang_thai}.")


@bao_sai_app.command("thanh-case")
def bao_sai_thanh_case(
    ma: Annotated[int, typer.Argument(help="Mã báo sai.")],
    van_ban: Annotated[str, typer.Option(help="Số hiệu văn bản gốc, vd 98/2020/NĐ-CP.")],
    dieu: Annotated[str, typer.Option(help="Điều đúng, vd 11 hoặc 53a.")],
    khoan: Annotated[list[int], typer.Option(help="Khoản đúng (lặp lại được).")] = [],  # noqa: B006
    diem: Annotated[list[str], typer.Option(help="Điểm đúng (lặp lại được).")] = [],  # noqa: B006
    file: Annotated[Path, typer.Option(help="File case.")] = Path("eval/cases.jsonl"),
):
    """Đưa câu hỏi bị báo sai vào bộ eval (cứ 4 case thì 1 case vào nhóm giữ lại)."""
    from qltt import danh_gia, nhat_ky

    with ket_noi_db() as conn:
        case_id = nhat_ky.thanh_case(conn, ma, file, van_ban, dieu, khoan, diem)
        conn.commit()
        try:
            x = next(c for c in danh_gia.doc_cases(file) if c.id == case_id)
            da = danh_gia.giai(conn, x)
        except ValueError as e:
            raise dung(f"{case_id} đã thêm nhưng file lỗi: {e}") from None
    loi = f" Căn cứ lỗi: {'; '.join(da.loi)} — sửa tay trong {file}." if da.loi else ""
    typer.echo(f"Đã thêm {case_id}{' (nhóm giữ lại)' if x.giu_lai else ''}.{loi}")


@app.command("bot")
def bot_lenh():
    """Chạy bot Telegram (long polling; Ctrl+C để dừng). Cần TELEGRAM_TOKEN, TELEGRAM_CHO_PHEP."""
    import logging

    from qltt import bot

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # không in mỗi lần poll (lộ token)
    c = lay_cau_hinh()
    try:
        app = bot.tao_ung_dung(c)
    except ValueError as e:
        raise dung(str(e)) from None
    typer.echo(
        f"Bot chạy với {len(c.ds_cho_phep)} người được phép; admin: {c.telegram_admin or 'không'}."
        " Ctrl+C để dừng."
    )
    app.run_polling(allowed_updates=["message", "callback_query"])


@app.command("do-thi")
def do_thi_lenh():
    """In sơ đồ đồ thị trả lời (Mermaid; dán vào mermaid.live để xem)."""
    from qltt import do_thi

    typer.echo(do_thi.mermaid())


@app.command("tim")
def tim_lenh(
    cau_hoi: Annotated[str, typer.Argument(help="Câu hỏi, đặt trong ngoặc kép.")],
    chi_tu_khoa: Annotated[bool, typer.Option("--chi-tu-khoa", help="Không gọi API.")] = False,
    khong_viet_lai: Annotated[
        bool, typer.Option("--khong-viet-lai", help="Không dùng LLM viết lại câu hỏi.")
    ] = False,
):
    """Thử một câu: in hành vi ứng viên (Điều xử phạt), định nghĩa và quy phạm liên quan."""
    from qltt import ngu_canh, tim_kiem, viet_lai

    c = lay_cau_hinh()
    with ket_noi_db() as conn:
        vec, them = None, []
        if not chi_tu_khoa:
            client = client_embed(c)
            cau = [cau_hoi]
            if not khong_viet_lai:
                with loi_openai(c.llm_model):
                    cau += viet_lai.viet_lai(
                        conn, client, c.llm_model, cau_hoi, c.viet_lai_prompt, c.llm_tat_suy_nghi
                    ).cau
            with loi_openai(c.embed_model):
                vecs, _ = tim_kiem.vector_cau_hoi(conn, client, c.embed_model, cau)
            conn.commit()
            vec, them = vecs[0], list(zip(cau[1:], vecs[1:], strict=True))
        nc = ngu_canh.lap(conn, cau_hoi, vec, them)

    def ngan(s: str, n: int = 110) -> str:
        s = " ".join(s.split())
        return s if len(s) <= n else s[: n - 1] + "…"

    if them:
        typer.echo("VIẾT LẠI (LLM)")
        for q, _ in them:
            typer.echo(f"  - {q}")
        typer.echo("")
    typer.echo("HÀNH VI ỨNG VIÊN (Điều xử phạt)")
    for i, h in enumerate(nc.hanh_vi, 1):
        typer.echo(f"{i:>2}. {h.so_hieu} {h.dieu}. {ngan(h.ten, 90)}")
        typer.echo(f"     khớp: {', '.join(h.chunk_khop[:4])}")
    typer.echo("\nĐỊNH NGHĨA trong các văn bản trên")
    for d in nc.dinh_nghia:
        typer.echo(f"  - {d.so_hieu} {d.duong_dan}: {ngan(d.noi_dung)}")
    typer.echo("\nQUY PHẠM liên quan")
    for d in nc.quy_pham:
        typer.echo(f"  - {d.so_hieu} {d.duong_dan}: {ngan(d.noi_dung)}")


@app.command("sua-doi")
def sua_doi_lenh(
    tat_ca: Annotated[
        bool, typer.Option("--tat-ca", help="In cả cặp đã hợp nhất và văn bản không có trong kho.")
    ] = False,
    van_ban: Annotated[
        str | None,
        typer.Option(
            "--van-ban", help="In chỉ dẫn sửa đổi chi tiết nhắm vào văn bản này (số hiệu)."
        ),
    ] = None,
):
    """Dựng lại quan hệ sửa đổi (từ tên Điều) và in bảng phủ: sửa đổi nào chưa có trong VBHN."""
    from qltt import sua_doi
    from qltt.parse import chuan_so_hieu

    with ket_noi_db() as conn:
        n = sua_doi.dung_lai(conn)
        n_ct = sua_doi.dung_chi_tiet(conn)
        bang = sua_doi.bang_phu(conn)
        if van_ban:
            ct = conn.execute(
                "SELECT v.so_hieu, s.vi_tri_tu, s.dieu_so, s.dieu_suffix, s.khoan, s.hanh_dong,"
                " s.mo_ta, s.chac FROM sua_doi_chi_tiet s JOIN van_ban v ON v.tvpl_id = s.tu"
                " WHERE s.den_so_hieu = %s ORDER BY v.ngay_ban_hanh, s.id",
                [chuan_so_hieu(van_ban)],
            ).fetchall()
        dem_canh_bao = sua_doi.dem_canh_bao(conn)
        lech = sua_doi.lech_sheet(conn)
    if van_ban:
        typer.echo(f"Chỉ dẫn sửa đổi nhắm vào {van_ban}: {len(ct)}")
        for sh, vt, d, h, k, hd, mt, chac in ct:
            dich = f"Điều {d}{h}" if d is not None else "cả văn bản"
            if k:
                dich += " khoản " + ",".join("mới" if x == 0 else str(x) for x in k)
            typer.echo(f"  {sh:<16} {vt:<18} → {dich:<28} {hd:<12}{'' if chac else ' (đoán đích)'}"
                       f" {mt[:80]}")  # fmt: skip
        return
    typer.echo(f"{n_ct} chỉ dẫn sửa đổi chi tiết (Điều / khoản bị sửa).")
    typer.echo(f"{n} quan hệ sửa đổi / bãi bỏ / thay thế (đọc từ tên Điều).")
    nhom = {
        "chua_hop_nhat": "CHƯA HỢP NHẤT – bot đang đọc văn bản bị sửa (có thể là chữ cũ)",
        "vbhn_thieu": "VBHN CHƯA GỒM sửa đổi – bot đọc VBHN cũ",
        "nghi_quyet": "NGHỊ QUYẾT TẠM THỜI (không hợp nhất; bot cảnh báo khi trích chỗ bị chạm)",
        "da_hop_nhat": "Đã hợp nhất",
        "khong_trong_kho": "Văn bản bị sửa không có trong kho",
        "khac": "Văn bản bị sửa hết hiệu lực / không dùng để tra",
    }
    for k, ten in nhom.items():
        ds = [d for d in bang if d.nhom == k]
        if not ds or (not tat_ca and k in ("da_hop_nhat", "khong_trong_kho")):
            typer.echo(f"\n{ten}: {len(ds)} cặp")
            continue
        typer.echo(f"\n{ten}: {len(ds)} cặp")
        for d in ds:
            ghi = f" [{d.vbhn}]" if d.vbhn else ""
            typer.echo(
                f"  {d.den_so_hieu:<16} ← {d.tu_so_hieu:<16} {d.loai:<22}{ghi}"
                f" {(d.den_ten or '')[:60]}"
            )
    rui_ro = sorted(
        {d.den_so_hieu for d in bang if d.nhom in ("chua_hop_nhat", "vbhn_thieu", "nghi_quyet")}
    )
    typer.echo(f"\nVăn bản bot đang tra có sửa đổi chưa hợp nhất ({len(rui_ro)}):")
    typer.echo("  " + ", ".join(rui_ro))
    typer.echo('\nĐiều / khoản bot đang tra sẽ kèm cảnh báo "đã bị sửa" khi được trích:')
    for sh, so, tong in dem_canh_bao:
        typer.echo(f"  {sh:<16} {so:>4} / {tong} Điều, khoản")
    typer.echo(f"\nSheet ghi còn hiệu lực nhưng đã bị thay thế / bãi bỏ ({len(lech)}):")
    for x in lech:
        typer.echo(f"  {x.so_hieu:<16} ← {x.bi_thay_boi} ({x.loai}, từ {x.tu_ngay or '?'})")
    if lech:
        typer.echo('  → nhờ chú bỏ tick "còn hiệu lực" hoặc điền ngày hết hiệu lực trên sheet.')


@app.command("dan-chieu")
def dan_chieu_lenh(
    liet_ke: Annotated[int, typer.Option(help="In bấy nhiêu dòng mỗi nhóm.")] = 30,
    tat_ca: Annotated[
        bool, typer.Option("--tat-ca", help="Tính cả văn bản không liên quan quản lý thị trường.")
    ] = False,
):
    """Dựng lại dẫn chiếu (tên luật / số hiệu / "pháp luật về X") và báo văn bản được nhắc mà kho
    chưa có."""
    from qltt import dan_chieu

    with ket_noi_db() as conn:
        n = dan_chieu.dung_lai(conn)
        b = dan_chieu.bao_cao(conn, chi_qltt=not tat_ca)
    tt = b.theo_trang_thai
    if not tat_ca:
        typer.echo("(Chỉ văn bản liên quan quản lý thị trường; --tat-ca để xem cả kho.)")
    typer.echo(
        f"{n} dẫn chiếu trong kho. Phần được tính: nối được {tt['ok']},"
        f" văn bản chưa có trong kho {tt['thieu_van_ban']},"
        f" chủ đề chưa ánh xạ {tt['chua_anh_xa']}."
    )
    typer.echo(f"\nVăn bản được nhắc nhưng kho chưa có / không dùng để tra ({len(b.thieu)}):")
    for _, khoa, so in b.thieu[:liet_ke]:
        typer.echo(f"  {so:>4} chỗ  {khoa}")
    typer.echo(f'\nChủ đề "pháp luật về …" chưa ánh xạ ({len(b.chua_anh_xa)}):')
    for khoa, so in b.chua_anh_xa[:liet_ke]:
        typer.echo(f"  {so:>4} chỗ  {khoa}")


@app.command("muc-phat")
def muc_phat_lenh(
    liet_ke: Annotated[int, typer.Option(help="In bấy nhiêu khoản chưa tách được.")] = 15,
):
    """Dựng lại bảng khung phạt + biện pháp bổ sung / khắc phục, báo độ phủ (văn bản đang tra)."""
    from qltt import bien_phap, muc_phat

    with ket_noi_db() as conn:
        muc_phat.dung_lai(conn)
        bien_phap.dung_lai(conn)
        dem_bp = conn.execute(
            "SELECT b.loai, count(*), count(*) FILTER (WHERE b.ca_dieu),"
            " count(*) FILTER (WHERE NOT b.tach_duoc) FROM bien_phap b"
            " JOIN van_ban v USING (tvpl_id) WHERE v.dung_de_tra GROUP BY 1 ORDER BY 1"
        ).fetchall()
        chua_bp = conn.execute(
            "SELECT v.so_hieu, b.dieu_so, b.dieu_suffix, b.khoan_so, b.diem, b.noi_dung"
            " FROM bien_phap b JOIN van_ban v USING (tvpl_id)"
            " WHERE v.dung_de_tra AND NOT b.tach_duoc ORDER BY 1, 2, 4 LIMIT %s",
            [liet_ke],
        ).fetchall()
        dem = dict(
            conn.execute(
                "SELECT m.loai, count(*) FROM muc_phat m JOIN van_ban v USING (tvpl_id)"
                " WHERE v.dung_de_tra GROUP BY 1"
            ).fetchall()
        )
        cua = conn.execute(
            "SELECT coalesce(mucphat_cua, 'chưa rõ'), coalesce(mucphat_cua_nguon, '-'),"
            " string_agg(so_hieu, ', ' ORDER BY so_hieu) FROM van_ban WHERE dung_de_tra"
            " AND tvpl_id IN (SELECT tvpl_id FROM muc_phat WHERE loai <> 'sua_doi')"
            " GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
        chua = conn.execute(
            "SELECT v.so_hieu, m.dieu_so, m.dieu_suffix, m.khoan_so, m.diem, m.hanh_vi"
            " FROM muc_phat m JOIN van_ban v USING (tvpl_id)"
            " WHERE v.dung_de_tra AND m.loai = 'khong_tach' ORDER BY 1, 2, 4 LIMIT %s",
            [liet_ke],
        ).fetchall()
    co = sum(n for k, n in dem.items() if k != "sua_doi")
    typer.echo(f"Văn bản đang dùng để tra: {co} hành vi (khoản/điểm), không tính khoản sửa đổi.")
    for k, n in sorted(dem.items(), key=lambda x: -x[1]):
        typer.echo(f"  {k:<20}{n:>6}")
    typer.echo(f"Tách được: {(co - dem.get('khong_tach', 0)) / max(co, 1):.1%}")
    typer.echo("\nMức phạt ghi trong văn bản là của (suy_ra / chưa rõ: cần người xác nhận):")
    for c, nguon, ds in cua:
        typer.echo(f"  {c} ({nguon}): {ds}")
    typer.echo(f"\nKhoản chưa tách được (tối đa {liet_ke}):")
    for so, d, ht, k, diem, hv in chua:
        typer.echo(f"  {so} Điều {d}{ht} khoản {k}{' điểm ' + diem if diem else ''}: {hv[:90]}")

    typer.echo("\nBiện pháp (bổ sung / khắc phục), văn bản đang tra:")
    for loai, n, ca_dieu, khong in dem_bp:
        typer.echo(f"  {loai:<10}{n:>5}  (áp cả Điều {ca_dieu}, chưa đọc được dẫn chiếu {khong})")
    typer.echo(f"Biện pháp chưa đọc được dẫn chiếu (tối đa {liet_ke}; bot trích nguyên văn):")
    for so, d, ht, k, diem, nd in chua_bp:
        typer.echo(f"  {so} Điều {d}{ht} khoản {k}{' điểm ' + diem if diem else ''}: {nd[:90]}")


@eval_app.command("kiem-tra")
def eval_kiem_tra(
    file: Annotated[Path, typer.Option(help="File case.")] = Path("eval/cases.jsonl"),
):
    """Kiểm từng căn cứ trong bộ đánh giá có trỏ đúng tới chunk đang được tìm kiếm không."""
    from collections import Counter

    from qltt import danh_gia

    try:
        cases = danh_gia.doc_cases(file)
    except FileNotFoundError:
        raise dung(f"Không thấy {file}.") from None
    except ValueError as e:
        raise dung(f"{file} sai định dạng:\n{e}") from None
    with ket_noi_db() as conn:
        dap_an = [danh_gia.giai(conn, c) for c in cases]
    so_loi = 0
    for da in dap_an:
        if da.loi:
            so_loi += 1
            typer.echo(f"LỖI {da.case.id}: " + "; ".join(da.loi))
    dem = Counter((c.nhom, c.kiem) for c in cases)
    typer.echo(
        f"{len(cases)} case: "
        + ", ".join(f"{n}/{k} {s}" for (n, k), s in sorted(dem.items()))
        + f"; giữ lại {sum(c.giu_lai for c in cases)}; {so_loi} case lỗi."
    )
    if so_loi:
        raise typer.Exit(1)


def chay_viet_lai(conn, client, c, model, prompt, tat_sn, cau: list[str], nhan: str = ""):
    """Viết lại (+ phân loại với prompt v5) từng câu, có cache; in tiến độ, token, tiền, giây."""
    from qltt import viet_lai

    ra, tien, giay, vao, ra_ = [], [], [], 0, 0
    with loi_openai(model):
        for j, q in enumerate(cau, 1):
            if j % 10 == 0:
                typer.echo(f"  {nhan}: {j}/{len(cau)}")
            kq = viet_lai.viet_lai(conn, client, model, q, prompt, tat_sn)
            ra.append(kq)
            vao, ra_ = vao + kq.token_vao, ra_ + kq.token_ra
            if not kq.tu_cache:
                tien.append(kq.chi_phi)
                giay.append(kq.giay)
    conn.commit()
    if tien and all(t is not None for t in tien):
        phi = f"{sum(tien):.4f} USD (OpenRouter tính)"
    else:  # API không trả usage.cost: ước theo giá trong .env
        phi = f"~{vao / 1e6 * c.llm_gia_1m_vao + ra_ / 1e6 * c.llm_gia_1m_ra:.4f} USD (ước)"
    tg = ""
    if giay:
        tg = f"; trung bình {sum(giay) / len(giay):.1f} s/lần, chậm nhất {max(giay):.1f} s"
    hong = sum(not (r.cau or r.loai) for r in ra)
    typer.echo(
        f"{nhan}: {len(tien)} lần gọi mới, {vao:,} + {ra_:,} token, {phi}{tg};"
        f" {hong} câu LLM không trả được"
    )
    return ra


@eval_app.command("tra-loi")
def eval_tra_loi(
    file: Annotated[Path, typer.Option(help="File case.")] = Path("eval/cases.jsonl"),
):
    """Chấm bước chọn hành vi (GĐ 2.3) trên câu hanh_vi, câu hỏi đời thường.

    đúng@1: hành vi đầu tiên LLM chọn thuộc Điều đáp án (cap_cham khoan: đúng cả khoản);
    trong DS: một trong các hành vi đã chọn đúng; khong_co: không chọn gì. In câu sai của nhóm dev.
    """
    from qltt import danh_gia, tra_loi

    c = lay_cau_hinh()
    try:
        cases = [x for x in danh_gia.doc_cases(file) if x.loai == "hanh_vi"]
    except (FileNotFoundError, ValueError) as e:
        raise dung(f"Không đọc được {file}: {e}") from None
    typer.echo(f"Trả lời {len(cases)} câu hanh_vi bằng {c.llm_model}...")
    kq = []
    with ket_noi_db() as conn, loi_openai(c.llm_model):
        client = client_embed(c)
        for j, x in enumerate(cases, 1):
            if j % 10 == 0:
                typer.echo(f"  {j}/{len(cases)}")
            da = danh_gia.giai(conn, x)
            try:
                tl = tra_loi.hoi(conn, client, c, x.cau_hoi)
            except ValueError as e:
                raise dung(str(e)) from None
            conn.commit()  # giữ cache LLM / vector nếu dừng giữa chừng
            chon = [(h.uv.tvpl_id, h.uv.dieu_so, h.uv.dieu_suffix, h.uv.khoan_so) for h in tl.chon]

            def trung(v, x=x, da=da):
                for m, so, ht, k in da.vi_tri:
                    if (v[0], v[1], v[2]) == (m, so, ht):
                        if x.cap_cham != "khoan" or k is None or v[3] == k:
                            return True
                return False

            kq.append((x, tl, chon, [trung(v) for v in chon]))
    nhom = {"dev": [r for r in kq if not r[0].giu_lai], "giữ lại": [r for r in kq if r[0].giu_lai]}
    nhom["tất cả"] = kq
    typer.echo(
        f"\n{'nhóm':<10}{'n':>4}{'đúng@1':>9}{'trong DS':>10}{'TB chọn':>9}"
        f"{'không_có':>10}{'sai loại':>10}{'giây TB':>9}{'USD TB':>10}"
    )
    for ten, rs in nhom.items():
        chinh = [r for r in rs if r[0].nhom == "chinh"]
        kc = [r for r in rs if r[0].nhom == "khong_co"]
        d1 = sum(bool(r[3]) and r[3][0] for r in chinh)
        ds = sum(any(r[3]) for r in chinh)
        tb = sum(len(r[2]) for r in chinh) / max(len(chinh), 1)
        kc_dung = sum(not r[2] for r in kc)
        sai_loai = sum(r[1].loai != "hanh_vi" for r in rs)
        giay = sum(r[1].giay for r in rs) / max(len(rs), 1)
        usd = sum(r[1].chi_phi for r in rs) / max(len(rs), 1)
        typer.echo(
            f"{ten:<10}{len(rs):>4}{f'{d1}/{len(chinh)}':>9}{f'{ds}/{len(chinh)}':>10}{tb:>9.2f}"
            f"{f'{kc_dung}/{len(kc)}':>10}{sai_loai:>10}{giay:>9.1f}{usd:>10.5f}"
        )
    typer.echo("(giây / USD TB tính cả lần lấy từ cache; chạy lần đầu mới là số thật)")
    sai = [r for r in nhom["dev"] if (r[0].nhom == "chinh" and not (r[3] and r[3][0]))
           or (r[0].nhom == "khong_co" and r[2])]  # fmt: skip
    typer.echo(f"\nCâu dev sai đúng@1 ({len(sai)}; nhóm giữ lại chỉ in điểm tổng):")
    for x, tl, _, _ in sai:
        dap = "; ".join(f"{cc.van_ban} Điều {cc.dieu} khoản {cc.khoan}" for cc in x.can_cu)
        typer.echo(f"  {x.id} [{tl.loai}] {x.cau_hoi}")
        typer.echo(f"     đáp án: {dap or 'không có'}")
        for h in tl.chon:
            typer.echo(f"     chọn: {h.uv.so_hieu} {h.uv.vi_tri}: {h.uv.hanh_vi[:90]}")
        if not tl.chon:
            typer.echo(f"     chọn: (không) / {tl.so_ung_vien} hành vi ứng viên")


@eval_app.command("tong")
def eval_tong(
    file: Annotated[Path, typer.Option(help="File case.")] = Path("eval/cases.jsonl"),
    khong_cache: Annotated[
        bool,
        typer.Option(
            "--khong-cache", help="Gọi LLM mới mọi câu để đo giây / tiền thật (~0,1 USD)."
        ),
    ] = False,
):
    """Eval toàn bộ (GĐ 2.7): mọi câu chạy cả đồ thị như chú hỏi; chấm phân loại, hành vi,
    quy định, không có; thời gian (TB, trung vị, p90, chậm nhất) và chi phí mỗi câu."""
    import statistics

    from qltt import danh_gia, llm, tra_loi

    c = lay_cau_hinh()
    try:
        cases = danh_gia.doc_cases(file)
    except (FileNotFoundError, ValueError) as e:
        raise dung(f"Không đọc được {file}: {e}") from None
    llm.BO_QUA_CACHE = khong_cache
    typer.echo(
        f"Chạy {len(cases)} câu qua đồ thị bằng {c.llm_model}"
        f"{' (không dùng cache LLM)' if khong_cache else ''}..."
    )
    kq = []
    with ket_noi_db() as conn, loi_openai(c.llm_model):
        client = client_embed(c)
        for j, x in enumerate(cases, 1):
            if j % 10 == 0:
                typer.echo(f"  {j}/{len(cases)}")
            da = danh_gia.giai(conn, x)
            try:
                tl = tra_loi.hoi(conn, client, c, x.cau_hoi)
            except ValueError as e:
                raise dung(str(e)) from None
            conn.commit()
            if tl.loai == "quy_dinh":
                vt = [(t.doan.tvpl_id, t.doan.dieu_so, t.doan.dieu_suffix, t.doan.khoan_so)
                      for t in tl.trich]  # fmt: skip
            else:
                vt = [(h.uv.tvpl_id, h.uv.dieu_so, h.uv.dieu_suffix, h.uv.khoan_so)
                      for h in tl.chon]  # fmt: skip

            def trung(v, x=x, da=da):
                return any(
                    (v[0], v[1], v[2]) == (m, so, ht)
                    and (x.cap_cham != "khoan" or k is None or v[3] == k)
                    for m, so, ht, k in da.vi_tri
                )

            kq.append((x, tl, [trung(v) for v in vt]))

    def ty(a: int, b: int) -> str:
        return f"{a}/{b}" if b else "-"

    nhom = {"dev": [r for r in kq if not r[0].giu_lai], "giữ lại": [r for r in kq if r[0].giu_lai]}
    nhom["tất cả"] = kq
    typer.echo(
        f"\n{'nhóm':<10}{'n':>4}{'phân loại':>11}{'hv đúng@1':>11}{'hv DS':>8}"
        f"{'qđ đúng@1':>11}{'qđ DS':>8}{'không_có':>10}{'trích lỗi':>11}"
    )
    for ten, rs in nhom.items():
        hv = [r for r in rs if r[0].loai == "hanh_vi" and r[0].nhom == "chinh"]
        qd = [r for r in rs if r[0].loai == "quy_dinh" and r[0].nhom == "chinh"]
        kc = [r for r in rs if r[0].nhom == "khong_co" and r[0].loai in ("hanh_vi", "quy_dinh")]
        typer.echo(
            f"{ten:<10}{len(rs):>4}"
            f"{ty(sum(r[1].loai == r[0].loai for r in rs), len(rs)):>11}"
            f"{ty(sum(bool(r[2]) and r[2][0] for r in hv), len(hv)):>11}"
            f"{ty(sum(any(r[2]) for r in hv), len(hv)):>8}"
            f"{ty(sum(bool(r[2]) and r[2][0] for r in qd), len(qd)):>11}"
            f"{ty(sum(any(r[2]) for r in qd), len(qd)):>8}"
            f"{ty(sum(not r[1].chon and not r[1].trich for r in kc), len(kc)):>10}"
            f"{sum(t.loi_trich for r in rs for t in r[1].trich):>11}"
        )
    giay = sorted(r[1].giay for r in kq)
    tien = [r[1].chi_phi for r in kq]
    p90 = giay[min(len(giay) - 1, int(0.9 * len(giay)))]
    typer.echo(
        f"\nThời gian mỗi câu: TB {statistics.mean(giay):.1f} s, trung vị"
        f" {statistics.median(giay):.1f} s, p90 {p90:.1f} s, chậm nhất {giay[-1]:.1f} s"
    )
    typer.echo(
        f"Chi phí LLM: tổng {sum(tien):.4f} USD, TB {statistics.mean(tien):.5f} USD/câu"
        + ("" if khong_cache else " (có cache: chạy --khong-cache để có số thật)")
    )
    theo_buoc: dict[str, list] = {}
    for r in kq:
        for b in r[1].buoc:
            theo_buoc.setdefault(b.ten, []).append(b)
    typer.echo(
        "Giây TB theo bước: "
        + "; ".join(f"{k} {statistics.mean(b.giay for b in v):.1f}" for k, v in theo_buoc.items())
    )
    typer.echo("\nToken (chỉ lần gọi mới; lấy từ cache = 0):")
    typer.echo(f"  {'bước':<22}{'lần gọi':>9}{'vào':>12}{'ra':>9}{'vào TB':>9}{'USD':>9}")
    tv = tr = 0
    for k, v in theo_buoc.items():
        moi = [b for b in v if b.token_vao or b.token_ra]
        if not moi:
            continue
        vao, ra = sum(b.token_vao for b in moi), sum(b.token_ra for b in moi)
        tv, tr = tv + vao, tr + ra
        typer.echo(
            f"  {k:<22}{len(moi):>9}{vao:>12,}{ra:>9,}{vao // len(moi):>9,}"
            f"{sum(b.chi_phi or 0 for b in moi):>9.4f}"
        )
    typer.echo(f"  {'tổng':<22}{'':>9}{tv:>12,}{tr:>9,}")
    sai = [r for r in nhom["dev"] if r[1].loai != r[0].loai
           or (r[0].nhom == "chinh" and not (r[2] and r[2][0]))
           or (r[0].nhom == "khong_co" and (r[1].chon or r[1].trich))]  # fmt: skip
    typer.echo(f"\nCâu dev sai ({len(sai)}; nhóm giữ lại chỉ in điểm tổng):")
    for x, tl, _ in sai:
        dap = "; ".join(f"{cc.van_ban} Điều {cc.dieu} khoản {cc.khoan}" for cc in x.can_cu)
        typer.echo(f"  {x.id} [{x.loai} → {tl.loai}] {x.cau_hoi}")
        typer.echo(f"     đáp án: {dap or 'không có'}")
        for h in tl.chon:
            typer.echo(f"     chọn: {h.uv.so_hieu} {h.uv.vi_tri}")
        for t in tl.trich:
            typer.echo(f"     trích: {t.doan.so_hieu} {t.doan.vi_tri}")


@eval_app.command("quy-dinh")
def eval_quy_dinh(
    file: Annotated[Path, typer.Option(help="File case.")] = Path("eval/cases.jsonl"),
):
    """Chấm luồng quy_dinh (GĐ 2.4 + 2.5) trên câu loai quy_dinh.

    tìm thấy: Điều đáp án trong 6 Điều ứng viên; đúng@1 / trong DS: đoạn trích đầu / một trong các
    đoạn thuộc Điều đáp án (cap_cham khoan: đúng khoản); trích lỗi: LLM chép sai nguyên văn 2 lần.
    """
    from qltt import danh_gia, tra_loi

    c = lay_cau_hinh()
    try:
        cases = [x for x in danh_gia.doc_cases(file) if x.loai == "quy_dinh"]
    except (FileNotFoundError, ValueError) as e:
        raise dung(f"Không đọc được {file}: {e}") from None
    typer.echo(f"Trả lời {len(cases)} câu quy_dinh bằng {c.llm_model}...")
    kq = []
    with ket_noi_db() as conn, loi_openai(c.llm_model):
        client = client_embed(c)
        for x in cases:
            da = danh_gia.giai(conn, x)
            try:
                tl = tra_loi.hoi(conn, client, c, x.cau_hoi)
            except ValueError as e:
                raise dung(str(e)) from None
            conn.commit()

            def trung(m, so, ht, k, x=x, da=da):
                return any(
                    (m, so, ht) == (a, b, h) and (x.cap_cham != "khoan" or kk is None or k == kk)
                    for a, b, h, kk in da.vi_tri
                )

            tim = any(any((h.khoa == (a, b, hh)) for a, b, hh, _ in da.vi_tri) for h in tl.dieu_gan)
            tr = [
                trung(t.doan.tvpl_id, t.doan.dieu_so, t.doan.dieu_suffix, t.doan.khoan_so)
                for t in tl.trich
            ]
            kq.append((x, tl, tim, tr))
    nhom = {"dev": [r for r in kq if not r[0].giu_lai], "giữ lại": [r for r in kq if r[0].giu_lai]}
    nhom["tất cả"] = kq
    typer.echo(
        f"\n{'nhóm':<10}{'n':>4}{'tìm thấy':>10}{'đúng@1':>9}{'trong DS':>10}{'TB đoạn':>9}"
        f"{'không_có':>10}{'trích lỗi':>11}{'sai loại':>10}{'giây TB':>9}"
    )
    for ten, rs in nhom.items():
        chinh = [r for r in rs if r[0].nhom == "chinh"]
        kc = [r for r in rs if r[0].nhom == "khong_co"]
        n = max(len(chinh), 1)
        typer.echo(
            f"{ten:<10}{len(rs):>4}{f'{sum(r[2] for r in chinh)}/{len(chinh)}':>10}"
            f"{f'{sum(bool(r[3]) and r[3][0] for r in chinh)}/{len(chinh)}':>9}"
            f"{f'{sum(any(r[3]) for r in chinh)}/{len(chinh)}':>10}"
            f"{sum(len(r[3]) for r in chinh) / n:>9.2f}"
            f"{f'{sum(not r[1].trich for r in kc)}/{len(kc)}':>10}"
            f"{sum(t.loi_trich for r in rs for t in r[1].trich):>11}"
            f"{sum(r[1].loai != 'quy_dinh' for r in rs):>10}"
            f"{sum(r[1].giay for r in rs) / max(len(rs), 1):>9.1f}"
        )
    sai = [r for r in nhom["dev"] if (r[0].nhom == "chinh" and not (r[3] and r[3][0]))
           or (r[0].nhom == "khong_co" and r[1].trich)]  # fmt: skip
    typer.echo(f"\nCâu dev sai đúng@1 ({len(sai)}; nhóm giữ lại chỉ in điểm tổng):")
    for x, tl, tim, _ in sai:
        dap = "; ".join(f"{cc.van_ban} Điều {cc.dieu} khoản {cc.khoan}" for cc in x.can_cu)
        typer.echo(f"  {x.id} [{tl.loai}] {x.cau_hoi}")
        uv = "có" if tim else "không có"
        typer.echo(f"     đáp án: {dap or 'không có'} ({uv} trong ứng viên)")
        for t in tl.trich:
            typer.echo(f"     trích: {t.doan.so_hieu} {t.doan.vi_tri} – {t.doan.dieu_ten[:70]}")
        if not tl.trich:
            typer.echo(f"     trích: (không) / {tl.so_ung_vien} đoạn ứng viên")


@eval_app.command("phan-loai")
def eval_phan_loai(
    file: Annotated[Path, typer.Option(help="File case.")] = Path("eval/cases.jsonl"),
    prompt: Annotated[str, typer.Option(help="Prompt có phân loại (hiện chỉ v5).")] = "v5",
    model_viet_lai: Annotated[
        str | None, typer.Option(help="Model (mặc định LLM_MODEL trong .env).")
    ] = None,
    tat_suy_nghi: Annotated[
        bool | None,
        typer.Option(
            "--tat-suy-nghi/--co-suy-nghi",
            help="Tắt/bật suy nghĩ (mặc định LLM_TAT_SUY_NGHI trong .env).",
        ),
    ] = None,
):
    """Đo phân loại câu hỏi (hanh_vi / quy_dinh / ngoai_pham_vi / khac) trên câu đời thường.

    In độ đúng và bảng nhầm lẫn theo dev / giữ lại; liệt kê câu sai của nhóm dev. Dùng chung cache
    với `eval tim-kiem --viet-lai --prompt v5`.
    """
    from qltt import danh_gia, viet_lai

    c = lay_cau_hinh()
    model = model_viet_lai or c.llm_model
    tat_sn = c.llm_tat_suy_nghi if tat_suy_nghi is None else tat_suy_nghi
    if prompt not in viet_lai.PHAN_LOAI:
        raise dung(f"--prompt phải là prompt có phân loại: {', '.join(sorted(viet_lai.PHAN_LOAI))}")
    try:
        cases = danh_gia.doc_cases(file)
    except (FileNotFoundError, ValueError) as e:
        raise dung(f"Không đọc được {file}: {e}") from None
    typer.echo(f"Phân loại {len(cases)} câu bằng {model}, prompt {prompt}...")
    with ket_noi_db() as conn:
        kq = chay_viet_lai(
            conn, client_embed(c), c, model, prompt, tat_sn, [x.cau_hoi for x in cases], "câu"
        )
    loai = list(danh_gia.LOAI_THU_TU)
    nhom = {
        "dev": [i for i, x in enumerate(cases) if not x.giu_lai],
        "giữ lại": [i for i, x in enumerate(cases) if x.giu_lai],
        "tất cả": list(range(len(cases))),
    }
    ngan = {"hanh_vi": "hv", "quy_dinh": "qđ", "ngoai_pham_vi": "ngoài", "khac": "khác"}
    ngan[None] = "lỗi"
    tieu_de = "thật / đoán"
    for ten, ids in nhom.items():
        dung_ = sum(kq[i].loai == cases[i].loai for i in ids)
        typer.echo(f"\n{ten}: đúng {dung_}/{len(ids)} ({dung_ / max(len(ids), 1):.0%})")
        typer.echo(f"  {tieu_de:<14}" + "".join(f"{ngan[b]:>7}" for b in [*loai, None]))
        for a in loai:
            hang = [sum(cases[i].loai == a and kq[i].loai == b for i in ids) for b in [*loai, None]]
            if sum(hang):
                typer.echo(f"  {a:<14}" + "".join(f"{n:>7}" for n in hang))
    sai = [i for i in nhom["dev"] if kq[i].loai != cases[i].loai]
    typer.echo(f"\nCâu dev phân loại sai ({len(sai)}; nhóm giữ lại chỉ in điểm tổng):")
    for i in sai:
        x = cases[i]
        typer.echo(f"  {x.id} [{x.loai} → {kq[i].loai}] {x.cau_hoi}")
        typer.echo(f"      viết lại: {'; '.join(kq[i].cau) or '-'}")


@eval_app.command("tim-kiem")
def eval_tim_kiem(
    file: Annotated[Path, typer.Option(help="File case.")] = Path("eval/cases.jsonl"),
    chi_tu_khoa: Annotated[bool, typer.Option("--chi-tu-khoa", help="Không gọi API.")] = False,
    tat_ca: Annotated[
        bool, typer.Option("--tat-ca", help="Tìm cả chunk quy phạm, không chỉ chunk xử phạt.")
    ] = False,
    co_viet_lai: Annotated[
        bool,
        typer.Option(
            "--viet-lai", help="Thêm nhánh viet_lai: LLM viết lại câu hỏi (lần đầu ~0,01-0,5 USD)."
        ),
    ] = False,
    prompt: Annotated[
        str | None,
        typer.Option(help="Phiên bản prompt viết lại: v1..v5 (mặc định theo .env)."),
    ] = None,
    model_viet_lai: Annotated[
        str | None, typer.Option(help="Model viết lại (mặc định LLM_MODEL trong .env).")
    ] = None,
    tat_suy_nghi: Annotated[
        bool | None,
        typer.Option(
            "--tat-suy-nghi/--co-suy-nghi",
            help="Tắt/bật suy nghĩ của model viết lại (mặc định LLM_TAT_SUY_NGHI trong .env).",
        ),
    ] = None,
):
    """Đo recall@5/8/20 và MRR của tìm kiếm trên bộ đánh giá; in câu trượt của nhóm dev.

    Nhóm giữ lại (giu_lai) chỉ in điểm tổng: không đọc từng câu để chỉnh tìm kiếm theo nó.
    """
    import json
    from datetime import datetime

    from qltt import danh_gia, tim_kiem, viet_lai

    c = lay_cau_hinh()
    model_vl = model_viet_lai or c.llm_model
    tat_sn = c.llm_tat_suy_nghi if tat_suy_nghi is None else tat_suy_nghi
    prompt_vl = prompt or c.viet_lai_prompt
    if prompt_vl not in viet_lai.PROMPT:
        raise dung(f"--prompt phải là một trong: {', '.join(viet_lai.PROMPT)}")
    if co_viet_lai and chi_tu_khoa:
        raise dung("--viet-lai cần gọi API, không dùng cùng --chi-tu-khoa.")
    try:
        cases = [x for x in danh_gia.doc_cases(file) if x.nhom == "chinh" and x.loai == "hanh_vi"]
    except (FileNotFoundError, ValueError) as e:
        raise dung(f"Không đọc được {file}: {e}") from None
    kieu = {"doi_thuong": "cau_hoi", "nguyen_van": "cau_hoi_nguyen_van"}
    typer.echo(f"Đọc {len(cases)} case, kết nối DB...")
    with ket_noi_db() as conn:
        dap_an = [danh_gia.giai(conn, x) for x in cases]
        if loi := [d for d in dap_an if d.loi]:
            raise dung(f"{len(loi)} case có căn cứ lỗi. Chạy `qltt eval kiem-tra` trước.")
        vt = {
            r[0]: (r[1], r[2], r[3] or "", r[4])
            for r in conn.execute("SELECT id, tvpl_id, dieu_so, dieu_suffix, khoan_so FROM chunk")
        }
        vec = {k: [None] * len(cases) for k in kieu}
        if not chi_tu_khoa:
            typer.echo(f"Vector câu hỏi ({c.embed_model}, có cache)...")
            client = client_embed(c)
            with loi_openai(c.embed_model):
                for k, truong in kieu.items():
                    cau = [getattr(x, truong) for x in cases]
                    vec[k], token = tim_kiem.vector_cau_hoi(conn, client, c.embed_model, cau)
                    if token:
                        typer.echo(f"Embed {len(cau)} câu {k}: {token} token")
            conn.commit()

        ket_qua = []  # (kieu, nhanh, case, đáp án, danh sách id)
        typer.echo(f"Tìm {2 * len(cases)} câu (câu gốc)...")
        for k, truong in kieu.items():
            for x, da, v in zip(cases, dap_an, vec[k], strict=True):
                loc = tim_kiem.Loc(vai_tro=None) if tat_ca else tim_kiem.XU_PHAT
                tim = tim_kiem.tim(conn, getattr(x, truong), v, loc)
                for nhanh, ids in tim.items():
                    ket_qua.append((k, nhanh, x, da, ids))

        viet = {}  # (kiểu, id) → các câu viết lại
        if co_viet_lai:
            client = client_embed(c)
            typer.echo(
                f"Viết lại {2 * len(cases)} câu bằng {model_vl}, prompt {prompt_vl},"
                f" {'tắt' if tat_sn else 'có'} suy nghĩ..."
            )
            for k, truong in kieu.items():
                kq = chay_viet_lai(
                    conn, client, c, model_vl, prompt_vl, tat_sn,
                    [getattr(x, truong) for x in cases], k,
                )  # fmt: skip
                viet.update({(k, x.id): r.cau for x, r in zip(cases, kq, strict=True)})
            moi = list(dict.fromkeys(q for ds in viet.values() for q in ds))
            with loi_openai(c.embed_model):
                vmoi, _ = tim_kiem.vector_cau_hoi(conn, client, c.embed_model, moi)
            conn.commit()
            vq = dict(zip(moi, vmoi, strict=True))
            loc = tim_kiem.Loc(vai_tro=None) if tat_ca else tim_kiem.XU_PHAT
            typer.echo("Tìm lại bằng câu gốc + câu viết lại...")
            for k, truong in kieu.items():
                for j, (x, da, v) in enumerate(zip(cases, dap_an, vec[k], strict=True), 1):
                    if j % 10 == 0:
                        typer.echo(f"  {k}: {j}/{len(cases)}")
                    them = viet[(k, x.id)]
                    ids = tim_kiem.tim_nhieu(
                        conn, [getattr(x, truong), *them], [v, *(vq[q] for q in them)], loc
                    )
                    ket_qua.append((k, "viet_lai", x, da, ids))

        def hang(r):
            return danh_gia.hang([vt[i] for i in r[4]], r[3])

        nhom = {
            "dev": lambda x: not x.giu_lai,
            "giữ lại": lambda x: x.giu_lai,
            "tất cả": lambda x: True,
        }
        chinh = "viet_lai" if co_viet_lai else "lai"
        dong = [(nh, k, n) for nh in dict.fromkeys(("lai", chinh)) for k in kieu for n in nhom]
        dong += [(nh, k, "dev") for nh in ("vector", "tu_khoa") if nh != "vector" or not chi_tu_khoa
                 for k in kieu]  # fmt: skip
        typer.echo(
            f"\nModel: {'(không)' if chi_tu_khoa else c.embed_model}; "
            f"tìm trong: {'mọi chunk' if tat_ca else 'chunk xử phạt'}"
        )
        typer.echo(
            "chunk@k: đáp án trong k chunk đầu; Điều@k: Điều đáp án trong k hành vi ứng viên đầu"
        )
        typer.echo(
            f"{'nhánh / câu hỏi / nhóm':<32}{'n':>4}{'@5':>7}{'@8':>7}{'@20':>7}{'MRR':>7}"
            f"{'Điều@3':>8}{'Điều@5':>8}{'Điều@8':>8}{'Điều@10':>8}{'Đ@5':>7}"
        )
        for nhanh, k, ten_nhom in dong:
            hs = [hang(r) for r in ket_qua if r[0] == k and r[1] == nhanh and nhom[ten_nhom](r[2])]
            m = danh_gia.tong_hop(hs)
            hd = [
                danh_gia.hang_dieu(danh_gia.gom_dieu([vt[i] for i in r[4]]), r[3])
                for r in ket_qua
                if r[0] == k and r[1] == nhanh and nhom[ten_nhom](r[2])
            ]
            md = danh_gia.tong_hop(hd, (3, 5, 8, 10))
            typer.echo(
                f"{nhanh + ' / ' + k + ' / ' + ten_nhom:<32}{len(hs):>4}"
                + "".join(f"{m[f'recall@{n}']:>7.2f}" for n in (5, 8, 20))
                + f"{m['mrr']:>7.2f}"
                + "".join(f"{md[f'recall@{n}']:>8.2f}" for n in (3, 5, 8, 10))
                + f"{f'{sum(1 for h in hd if h and h <= 5)}/{len(hd)}':>7}"
            )

        theo_nhanh = {(r[0], r[1], r[2].id): r for r in ket_qua}

        def hang_d(r):
            return danh_gia.hang_dieu(danh_gia.gom_dieu([vt[i] for i in r[4]]), r[3])

        for k in kieu:
            truot = [
                r
                for r in ket_qua
                if r[0] == k and r[1] == chinh and not r[2].giu_lai and (hang_d(r) or 99) > 5
            ]
            typer.echo(f"\nĐiều đáp án ngoài 5 hành vi đầu ({chinh} / {k} / dev): {len(truot)}")
            for r in truot:
                x = r[2]
                dieu = danh_gia.gom_dieu([vt[i] for i in r[4]])[:3]
                ten = {
                    (a, b, s_): f"{so} Điều {b}{s_}"
                    for a, b, s_, so in conn.execute(
                        "SELECT c.tvpl_id, c.dieu_so, c.dieu_suffix, v.so_hieu FROM chunk c"
                        " JOIN van_ban v USING (tvpl_id) WHERE c.cap = 'dieu'"
                        " AND (c.tvpl_id, c.dieu_so) IN"
                        " (SELECT * FROM unnest(%s::int[], %s::int[]))",
                        [[d[0] for d in dieu], [d[1] for d in dieu]],
                    )
                }
                hv, ht = (hang_d(theo_nhanh[(k, nh, x.id)]) for nh in ("vector", "tu_khoa"))
                typer.echo(f'  {x.id}  "{getattr(x, kieu[k])}"')
                for q in viet.get((k, x.id), []):
                    typer.echo(f"     viết lại: {q}")
                can_cu = "; ".join(
                    f"{cc.van_ban} Điều {cc.dieu}"
                    + (f" khoản {', '.join(map(str, cc.khoan))}" if cc.khoan else "")
                    for cc in x.can_cu
                )
                typer.echo(
                    f"     đáp án: {can_cu} | hạng Điều {chinh} {hang_d(r) or 'không có'},"
                    f" vector {hv or 'không có'}, từ khóa {ht or 'không có'}"
                )
                typer.echo("     3 Điều đầu: " + " | ".join(ten.get(d, str(d)) for d in dieu))

    thu_muc = Path("data/eval")
    thu_muc.mkdir(parents=True, exist_ok=True)
    ra = thu_muc / f"tim_kiem_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    with ra.open("w", encoding="utf-8") as f:
        for k, nhanh, x, da, ids in ket_qua:
            f.write(
                json.dumps(
                    {
                        "id": x.id,
                        "kieu": k,
                        "nhanh": nhanh,
                        "hang": hang((k, nhanh, x, da, ids)),
                        "top20": ids[:20],
                    },
                    ensure_ascii=False,
                )  # fmt: skip
                + "\n"
            )
    typer.echo(f"\nChi tiết: {ra}")


def main() -> None:
    for luong in (sys.stdout, sys.stderr):
        # Windows: in được tiếng Việt cả khi đầu ra bị chuyển hướng sang file
        luong.reconfigure(encoding="utf-8")
    try:
        app()
    except psycopg.errors.LockNotAvailable:
        typer.echo(
            "Postgres: chờ khóa quá 15 giây. Một phiên khác đang giữ transaction dở (lệnh qltt"
            " cũ chưa thoát hẳn, hoặc DBeaver ở chế độ commit tay). Tắt chúng rồi chạy lại.",
            err=True,
        )
        sys.exit(1)
