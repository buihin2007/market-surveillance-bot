import json
import re
from types import SimpleNamespace as NS

import pytest
from test_nap import HOM_NAY, dong, nap_docx

from qltt import bien_phap, db, muc_phat, nap, tra_loi
from qltt.tra_loi import doc_chon, gon


def test_gon_bo_phan_khung_phat():
    assert gon(
        "1. Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng đối với hành vi bán hàng lậu."
    ) == ("bán hàng lậu.")
    assert gon("Bán hàng không rõ nguồn gốc") == "Bán hàng không rõ nguồn gốc"


@pytest.mark.parametrize(
    ("tra_loi_llm", "mong"),
    [
        (
            '{"chon": [{"ma": "h2", "dieu_kien": "nếu là hàng giả"}], "chu_the": "to_chuc",'
            ' "gia_tri": "60.000.000", "so_luong": null, "don_vi": null}',
            {"chon": [{"ma": "H2", "dieu_kien": "nếu là hàng giả"}], "chu_the": "to_chuc",
             "gia_tri": 60_000_000.0, "so_luong": None, "don_vi": None},
        ),
        (  # chọn rỗng = không có; chủ thể lạ → khong_ro; số âm → None
            '{"chon": [], "chu_the": "ho", "gia_tri": -1, "so_luong": 30, "don_vi": "Bao"}',
            {"chon": [], "chu_the": "khong_ro", "gia_tri": None, "so_luong": 30.0,
             "don_vi": "bao"},
        ),
        ('{"chon": [{"ma": "H9"}]}', None),  # mã không có trong danh sách
        ("không phải JSON", None),
    ],
)  # fmt: skip
def test_doc_chon(tra_loi_llm, mong):
    assert doc_chon(tra_loi_llm, {"H1", "H2", "H3"}) == mong


def test_doc_chon_toi_da_3_va_bo_trung():
    s = json.dumps({"chon": [{"ma": m} for m in ["H1", "H1", "H2", "H3", "H4"]]})
    assert [x["ma"] for x in doc_chon(s, {"H1", "H2", "H3", "H4"})["chon"]] == ["H1", "H2", "H3"]


ND = [
    "Điều 1. Phạm vi điều chỉnh",
    "Mức phạt tiền quy định tại Chương II Nghị định này là mức phạt đối với cá nhân.",
    "Chương II",
    "HÀNH VI VI PHẠM",
    "Điều 2. Hành vi buôn bán hàng nhập lậu",
    "1. Đối với hành vi buôn bán hàng hóa nhập lậu, mức phạt tiền như sau:",
    "a) Phạt tiền từ 500.000 đồng đến 1.000.000 đồng trong trường hợp trị giá dưới 3.000.000 đồng;",
    "b) Phạt tiền từ 1.000.000 đồng đến 2.000.000 đồng trong trường hợp trị giá từ 3.000.000 đồng"
    " trở lên.",
    "2. Phạt tiền gấp hai lần mức tiền phạt quy định tại khoản 1 Điều này trong trường hợp hàng là"
    " thực phẩm.",
    "3. Hình thức xử phạt bổ sung: Tịch thu tang vật.",
    "Điều 3. Hành vi bán hàng giả",
    "1. Phạt tiền từ 3.000.000 đồng đến 5.000.000 đồng đối với một trong các hành vi sau đây:",
    "a) Bán hàng giả mạo nhãn hàng hóa;",
    "b) Bán hàng giả về giá trị sử dụng.",
    "Điều 4. Hiệu lực thi hành",
]


class Gia:
    """Client giả: embeddings + chat. LLM 1 trả loai; LLM 2 chọn mã theo hàm chon(danh sách mã)."""

    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, loai="hanh_vi", chon=lambda ma: ma[:1], them=None):
        self.chat = NS(completions=NS(create=self._chat))
        self.embeddings = NS(create=self._emb)
        self.loai, self.chon, self.them = loai, chon, them or {}
        self.goi_chon: list[str] = []

    def _emb(self, model, input, extra_body=None):
        return NS(data=[NS(embedding=[0.1] * 4, index=i) for i in range(len(input))], usage=None)

    def _chat(self, model, messages, temperature, extra_body):
        if "xác định hành vi" in messages[0]["content"]:
            nd = messages[-1]["content"]
            self.goi_chon.append(nd)
            ma = re.findall(r"^(H\d+):", nd, re.M)
            out = {"chon": [{"ma": m, "dieu_kien": "khi x"} for m in self.chon(ma)], **self.them}
        else:
            hv = [] if self.loai in ("khac", "ngoai_pham_vi") else ["buôn bán hàng hóa nhập lậu"]
            out = {"loai": self.loai, "hanh_vi": hv}
        msg = NS(content=json.dumps(out, ensure_ascii=False))
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=10, completion_tokens=5))


C = NS(llm_model="m", embed_model="e", viet_lai_prompt="v5", llm_tat_suy_nghi=True)


@pytest.fixture
def kho(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    conn.execute("DELETE FROM llm_cache")
    nap_docx(conn, tmp_path, dong(1, "98/2020/NĐ-CP"), ND)
    nap.tinh_lai(conn, HOM_NAY)
    conn.execute("UPDATE van_ban SET ten = 'QUY ĐỊNH XỬ PHẠT VI PHẠM HÀNH CHÍNH TRONG THƯƠNG MẠI'")
    muc_phat.dung_lai(conn)
    bien_phap.dung_lai(conn)
    return conn


def test_ung_vien_gop_bac_phat_va_bo_khoan_tang_nang(kho):
    hv = tra_loi.ngu_canh.hanh_vi(kho, [r[0] for r in kho.execute("SELECT id FROM chunk")], 8)
    uv = tra_loi.ung_vien(kho, hv)
    vt = [(u.dieu_so, u.khoan_so, u.diem) for u in uv]
    # Điều 2 khoản 1 dạng B → một hành vi; khoản 2 "gấp hai lần" là tăng nặng → không phải ứng viên
    assert (2, 1, None) in vt and (2, 2, None) not in vt
    assert (3, 1, "a") in vt and (3, 1, "b") in vt  # dạng A: mỗi điểm một hành vi
    assert [u.ma for u in uv] == [f"H{i}" for i in range(1, len(uv) + 1)]


def test_hoi_hanh_vi_tra_dung_bac_va_chu_the(kho):
    api = Gia(chon=lambda ma: ma[:1], them={"chu_the": "ca_nhan", "gia_tri": 5_000_000})
    tl = tra_loi.hoi(kho, api, C, "hộ kinh doanh bán 5 triệu tiền hàng nhập lậu")
    assert tl.loai == "hanh_vi" and len(tl.chon) == 1
    u = tl.chon[0].uv
    assert (u.dieu_so, u.khoan_so) == (2, 1)
    assert "Cá nhân: 1.000.000 – 2.000.000 đồng" in tl.van_ban  # bậc từ 3 triệu trở lên
    assert "tổ chức" not in tl.van_ban.lower().split("cá nhân")[1][:40]  # chỉ nêu cá nhân
    assert "Nếu hàng là thực phẩm: Cá nhân: 2.000.000 – 4.000.000 đồng" in tl.van_ban
    assert "Tịch thu tang vật" in tl.van_ban
    assert "H1:" in api.goi_chon[0] and "TÌNH HUỐNG" in api.goi_chon[0]
    assert "1.000.000" not in api.goi_chon[0]  # LLM 2 không thấy khung phạt của khoản dạng B


def test_hoi_khong_ro_chu_the_va_gia_tri_thi_neu_het(kho):
    tl = tra_loi.hoi(kho, Gia(chon=lambda ma: ma[:1]), C, "bán hàng nhập lậu")
    assert "Mức phạt (theo từng trường hợp)" in tl.van_ban
    assert tl.van_ban.count("tổ chức") >= 2  # mỗi bậc nêu cả cá nhân và tổ chức
    assert "dưới 3.000.000 đồng" in tl.van_ban


def test_hoi_nhieu_hanh_vi_va_khong_co(kho):
    tl = tra_loi.hoi(kho, Gia(chon=lambda ma: ma[-2:]), C, "bán hàng giả")
    assert len(tl.chon) == 2 and "có thể thuộc 2 hành vi" in tl.van_ban
    assert "Khi: khi x" in tl.van_ban
    tl = tra_loi.hoi(kho, Gia(chon=lambda ma: []), C, "bán hàng giả nhãn")
    assert tl.chon == [] and tl.van_ban.startswith("Không tìm thấy quy định xử phạt")


@pytest.mark.parametrize(
    ("loai", "dau"),
    [("khac", "Câu này ngoài phạm vi của cháu.\n"), ("ngoai_pham_vi", "Câu này ngoài phạm vi")],
)
def test_hoi_khong_phai_hanh_vi(kho, loai, dau):
    api = Gia(loai=loai)
    tl = tra_loi.hoi(kho, api, C, "chào")
    assert tl.van_ban.startswith(dau) and api.goi_chon == [] and len(tl.buoc) == 1
    assert "1. Tình huống vi phạm" in tl.van_ban and "/vanban 98/2020/NĐ-CP" in tl.van_ban


def test_prompt_khong_phan_loai_thi_bao_loi(kho):
    c = NS(**{**vars(C), "viet_lai_prompt": "v2"})
    with pytest.raises(ValueError, match="VIET_LAI_PROMPT=v2"):
        tra_loi.hoi(kho, Gia(), c, "bán hàng nhập lậu")
