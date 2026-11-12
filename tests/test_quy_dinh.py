import json
import re
from types import SimpleNamespace as NS

import pytest
from test_nap import HOM_NAY, dong, nap_docx
from test_tra_loi import C

from qltt import db, nap, ngu_canh, nhat_ky, quy_dinh, tra_loi
from qltt.quy_dinh import doc, dung_nguyen_van


@pytest.mark.parametrize(
    ("trich", "mong"),
    [
        ("có hệ thống  cột bơm đạt quy chuẩn", True),  # khác khoảng trắng
        ("“Có hệ thống cột bơm đạt quy chuẩn.”", True),  # ngoặc, hoa thường, dấu câu cuối
        ("có cột bơm đạt quy chuẩn", False),  # bỏ chữ: không phải nguyên văn
        ("cột", False),  # quá ngắn
    ],
)
def test_dung_nguyen_van(trich, mong):
    nd = "1. Cửa hàng phải có hệ thống cột bơm đạt quy chuẩn kỹ thuật."
    assert dung_nguyen_van(trich, nd) is mong


def test_doc():
    assert doc('{"chon": [{"ma": "q2", "trich": " a  b "}, {"ma": "Q2"}]}', {"Q1", "Q2"}) == {
        "chon": [{"ma": "Q2", "trich": "a b"}]
    }
    assert doc('{"chon": [{"ma": "Q9"}]}', {"Q1"}) is None
    assert doc('{"chon": []}', {"Q1"}) == {"chon": []}


ND = [
    "Điều 1. Phạm vi điều chỉnh",
    "Nghị định này quy định về kinh doanh xăng dầu.",
    "Điều 2. Điều kiện đối với cửa hàng bán lẻ xăng dầu",
    "1. Cửa hàng bán lẻ xăng dầu phải có hệ thống cột bơm đạt quy chuẩn kỹ thuật.",
    "2. Cán bộ quản lý, nhân viên trực tiếp kinh doanh phải được đào tạo nghiệp vụ phòng cháy.",
    "Điều 3. Quyền của thương nhân",
    "Thương nhân được lựa chọn nguồn hàng.",
    "Điều 4. Hiệu lực thi hành",
]


class Gia:
    """LLM giả cho luồng quy_dinh: lượt 1 trả quy_dinh; lượt chọn trả lần lượt các câu cho trước."""

    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, *chon: dict):
        self.chat = NS(completions=NS(create=self._chat))
        self.embeddings = NS(create=self._emb)
        self.chon = list(chon)
        self.goi: list[list[dict]] = []

    def _emb(self, model, input, extra_body=None):
        return NS(data=[NS(embedding=[0.1] * 4, index=i) for i in range(len(input))], usage=None)

    def _chat(self, model, messages, temperature, extra_body):
        if "tra cứu quy định pháp luật" in messages[0]["content"]:
            self.goi.append(messages)
            dong = re.findall(r"^(Q\d+): (.*)$", messages[1]["content"], re.M)
            out = self.chon.pop(0)  # [(chữ có trong đoạn cần chọn, trích)]
            out = {
                "chon": [
                    {"ma": next(m for m, nd in dong if khoa in nd), "trich": t}
                    for khoa, t in out["chon"]
                ]
            }
        else:
            out = {"loai": "quy_dinh", "hanh_vi": ["điều kiện cửa hàng bán lẻ xăng dầu"]}
        msg = NS(content=json.dumps(out, ensure_ascii=False))
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=10, completion_tokens=5))


@pytest.fixture
def kho(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    conn.execute("DELETE FROM llm_cache")
    nap_docx(conn, tmp_path, dong(1, "83/2014/NĐ-CP"), ND)
    nap.tinh_lai(conn, HOM_NAY)
    return conn


def ds_doan(kho):
    ids = [r[0] for r in kho.execute("SELECT id FROM chunk ORDER BY dieu_so, khoan_so")]
    return quy_dinh.doan(kho, ngu_canh.hanh_vi(kho, ids, 6))


def test_doan_moi_khoan_mot_ma_dieu_khong_chia_khoan_la_mot_doan(kho):
    ds = ds_doan(kho)
    vt = [(d.dieu_so, d.khoan_so) for d in ds]
    assert (2, 1) in vt and (2, 2) in vt and (3, None) in vt
    assert [d.ma for d in ds] == [f"Q{i}" for i in range(1, len(ds) + 1)]


K1 = "hệ thống cột bơm"  # chữ nhận ra khoản 1 Điều 2
K2 = "đào tạo nghiệp vụ"  # khoản 2 Điều 2


def test_hoi_quy_dinh_trich_dung_nguyen_van(kho):
    api = Gia({"chon": [(K1, "có hệ thống cột bơm đạt quy chuẩn kỹ thuật")]})
    tl = tra_loi.hoi(kho, api, C, "cây xăng cần điều kiện gì")
    assert tl.loai == "quy_dinh" and len(tl.trich) == 1
    t = tl.trich[0]
    assert (t.doan.dieu_so, t.doan.khoan_so, t.loi_trich) == (2, 1, False)
    assert "«…có hệ thống cột bơm đạt quy chuẩn kỹ thuật…»" in tl.van_ban
    assert "khoản 1 Điều 2 83/2014/NĐ-CP" in tl.van_ban
    assert len(api.goi) == 1
    ma = nhat_ky.ghi(kho, tl, C)
    loai, kq = kho.execute(
        "SELECT loai_ket_qua, ket_qua FROM chat_log WHERE id = %s", [ma]
    ).fetchone()
    assert loai == "quy_dinh" and kq["trich"][0]["dieu"] == "2"


def test_trich_sai_thi_nhac_lai_mot_lan(kho):
    api = Gia(
        {"chon": [(K1, "cửa hàng phải có cột bơm xịn")]},  # bịa
        {"chon": [(K1, "phải có hệ thống cột bơm")]},  # chép lại đúng
    )
    tl = tra_loi.hoi(kho, api, C, "cây xăng cần điều kiện gì")
    assert len(api.goi) == 2 and "không có nguyên văn" in api.goi[1][-1]["content"]
    assert tl.trich[0].trich == "phải có hệ thống cột bơm" and not tl.trich[0].loi_trich


def test_trich_sai_hai_lan_thi_in_ca_doan(kho):
    api = Gia({"chon": [(K2, "bịa lần một cho dài")]}, {"chon": [(K2, "bịa lần hai cho dài")]})
    tl = tra_loi.hoi(kho, api, C, "nhân viên cây xăng cần gì")
    t = tl.trich[0]
    assert t.loi_trich and t.trich is None
    assert "phải được đào tạo nghiệp vụ phòng cháy" in tl.van_ban
    assert "không trích được câu cụ thể" in tl.van_ban


def test_khong_doan_nao_tra_loi(kho):
    tl = tra_loi.hoi(kho, Gia({"chon": []}), C, "thủ tục đăng ký hộ kinh doanh")
    assert tl.trich == [] and tl.van_ban.startswith("Không tìm thấy quy định trả lời")
    assert nhat_ky.loai_ket_qua(tl) == "khong_tim_thay"
