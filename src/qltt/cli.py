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
        g = gate.kiem(vb, str(d["so_hieu"]), ngay)
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
    """Đọc sheet + Drive, tải file mới, parse, ghi vào DB, tính lại trạng thái. Chưa embed."""
    from datetime import date

    from qltt import google_io, kho_file, nap

    c = kiem_cau_hinh_google()
    with loi_google():
        dong = google_io.doc_sheet()
        files = google_io.liet_ke_file()
    # mỗi mã một file: lấy bản sửa gần nhất trên Drive
    theo_ma: dict[int, dict] = {}
    for f in sorted(files, key=lambda f: f.get("modifiedTime", "")):
        if (m := tvpl.id_tu_ten_file(f["name"])) is not None:
            theo_ma[m] = f
    kq_tai = kho_file.dong_bo_file(list(theo_ma.values()), c.thu_muc_raw, google_io.tai_noi_dung)
    if kq_tai.moi:
        typer.echo(f"Tải mới {len(kq_tai.moi)} file từ Drive.")

    bao: dict[str, list[str]] = {"Lỗi sheet": [], "Dòng chưa có file": [], "Trượt gate": []}
    so_nap = so_giu = so_chunk = 0
    ma_sheet = set()
    with ket_noi_db() as conn:
        da_co = dict(conn.execute("SELECT tvpl_id, file_hash FROM van_ban").fetchall())
        for d in dong:
            ma = tvpl.id_tu_link(str(d["link_tvpl"]))
            if ma is None:
                bao["Lỗi sheet"].append(f"dòng {d['dong']}: link không có mã TVPL")
                continue
            ma_sheet.add(ma)
            ds = nap.dong_tu_sheet(d, ma, google_io.ngay_tu_serial)
            if isinstance(ds, str):
                bao["Lỗi sheet"].append(ds)
                continue
            f = theo_ma.get(ma)
            if f is None:
                bao["Dòng chưa có file"].append(f"{ds.so_hieu} (dòng {ds.dong})")
                continue
            md5 = kho_file.ten_ban_sao(f)
            if da_co.get(ma) == md5 and not lam_lai:
                nap.cap_nhat_dong(conn, ds)
                so_giu += 1
                continue
            kq = nap.nap_van_ban(
                conn, ds, kho_file.duong_dan(c.thu_muc_raw, ma, md5), md5, f.get("id")
            )
            if kq.loi:
                bao["Trượt gate"].append(f"{ds.so_hieu}: " + "; ".join(kq.loi[:3]))
            else:
                so_nap += 1
                so_chunk += kq.so_chunk
        conn.commit()
        nap.tinh_lai(conn, date.today())
        tk = nap.thong_ke(conn)

    bao["File chưa có dòng sheet"] = [f["name"] for m, f in theo_ma.items() if m not in ma_sheet]
    typer.echo(f"Nạp/parse lại: {so_nap} văn bản, {so_chunk} chunk. File không đổi: {so_giu}.")
    for nhan, ds in bao.items():
        if ds:
            typer.echo(f"{nhan} ({len(ds)}):")
            for x in ds:
                typer.echo(f"  {x}")
    tt = ", ".join(f"{k} {v}" for k, v in sorted(tk["trang_thai"].items()))
    typer.echo(
        f"Trong DB: {tk['van_ban']} văn bản ({tt}); {tk['dung_de_tra']} dùng để tra; "
        f"{tk['chunk']} chunk, {tk['chunk_tim_kiem']} chunk sẽ được tìm kiếm."
    )


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
                    cau += viet_lai.viet_lai(conn, client, c.llm_model, cau_hoi).cau
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
            "--viet-lai", help="Thêm nhánh viet_lai: LLM viết lại câu hỏi (lần đầu ~0,03 USD)."
        ),
    ] = False,
):
    """Đo recall@5/8/20 và MRR của tìm kiếm trên bộ đánh giá; in câu trượt của nhóm dev.

    Nhóm giữ lại (giu_lai) chỉ in điểm tổng: không đọc từng câu để chỉnh tìm kiếm theo nó.
    """
    import json
    from datetime import datetime

    from qltt import danh_gia, tim_kiem, viet_lai

    c = lay_cau_hinh()
    if co_viet_lai and chi_tu_khoa:
        raise dung("--viet-lai cần gọi API, không dùng cùng --chi-tu-khoa.")
    try:
        cases = [x for x in danh_gia.doc_cases(file) if x.nhom == "chinh"]
    except (FileNotFoundError, ValueError) as e:
        raise dung(f"Không đọc được {file}: {e}") from None
    kieu = {"doi_thuong": "cau_hoi", "nguyen_van": "cau_hoi_nguyen_van"}
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
            vao = ra_ = goi = 0
            typer.echo(f"Viết lại {2 * len(cases)} câu bằng {c.llm_model}...")
            with loi_openai(c.llm_model):
                for k, truong in kieu.items():
                    for j, x in enumerate(cases, 1):
                        if j % 10 == 0:
                            typer.echo(f"  {k}: {j}/{len(cases)}")
                        kq = viet_lai.viet_lai(conn, client, c.llm_model, getattr(x, truong))
                        viet[(k, x.id)] = kq.cau
                        vao, ra_, goi = (
                            vao + kq.token_vao,
                            ra_ + kq.token_ra,
                            goi + (not kq.tu_cache),
                        )
            conn.commit()
            moi = list(dict.fromkeys(q for ds in viet.values() for q in ds))
            with loi_openai(c.embed_model):
                vmoi, _ = tim_kiem.vector_cau_hoi(conn, client, c.embed_model, moi)
            conn.commit()
            vq = dict(zip(moi, vmoi, strict=True))
            phi = vao / 1e6 * c.llm_gia_1m_vao + ra_ / 1e6 * c.llm_gia_1m_ra
            typer.echo(
                f"Viết lại bằng {c.llm_model}: {goi} lần gọi mới, {vao:,} + {ra_:,} token,"
                f" ~{phi:.3f} USD; {sum(not v for v in viet.values())} câu LLM không trả được"
            )
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
            f"{'Điều@3':>8}{'Điều@5':>8}{'trúng@20':>10}"
        )
        for nhanh, k, ten_nhom in dong:
            hs = [hang(r) for r in ket_qua if r[0] == k and r[1] == nhanh and nhom[ten_nhom](r[2])]
            m = danh_gia.tong_hop(hs)
            hd = [
                danh_gia.hang_dieu(danh_gia.gom_dieu([vt[i] for i in r[4]]), r[3])
                for r in ket_qua
                if r[0] == k and r[1] == nhanh and nhom[ten_nhom](r[2])
            ]
            md = danh_gia.tong_hop(hd, (3, 5))
            trung = sum(1 for h in hs if h and h <= 20)
            typer.echo(
                f"{nhanh + ' / ' + k + ' / ' + ten_nhom:<32}{len(hs):>4}"
                + "".join(f"{m[f'recall@{n}']:>7.2f}" for n in (5, 8, 20))
                + f"{m['mrr']:>7.2f}"
                + "".join(f"{md[f'recall@{n}']:>8.2f}" for n in (3, 5))
                + f"{f'{trung}/{len(hs)}':>10}"
            )

        theo_nhanh = {(r[0], r[1], r[2].id): r for r in ket_qua}
        for k in kieu:
            truot = [
                r
                for r in ket_qua
                if r[0] == k and r[1] == chinh and not r[2].giu_lai and (hang(r) or 99) > 20
            ]
            typer.echo(f"\nTrượt top 20 ({chinh} / {k} / dev): {len(truot)}")
            for r in truot:
                x = r[2]
                top3 = tim_kiem.chi_tiet(conn, r[4][:3])
                hv, ht = (hang(theo_nhanh[(k, nh, x.id)]) for nh in ("vector", "tu_khoa"))
                typer.echo(f'  {x.id}  "{getattr(x, kieu[k])}"')
                for q in viet.get((k, x.id), []):
                    typer.echo(f"     viết lại: {q}")
                can_cu = "; ".join(
                    f"{cc.van_ban} Điều {cc.dieu}"
                    + (f" khoản {', '.join(map(str, cc.khoan))}" if cc.khoan else "")
                    for cc in x.can_cu
                )
                typer.echo(
                    f"     đáp án: {can_cu} | hạng lai {hang(r) or '>50'},"
                    f" vector {hv or '>50'}, từ khóa {ht or '>50'}"
                )
                typer.echo("     top 3:  " + " | ".join(f"{d.so_hieu} {d.duong_dan}" for d in top3))

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
    app()
