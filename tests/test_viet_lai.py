import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from qltt import danh_gia, db, viet_lai


class ChatGia:
    """Thay client OpenAI cho chat.completions; trả lần lượt các chuỗi cho trước."""

    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, *tra_loi: str):
        self.tra_loi = list(tra_loi)
        self.goi: list[dict] = []
        self.chat = NS(completions=self)

    def create(self, **kw):
        self.goi.append(kw)
        nd = self.tra_loi.pop(0)
        return NS(
            choices=[NS(message=NS(content=nd))],
            usage=NS(prompt_tokens=300, completion_tokens=40),
        )


@pytest.mark.parametrize(
    ("tra_loi", "mong"),
    [
        ('{"hanh_vi": ["a", "b"]}', ["a", "b"]),
        ('```json\n{"hanh_vi": ["  buôn bán\n hàng giả "]}\n```', ["buôn bán hàng giả"]),
        ('{"hanh_vi": ["a", "a", "b", "c", "d"]}', ["a", "b", "c"]),  # bỏ trùng, tối đa 3
        ("không phải JSON", []),
        ('{"hanh_vi": "a"}', []),
        ('{"khac": []}', []),
    ],
)
def test_doc_json(tra_loi, mong):
    assert viet_lai.doc_json(tra_loi) == mong


@pytest.fixture
def csdl(conn):
    db.khoi_tao(conn)
    conn.execute("DELETE FROM llm_cache")
    return conn


def test_goi_mot_lan_roi_lay_cache(csdl):
    api = ChatGia('{"hanh_vi": ["kinh doanh hàng hóa không rõ nguồn gốc, xuất xứ"]}')
    kq = viet_lai.viet_lai(csdl, api, "m", "bán hàng không hóa đơn")
    assert (kq.cau, kq.tu_cache, kq.token_vao) == (
        ["kinh doanh hàng hóa không rõ nguồn gốc, xuất xứ"], False, 300
    )  # fmt: skip
    goi = api.goi[0]
    assert goi["temperature"] == 0
    assert goi["extra_body"] == {"provider": {"data_collection": "deny"}}
    assert goi["messages"][0]["role"] == "system" and goi["messages"][-1]["content"] == (
        "bán hàng không hóa đơn"
    )

    lan_2 = viet_lai.viet_lai(csdl, api, "m", "bán hàng không hóa đơn")
    assert lan_2.tu_cache and lan_2.cau == kq.cau and len(api.goi) == 1
    viet_lai.viet_lai(csdl, ChatGia('{"hanh_vi": ["x"]}'), "model-khac", "bán hàng không hóa đơn")
    assert csdl.execute("SELECT count(*) FROM llm_cache").fetchone()[0] == 2  # khóa có model


def test_tra_loi_hong_thi_khong_luu_cache(csdl):
    api = ChatGia("xin lỗi", '{"hanh_vi": ["a"]}')
    assert viet_lai.viet_lai(csdl, api, "m", "q").cau == []
    assert viet_lai.viet_lai(csdl, api, "m", "q").cau == ["a"]  # gọi lại được
    assert len(api.goi) == 2


def test_vi_du_trong_prompt_khong_lay_tu_bo_eval():
    cases = danh_gia.doc_cases(Path(__file__).parent.parent / "eval" / "cases.jsonl")
    prompt = viet_lai.HE_THONG + json.dumps(viet_lai.VI_DU, ensure_ascii=False)
    for x in cases:
        assert x.cau_hoi not in prompt and x.cau_hoi_nguyen_van.lower() not in prompt.lower()


def test_prompt_v2_v3_lay_dinh_nghia_va_danh_muc_tu_kho(conn, tmp_path):
    from test_nap import HOM_NAY, dong, nap_docx
    from test_ngu_canh import ND

    from qltt import nap

    db.khoi_tao(conn, xoa_dan_xuat=True)
    nap_docx(conn, tmp_path, dong(406627, "98/2020/NĐ-CP"), ND)
    nap.tinh_lai(conn, HOM_NAY)

    v1, v2, v3, v4 = (viet_lai.he_thong(conn, v) for v in ("v1", "v2", "v3", "v4"))
    assert v1 == viet_lai.HE_THONG
    assert "Hàng giả là hàng hóa" in v2 and "DANH MỤC" not in v2
    assert "- 98/2020/NĐ-CP: Buôn bán hàng giả; Kinh doanh hàng nhập lậu" in v3
    assert "Hàng giả là hàng hóa" not in v3  # định nghĩa không lọt vào danh mục
    assert v4.startswith(v1) and "Hàng giả là hàng hóa" in v4 and "DANH MỤC" in v4
    with pytest.raises(ValueError, match="prompt lạ"):
        viet_lai.he_thong(conn, "v9")

    # khóa cache: v1 giữ như cũ; bản khác đổi khi prompt (tức kho) đổi
    assert viet_lai.khoa("m", "q") == viet_lai.khoa("m", "q", "v1", "bất kỳ")
    assert viet_lai.khoa("m", "q", "v3", v3) != viet_lai.khoa("m", "q", "v3", v3 + "x")

    api = ChatGia('{"hanh_vi": ["buôn bán hàng giả"]}')
    conn.execute("DELETE FROM llm_cache")
    assert viet_lai.viet_lai(conn, api, "m", "bán đồ dỏm", "v3").cau == ["buôn bán hàng giả"]
    assert api.goi[0]["messages"][0]["content"] == v3
