import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from test_tra_loi import C, Gia, kho  # noqa: F401  (kho là fixture)

from qltt import bot, nhat_ky
from qltt.bot import ban_phim_loai_loi, ban_phim_tra_loi, chia_tin


def test_chia_tin():
    assert chia_tin("ngắn") == ["ngắn"]
    doan = ["a" * 30, "b" * 30, "c" * 30]
    assert chia_tin("\n\n".join(doan), 70) == ["a" * 30 + "\n\n" + "b" * 30, "c" * 30]
    dai = chia_tin("x" * 250, 100)  # một dòng quá dài: cắt cứng
    assert [len(p) for p in dai] == [100, 100, 50]
    nhieu_dong = "\n".join(["d" * 40] * 5)  # một đoạn quá dài: tách theo dòng
    assert all(len(p) <= 100 for p in chia_tin(nhieu_dong, 100))
    assert "".join(chia_tin(nhieu_dong, 100)).replace("\n", "") == "d" * 200


def du_lieu(markup):
    return [b.callback_data for hang in markup.inline_keyboard for b in hang]


def test_ban_phim():
    assert du_lieu(ban_phim_tra_loi(7)) == ["qd:7", "bs:7"]
    assert du_lieu(ban_phim_tra_loi(7, co_quy_dinh=False)) == ["bs:7"]
    d = du_lieu(ban_phim_loai_loi(7, "tra_loi"))
    assert d[0] == "bk:7:sai_hanh_vi" and d[-1] == "bk:7:huy" and "bk:7:khong_tim_thay" not in d
    assert du_lieu(ban_phim_loai_loi(7, "khong_tim_thay"))[0] == "bk:7:khong_tim_thay"
    assert all(len(x.encode()) <= 64 for x in d)  # giới hạn callback_data của Telegram


def test_tra_loi_nguyen_van_bao_sai(kho):  # noqa: F811
    kq = bot.tra_loi_va_ghi(kho, Gia(), C, "bán hàng nhập lậu", 42)
    assert kq["loai_ket_qua"] == "tra_loi" and kq["co_nguyen_van"]
    nguoi, kenh = kho.execute(
        "SELECT nguoi, kenh FROM chat_log WHERE id = %s", [kq["ma"]]
    ).fetchone()
    assert (nguoi, kenh) == (42, "telegram")
    nv = bot.nguyen_van(kho, kq["ma"])
    assert "Điều 2. Hành vi buôn bán hàng nhập lậu" in nv and "98/2020/NĐ-CP" in nv
    i, tom = bot.ghi_bao_sai(kho, kq["ma"], "sai_muc_phat", 42)
    assert "Báo sai #" in tom and "Đúng hành vi, sai mức phạt" in tom
    tom = bot.ghi_can_cu(kho, i, "phải là Điều 3")
    assert "Chú ghi: phải là Điều 3" in tom and "Gợi ý khâu hỏng: chon" in tom


# ---------- luồng Telegram với đối tượng giả ----------


class TinGia:
    """Tin nhắn giả: ghi lại tin bot gửi / sửa."""

    def __init__(self, text="", chat_id=1, message_id=100, reply_to=None, so=None):
        self.text, self.chat_id, self.message_id = text, chat_id, message_id
        self.reply_to_message = NS(message_id=reply_to) if reply_to else None
        self.so = so if so is not None else [0]
        self.gui: list[tuple] = []
        self.sua: list[tuple] = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.so[0] += 1
        t = TinGia(text, self.chat_id, 1000 + self.so[0], so=self.so)
        self.gui.append((text, reply_markup))
        t.goc = self
        return t

    async def edit_text(self, text, reply_markup=None, **kw):
        self.sua.append((text, reply_markup))


def ctx_gia():
    return NS(chat_data={}, bot=NS(send_message=AsyncMock(), send_chat_action=AsyncMock()))


@pytest.fixture
def b(kho, monkeypatch):  # noqa: F811
    c = NS(**vars(C), telegram_admin=99, llm_api_key=SecretStr("x"), llm_base_url="http://x")
    bb = bot.Bot(c)
    bb.client = Gia()
    # chạy hàm DB trên kết nối test (không commit), cùng thread cho đơn giản
    monkeypatch.setattr(bb, "_chay", lambda ham, *a: ham(kho, *a))

    async def to_thread(f, *a):
        return f(*a)

    monkeypatch.setattr(bot.asyncio, "to_thread", to_thread)
    return bb


def chay(coro):
    return asyncio.run(coro)


@pytest.fixture
def ghi_tin(monkeypatch):
    """Giữ tham chiếu các tin bot tạo để kiểm."""
    tao: list[TinGia] = []
    goc = TinGia.reply_text

    async def reply_text(self, text, reply_markup=None, **kw):
        t = await goc(self, text, reply_markup)
        tao.append(t)
        return t

    monkeypatch.setattr(TinGia, "reply_text", reply_text)
    return tao


def test_luong_day_du(b, ghi_tin):
    ctx = ctx_gia()
    msg = TinGia("bán hàng nhập lậu")
    chay(b.hoi(NS(effective_message=msg), ctx))
    trang_thai = ghi_tin[0]
    (chu, ban_phim) = trang_thai.sua[-1]
    assert "🔹 <b>" in chu and "📌 khoản 1 Điều 2 NĐ 98/2020" in chu and "<i>mã #" in chu
    ma = int(chu.rsplit("#", 1)[1].removesuffix("</i>"))
    assert du_lieu(ban_phim) == [f"qd:{ma}", f"bs:{ma}"]

    def bam(data):
        q = NS(data=data, answer=AsyncMock(), message=msg, edit_message_text=AsyncMock())
        chay(b.nut(NS(callback_query=q), ctx))
        return q

    bam(f"qd:{ma}")
    qd = ghi_tin[-1].text
    assert qd.startswith("📋 <b>Quy định tại</b>") and "<code>khoản 1 Điều 2 Nghị định số" in qd
    assert '<a href="x-1.aspx">' in qd and qd.endswith(f"<i>mã #{ma}</i>")
    bam(f"nv:{ma}")
    assert "Điều 2. Hành vi buôn bán hàng nhập lậu" in ghi_tin[-1].text
    bam(f"bs:{ma}")
    assert ghi_tin[-1].text == "Câu trả lời sai ở chỗ nào?"
    q = bam(f"bk:{ma}:sai_hanh_vi")
    assert "Đã ghi nhận: Sai hành vi" in q.edit_message_text.call_args.args[0]
    hoi_can_cu = ghi_tin[-1]
    assert hoi_can_cu.text.startswith("Căn cứ đúng là gì?")
    ctx.bot.send_message.assert_awaited()  # đã nhắn ikm
    assert ctx.bot.send_message.call_args.args[0] == 99

    # chú trả lời tin hỏi căn cứ → ghi lý do, không coi là câu hỏi mới
    tl = TinGia("phải là Điều 3", reply_to=hoi_can_cu.message_id)
    chay(b.hoi(NS(effective_message=tl), ctx))
    assert tl.gui[-1][0] == "Cảm ơn chú, đã ghi nhận căn cứ."
    assert "Chú ghi: phải là Điều 3" in ctx.bot.send_message.call_args.args[1]


def test_bo_qua_va_huy(b, ghi_tin, kho):  # noqa: F811
    ctx = ctx_gia()
    msg = TinGia("bán hàng nhập lậu")
    chay(b.hoi(NS(effective_message=msg), ctx))
    ma = int(ghi_tin[0].sua[-1][0].rsplit("#", 1)[1].removesuffix("</i>"))
    q = NS(data=f"bk:{ma}:huy", answer=AsyncMock(), message=msg, edit_message_text=AsyncMock())
    chay(b.nut(NS(callback_query=q), ctx))
    assert q.edit_message_text.call_args.args[0] == "Đã hủy báo sai."
    q = NS(data=f"bk:{ma}:khac", answer=AsyncMock(), message=msg, edit_message_text=AsyncMock())
    chay(b.nut(NS(callback_query=q), ctx))
    (bao_sai_id,) = ctx.chat_data["cho_can_cu"].values()
    q = NS(data=f"bq:{bao_sai_id}", answer=AsyncMock(), message=msg, edit_message_text=AsyncMock())
    chay(b.nut(NS(callback_query=q), ctx))
    assert ctx.chat_data["cho_can_cu"] == {}
    assert nhat_ky.goi_y(kho, bao_sai_id) is None


def test_qua_thoi_gian(b, ghi_tin, monkeypatch):
    async def cham(coro, t):
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(bot.asyncio, "wait_for", cham)
    ctx = ctx_gia()
    chay(b.hoi(NS(effective_message=TinGia("bán hàng nhập lậu")), ctx))
    assert ghi_tin[0].sua[-1][0] == bot.QUA_LAU
    assert "Quá" in ctx.bot.send_message.call_args.args[1]


def test_tao_ung_dung_bat_buoc_token_va_danh_sach():
    c = NS(**vars(C), telegram_token=SecretStr(""), ds_cho_phep={1})
    with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
        bot.tao_ung_dung(c)
    c = NS(**vars(C), telegram_token=SecretStr("123:abc"), ds_cho_phep=set())
    with pytest.raises(ValueError, match="TELEGRAM_CHO_PHEP"):
        bot.tao_ung_dung(c)


def test_van_ban(b, ghi_tin, kho):  # noqa: F811
    assert "Kho có 1 văn bản, 1 văn bản đang dùng để tra" in bot.tra_van_ban(kho, " ")
    chu = bot.tra_van_ban(kho, "98/2020")
    assert chu.startswith('📄 <a href="x-1.aspx">98/2020/NĐ-CP</a>: <b>dùng để tra</b>')
    assert "Quy định xử phạt vi phạm hành chính trong thương mại" in chu
    assert "Không có văn bản nào khớp «99/2099»" in bot.tra_van_ban(kho, "99/2099")
    assert bot.tra_van_ban(kho, "98/2020/ND-CP") == chu  # gõ không dấu cũng ra
    msg = TinGia("/vanban 98/2020")
    chay(b.van_ban(NS(effective_message=msg), NS(args=["98/2020"])))
    assert msg.gui[-1][0] == chu


def test_dong_bo_qua_bot(b, ghi_tin, monkeypatch):
    goi = []
    monkeypatch.setattr(
        bot, "dong_bo_ngay", lambda conn, c, client: goi.append(1) or "Không có gì mới."
    )
    ctx = ctx_gia()
    msg = TinGia("/dongbo", chat_id=5)
    chay(b.dong_bo(NS(effective_message=msg), ctx))
    assert goi and ghi_tin[0].sua[-1][0] == "Không có gì mới."
    # chú chạy (không phải admin) → báo cả admin
    assert ctx.bot.send_message.call_args.args == (99, "🔄 /dongbo (chat 5):\nKhông có gì mới.")

    def hong(conn, c, client):
        from qltt import google_io

        raise google_io.LoiTieuDe("thiếu cột so_hieu")

    monkeypatch.setattr(bot, "dong_bo_ngay", hong)
    chay(b.dong_bo(NS(effective_message=TinGia("/dongbo")), ctx))
    assert ghi_tin[-1].sua[-1][0].startswith("Dòng tiêu đề của sheet chưa đúng: thiếu cột so_hieu")
    assert "Lỗi /dongbo" in ctx.bot.send_message.call_args.args[1]


def test_admin_trong_khong_loi(monkeypatch):
    from qltt.config import CauHinh

    monkeypatch.setenv("TELEGRAM_ADMIN", "")
    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    assert CauHinh(_env_file=None).telegram_admin is None
