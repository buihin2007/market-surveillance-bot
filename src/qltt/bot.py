"""Bot Telegram (GĐ 4.1 + 4.2): chú hỏi tự do, bot trả lời (HTML) kèm 2 nút:
"📋 Quy định tại" (căn cứ đầy đủ văn phong biên bản, hien_thi.quy_dinh_tai; dựng lúc trả lời, lưu
chat_log.ket_qua['qdt']) và "⚠️ Báo sai". Nút Nguyên văn đã bỏ (12/11); callback "nv:" còn xử lý
cho tin cũ.
- /dongbo: đồng bộ Sheet / Drive → DB như `qltt dong-bo` (cả embed), báo cáo về chat; người chạy
  không phải admin thì báo cả admin. /vanban <số hiệu>: tình trạng văn bản trong kho (GĐ 4.3).

- Chỉ chat_id trong TELEGRAM_CHO_PHEP được dùng; người khác: bot im lặng, chỉ ghi log chat_id (để
  ikm lấy chat_id của chú lúc đầu).
- Mỗi câu hỏi: tin "Đang tra cứu…" → chạy đồ thị trong thread riêng (DB, API là code đồng bộ) →
  sửa tin đó thành câu trả lời (dài thì tách nhiều tin). Quá THOI_GIAN_TOI_DA giây thì báo chú hỏi
  lại; lỗi thì báo chú + nhắn ikm.
- Báo sai 2 bước (ikm chốt 11/11): nút loại lỗi (lời của chú, nhat_ky.kieu_cho) → hỏi "Căn cứ đúng
  là gì?" (tin ForceReply: chú gõ là thành trả lời; hoặc bấm Bỏ qua). Mỗi bước nhắn ikm.
- Câu trả lời HTML (hien_thi.telegram: mọi chữ văn bản đều escape); tin khác chữ thường.
"""

import asyncio
import logging
import traceback

import psycopg
from telegram import (
    BotCommand,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from qltt import db, embed, hien_thi, nhat_ky, sua_doi, tra_loi

log = logging.getLogger("qltt.bot")

GIOI_HAN = 4000  # Telegram cho tối đa 4096 ký tự mỗi tin
THOI_GIAN_TOI_DA = 90  # giây cho một câu hỏi (p90 đo được 5 s; API đôi khi chậm bất thường)
QUA_LAU = "Tra cứu quá lâu (máy chủ AI chậm). Chú hỏi lại sau ít phút."
CO_LOI = "Có lỗi khi tra cứu, đã báo người quản trị. Chú thử lại sau."

GIOI_THIEU = """Chào chú. Chú gõ tình huống hoặc câu hỏi bình thường, không cần lệnh, ví dụ:
bán bánh kẹo trị giá 7 triệu không có nhãn
(Nêu trị giá / số lượng, cá nhân hay tổ chức, loại hàng thì bot chọn đúng mức phạt hơn.)

CÁC LỆNH (gõ liền, có dấu /, hoặc bấm nút ☰ Menu cạnh ô gõ):
/start – bắt đầu, xem lời chào này
/help – xem lại hướng dẫn này
/dongbo – gõ khi chú vừa sửa sheet hoặc thêm văn bản mới vào Drive: bot nạp phần thay đổi rồi \
gửi báo cáo (vài chục giây đến vài phút). Trong lúc đồng bộ chú vẫn hỏi bot bình thường.
/vanban <số hiệu> – xem văn bản có đang được tra không (hay tra qua văn bản hợp nhất nào), bị \
văn bản nào sửa đổi, bổ sung, tạm dừng. Ví dụ: /vanban 98/2020/NĐ-CP (gõ ND-CP hoặc một phần \
số hiệu như 98/2020 cũng được)

CÁC NÚT dưới câu trả lời:
📋 Quy định tại – căn cứ đầy đủ (ghi tới điểm, kèm văn bản sửa đổi), chạm để chép vào biên bản; \
cuối tin có link Thư viện Pháp luật
⚠️ Báo sai – chọn chỗ sai, rồi gõ căn cứ đúng vào ô trả lời bot mở sẵn (hoặc bấm Bỏ qua)

Dòng 📌 là căn cứ rút gọn; dòng ⚠️ là cảnh báo quy định đã bị sửa đổi, bãi bỏ, tạm dừng.
Bot không trả lời thẩm quyền xử phạt, trách nhiệm hình sự; luôn đối chiếu văn bản trước khi lập \
biên bản."""
TOI_DA_VAN_BAN = 10
HTML = {"parse_mode": ParseMode.HTML, "link_preview_options": LinkPreviewOptions(is_disabled=True)}


# ---------- phần thuần (test được, không cần Telegram) ----------


def chia_tin(van_ban: str, gioi_han: int = GIOI_HAN) -> list[str]:
    """Tách theo đoạn (dòng trống), rồi theo dòng, cuối cùng cắt cứng; mỗi phần ≤ gioi_han."""
    phan: list[str] = []
    hien = ""
    for doan in van_ban.split("\n\n"):
        manh = [doan]
        if len(doan) > gioi_han:
            manh, dong = [], ""
            for d in doan.split("\n"):
                while len(d) > gioi_han:
                    if dong:
                        manh.append(dong)
                        dong = ""
                    manh.append(d[:gioi_han])
                    d = d[gioi_han:]
                if dong and len(dong) + 1 + len(d) > gioi_han:
                    manh.append(dong)
                    dong = d
                else:
                    dong = f"{dong}\n{d}" if dong else d
            if dong:
                manh.append(dong)
        for m in manh:
            if hien and len(hien) + 2 + len(m) > gioi_han:
                phan.append(hien)
                hien = m
            else:
                hien = f"{hien}\n\n{m}" if hien else m
    if hien:
        phan.append(hien)
    return phan or [""]


def ban_phim_tra_loi(ma: int, co_quy_dinh: bool = True) -> InlineKeyboardMarkup:
    """Chú chốt 12/11: [📋 Quy định tại] [⚠️ Báo sai] (không có căn cứ thì chỉ Báo sai)."""
    hang = [InlineKeyboardButton("⚠️ Báo sai", callback_data=f"bs:{ma}")]
    if co_quy_dinh:
        hang.insert(0, InlineKeyboardButton("📋 Quy định tại", callback_data=f"qd:{ma}"))
    return InlineKeyboardMarkup([hang])


def ban_phim_loai_loi(ma: int, loai_ket_qua: str | None) -> InlineKeyboardMarkup:
    hang = [
        [InlineKeyboardButton(nhat_ky.KIEU[k], callback_data=f"bk:{ma}:{k}")]
        for k in nhat_ky.kieu_cho(loai_ket_qua)
    ]
    hang.append([InlineKeyboardButton("Hủy", callback_data=f"bk:{ma}:huy")])
    return InlineKeyboardMarkup(hang)


def tra_loi_va_ghi(conn: psycopg.Connection, client, c, cau_hoi: str, nguoi: int) -> dict:
    tl = tra_loi.hoi(conn, client, c, cau_hoi)
    ma = nhat_ky.ghi(conn, tl, c, kenh="telegram", nguoi=nguoi)
    qdt = hien_thi.quy_dinh_tai(conn, tl)
    if qdt:
        conn.execute(
            "UPDATE chat_log SET ket_qua = coalesce(ket_qua, '{}')"
            " || jsonb_build_object('qdt', %s::text) WHERE id = %s",
            [qdt, ma],
        )
    return {
        "ma": ma,
        "van_ban": tl.van_ban,
        "html": hien_thi.telegram(conn, tl),
        "co_quy_dinh": bool(qdt),
        "loai_ket_qua": nhat_ky.loai_ket_qua(tl),
        "co_nguyen_van": bool(tl.chon or tl.trich),
        "giay": tl.giay,
    }


def nguyen_van(conn: psycopg.Connection, ma: int) -> str:
    """Toàn văn các Điều bot đã chọn / trích trong câu trả lời #ma."""
    r = conn.execute("SELECT ket_qua FROM chat_log WHERE id = %s", [ma]).fetchone()
    if not r:
        return "Không tìm thấy câu trả lời này."
    kq = r[0] or {}
    da, phan = set(), []
    for x in kq.get("chon", []) + kq.get("trich", []):
        khoa = (x["tvpl_id"], x["dieu"])
        if khoa in da:
            continue
        da.add(khoa)
        so, ht = (
            int("".join(ch for ch in x["dieu"] if ch.isdigit())),
            x["dieu"].lstrip("0123456789"),
        )
        nd = conn.execute(
            "SELECT noi_dung FROM chunk WHERE tvpl_id = %s AND dieu_so = %s AND dieu_suffix = %s"
            " AND cap = 'dieu'",
            [x["tvpl_id"], so, ht],
        ).fetchone()
        if nd:
            phan.append(f"{x['so_hieu']}\n{nd[0].strip()}")
        for cb in sua_doi.canh_bao(conn, x["tvpl_id"], so, ht, x.get("khoan")):
            khoa_sd = (cb.so_hieu, cb.vi_tri_tu)
            if khoa_sd in da or not cb.noi_dung_moi:
                continue
            da.add(khoa_sd)
            phan.append(
                f"⚠ Chữ mới theo {cb.vi_tri_tu} {cb.so_hieu} ({cb.mo_ta}):\n{cb.noi_dung_moi}"
            )
    return "\n\n".join(phan) or "Câu trả lời này không trích Điều nào."


def quy_dinh_tai(conn: psycopg.Connection, ma: int) -> str:
    """Tin HTML "📋 Quy định tại" đã dựng lúc trả lời câu #ma."""
    r = conn.execute("SELECT ket_qua->>'qdt' FROM chat_log WHERE id = %s", [ma]).fetchone()
    return r[0] if r and r[0] else "Câu trả lời này không có căn cứ để trích."


def tra_van_ban(conn: psycopg.Connection, tim: str) -> str:
    """Tin HTML cho /vanban."""
    from html import escape

    from qltt import dong_bo

    if not tim.strip():
        ds = dong_bo.tinh_trang(conn)
        tra = sum(x.ly_do == "dùng để tra" for x in ds)
        return (
            f"Kho có {len(ds)} văn bản, {tra} văn bản đang dùng để tra (văn bản gốc đã có VBHN thì"
            " tra qua VBHN).\nGõ /vanban kèm số hiệu để xem chi tiết, vd: /vanban 98/2020/NĐ-CP"
        )
    ds = dong_bo.tinh_trang(conn, tim)
    if not ds:
        return (
            f"Không có văn bản nào khớp «{escape(tim)}». Văn bản chưa có trên sheet và Drive thì"
            " bot chưa tra được: chú thêm vào rồi gõ /dongbo."
        )
    khoi = []
    for x in ds[:TOI_DA_VAN_BAN]:
        ten = x.ten[:1] + x.ten[1:].lower()
        dong = [
            f'📄 <a href="{escape(x.link, quote=True)}">{escape(x.so_hieu)}</a>: '
            f"<b>{escape(x.ly_do)}</b>",
            escape(ten[:160]),
        ]
        if len(ds) <= 3:
            dong += [f"• {escape(d)}" for d in dong_bo.van_ban_sua(conn, x.tvpl_id)]
        khoi.append("\n".join(dong))
    if len(ds) > TOI_DA_VAN_BAN:
        khoi.append(f"… và {len(ds) - TOI_DA_VAN_BAN} văn bản khác. Chú gõ số hiệu cụ thể hơn.")
    elif len(ds) > 3:
        khoi.append("Gõ số hiệu đầy đủ để xem văn bản sửa đổi, tạm dừng.")
    return "\n\n".join(khoi)


def dong_bo_ngay(conn: psycopg.Connection, c, client) -> str:
    """/dongbo: như `qltt dong-bo` (đọc sheet, Drive, nạp, tính lại, embed), trả báo cáo."""
    from datetime import date

    from qltt import dong_bo, google_io

    dong = google_io.doc_sheet()
    files = google_io.liet_ke_file()
    ham = dong_bo.ham_embed(client, c.embed_model, c.embed_gia_1m_token)
    kq = dong_bo.chay(
        conn, dong, files, c.thu_muc_raw, google_io.tai_noi_dung, google_io.ngay_tu_serial,
        date.today(), embed_fn=ham,
    )  # fmt: skip
    return dong_bo.bao_cao(kq)


def loi_dong_bo(e: Exception) -> str | None:
    """Lỗi Google dễ hiểu cho chú; None: lỗi khác (báo chung)."""
    from googleapiclient.errors import HttpError

    from qltt import google_io

    if isinstance(e, google_io.LoiTieuDe):
        return f"Dòng tiêu đề của sheet chưa đúng: {e}. Chú sửa sheet rồi gõ /dongbo lại."
    if isinstance(e, HttpError):
        return f"Không đọc được sheet hoặc Drive (lỗi {e.status_code}). Đã báo người quản trị."
    return None


def loai_ket_qua(conn: psycopg.Connection, ma: int) -> str | None:
    r = conn.execute("SELECT loai_ket_qua FROM chat_log WHERE id = %s", [ma]).fetchone()
    return r[0] if r else None


def ghi_bao_sai(conn: psycopg.Connection, ma: int, kieu: str, nguoi: int) -> tuple[int, str]:
    i = nhat_ky.bao_sai(conn, ma, "", nguoi, kieu)
    return i, nhat_ky.tom_tat(conn, i)


def ghi_can_cu(conn: psycopg.Connection, bao_sai_id: int, ly_do: str) -> str:
    nhat_ky.them_ly_do(conn, bao_sai_id, ly_do)
    return nhat_ky.tom_tat(conn, bao_sai_id)


# ---------- Telegram ----------


class Bot:
    def __init__(self, c):
        self.c = c
        # timeout ngắn, ít lần thử: chú không phải chờ 2 phút khi API treo
        self.client = embed.tao_client(
            c.llm_api_key.get_secret_value(), c.llm_base_url, max_retries=2, timeout=40
        )

    def _chay(self, ham, *args):
        """Chạy hàm DB đồng bộ với một kết nối riêng (gọi trong thread)."""
        with db.ket_noi() as conn:
            kq = ham(conn, *args)
            conn.commit()
            return kq

    async def _bao_admin(self, ctx: ContextTypes.DEFAULT_TYPE, chu: str) -> None:
        if self.c.telegram_admin:
            for p in chia_tin(chu):
                await ctx.bot.send_message(self.c.telegram_admin, p)

    async def bat_dau(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(GIOI_THIEU)

    async def hoi(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        cho = ctx.chat_data.get("cho_can_cu", {})
        tra_loi_cho = msg.reply_to_message.message_id if msg.reply_to_message else None
        if tra_loi_cho in cho:  # chú gõ căn cứ đúng (trả lời tin ForceReply)
            bao_sai_id = cho.pop(tra_loi_cho)
            tom = await asyncio.to_thread(self._chay, ghi_can_cu, bao_sai_id, msg.text)
            await msg.reply_text("Cảm ơn chú, đã ghi nhận căn cứ.")
            await self._bao_admin(ctx, tom)
            return
        trang_thai = await msg.reply_text("⏳ Đang tra cứu…")
        await ctx.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
        try:
            kq = await asyncio.wait_for(
                asyncio.to_thread(
                    self._chay, lambda conn: tra_loi_va_ghi(
                        conn, self.client, self.c, msg.text, msg.chat_id
                    )
                ),
                THOI_GIAN_TOI_DA,
            )  # fmt: skip
        except TimeoutError:
            await trang_thai.edit_text(QUA_LAU)
            await self._bao_admin(ctx, f"⏱ Quá {THOI_GIAN_TOI_DA} s: {msg.text}")
            return
        except Exception:
            await trang_thai.edit_text(CO_LOI)
            await self._bao_admin(
                ctx, f"❌ Lỗi khi trả lời: {msg.text}\n{traceback.format_exc()[-3000:]}"
            )
            log.exception("lỗi khi trả lời %r", msg.text)
            return
        phan = chia_tin(f"{kq['html']}\n\n<i>mã #{kq['ma']}</i>")
        ban_phim = ban_phim_tra_loi(kq["ma"], kq["co_quy_dinh"])
        await trang_thai.edit_text(
            phan[0], reply_markup=ban_phim if len(phan) == 1 else None, **HTML
        )
        for i, p in enumerate(phan[1:], 2):
            await msg.reply_text(p, reply_markup=ban_phim if i == len(phan) else None, **HTML)

    async def van_ban(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tim = " ".join(ctx.args or [])
        chu = await asyncio.to_thread(self._chay, tra_van_ban, tim)
        for p in chia_tin(chu):
            await update.effective_message.reply_text(p, **HTML)

    async def dong_bo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        trang_thai = await msg.reply_text(
            "⏳ Đang đồng bộ sheet và Drive… (vài chục giây đến vài phút)"
        )
        try:
            bc = await asyncio.to_thread(
                self._chay, lambda conn: dong_bo_ngay(conn, self.c, self.client)
            )
        except Exception as e:
            log.exception("lỗi đồng bộ")
            await trang_thai.edit_text(loi_dong_bo(e) or CO_LOI)
            await self._bao_admin(ctx, f"❌ Lỗi /dongbo:\n{traceback.format_exc()[-3000:]}")
            return
        phan = chia_tin(bc)
        await trang_thai.edit_text(phan[0])
        for p in phan[1:]:
            await msg.reply_text(p)
        if msg.chat_id != self.c.telegram_admin:
            await self._bao_admin(ctx, f"🔄 /dongbo (chat {msg.chat_id}):\n{bc}")

    async def nut(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        await q.answer()
        loai, *phan = q.data.split(":")
        if loai == "qd":
            chu = await asyncio.to_thread(self._chay, quy_dinh_tai, int(phan[0]))
            for p in chia_tin(f"{chu}\n\n<i>mã #{phan[0]}</i>"):
                await q.message.reply_text(p, **HTML)
        elif loai == "nv":
            chu = await asyncio.to_thread(self._chay, nguyen_van, int(phan[0]))
            for p in chia_tin(chu):
                await q.message.reply_text(p)
        elif loai == "bs":
            ma = int(phan[0])
            lkq = await asyncio.to_thread(self._chay, loai_ket_qua, ma)
            await q.message.reply_text(
                "Câu trả lời sai ở chỗ nào?", reply_markup=ban_phim_loai_loi(ma, lkq)
            )
        elif loai == "bk":
            ma, kieu = int(phan[0]), phan[1]
            if kieu == "huy":
                await q.edit_message_text("Đã hủy báo sai.")
                return
            bao_sai_id, tom = await asyncio.to_thread(
                self._chay, ghi_bao_sai, ma, kieu, q.message.chat_id
            )
            await q.edit_message_text(
                f"Đã ghi nhận: {nhat_ky.KIEU[kieu]}.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Bỏ qua căn cứ", callback_data=f"bq:{bao_sai_id}")]]
                ),
            )
            hoi = await q.message.reply_text(
                "Căn cứ đúng là gì? Chú gõ ngắn (vd: Điều 11 NĐ 98/2020), hoặc bấm Bỏ qua.",
                reply_markup=ForceReply(input_field_placeholder="Điều …, khoản …, nghị định …"),
            )
            ctx.chat_data.setdefault("cho_can_cu", {})[hoi.message_id] = bao_sai_id
            await self._bao_admin(ctx, tom)
        elif loai == "bq":
            bao_sai_id = int(phan[0])
            cho = ctx.chat_data.get("cho_can_cu", {})
            for k in [k for k, v in cho.items() if v == bao_sai_id]:
                cho.pop(k)
            await q.edit_message_text("Cảm ơn chú, đã ghi nhận.")

    async def nguoi_la(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        log.warning(
            "chat_id %s (%s) chưa được phép; thêm vào TELEGRAM_CHO_PHEP nếu là người dùng",
            update.effective_chat.id if update.effective_chat else "?",
            u.full_name if u else "?",
        )

    async def loi(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("lỗi bot", exc_info=ctx.error)
        tb = "".join(traceback.format_exception(ctx.error))[-3000:]
        try:
            await self._bao_admin(ctx, f"❌ Lỗi bot:\n{tb}")
        except Exception:
            log.exception("không nhắn được admin")


LENH = [
    BotCommand("start", "Bắt đầu, xem lời chào"),
    BotCommand("dongbo", "Nạp văn bản mới / đã sửa trên sheet và Drive"),
    BotCommand("vanban", "Xem tình trạng văn bản, vd /vanban 98/2020/NĐ-CP"),
    BotCommand("help", "Hướng dẫn: các lệnh, các nút, câu hỏi mẫu"),
]


async def dat_menu_lenh(app: Application) -> None:
    """Menu lệnh (nút ☰ cạnh ô gõ) để chú khỏi phải nhớ."""
    await app.bot.set_my_commands(LENH)


def tao_ung_dung(c) -> Application:
    cho_phep = c.ds_cho_phep
    if not c.telegram_token.get_secret_value():
        raise ValueError("Chưa điền TELEGRAM_TOKEN trong .env (lấy từ @BotFather).")
    if not cho_phep:
        raise ValueError("Chưa điền TELEGRAM_CHO_PHEP (chat_id được dùng bot, cách nhau dấu phẩy).")
    tra_loi.kiem_cau_hinh(c)
    b = Bot(c)
    xay = Application.builder().token(c.telegram_token.get_secret_value())
    if c.telegram_proxy:
        xay = xay.proxy(c.telegram_proxy).get_updates_proxy(c.telegram_proxy)
    app = xay.post_init(dat_menu_lenh).build()
    duoc = filters.Chat(chat_id=cho_phep)
    app.add_handler(CommandHandler(["start", "help"], b.bat_dau, filters=duoc))
    app.add_handler(CommandHandler("dongbo", b.dong_bo, filters=duoc, block=False))
    app.add_handler(CommandHandler("vanban", b.van_ban, filters=duoc))
    app.add_handler(MessageHandler(duoc & filters.TEXT & ~filters.COMMAND, b.hoi))
    app.add_handler(CallbackQueryHandler(b.nut, pattern=r"^(qd|nv|bs|bk|bq):"), group=0)
    app.add_handler(MessageHandler(~duoc, b.nguoi_la), group=1)
    app.add_error_handler(b.loi)
    return app
