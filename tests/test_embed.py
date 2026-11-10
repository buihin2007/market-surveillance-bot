from types import SimpleNamespace as NS

import pytest
from test_nap import ND_98, dong, nap_docx

from qltt import db, embed


class ApiGia:
    """Thay client OpenAI: mỗi text → vector 1536 chiều, ghi lại số lần gọi."""

    base_url = "https://openrouter.ai/api/v1"

    def __init__(self):
        self.goi: list[list[str]] = []
        self.embeddings = self

    def create(self, model, input, extra_body=None):
        self.goi.append(list(input))
        self.extra_body = extra_body
        data = [NS(index=i, embedding=[0.0] * 1535 + [float(len(t))]) for i, t in enumerate(input)]
        return NS(data=data, usage=NS(total_tokens=10 * len(input)))


@pytest.fixture
def csdl(conn, tmp_path):
    db.khoi_tao(conn, xoa_dan_xuat=True)
    conn.execute("DELETE FROM embed_cache")
    nap_docx(conn, tmp_path, dong(406627, "98/2020/NĐ-CP"), ND_98)
    return conn


def test_embed_lan_dau_goi_api_lan_hai_khong(csdl):
    api = ApiGia()
    kq = embed.embed_tat_ca(csdl, api, "m")
    can = csdl.execute("SELECT count(*) FROM chunk WHERE embed").fetchone()[0]

    assert (kq.can, kq.tu_api, kq.tu_cache, kq.so_lan_goi) == (can, can, 0, 1)
    assert api.extra_body == {"provider": {"data_collection": "deny"}}
    assert (
        csdl.execute("SELECT count(*) FROM chunk WHERE embed AND embedding IS NULL").fetchone()[0]
        == 0
    )
    # Điều thẩm quyền, hiệu lực không embed
    assert (
        csdl.execute(
            "SELECT count(*) FROM chunk WHERE NOT embed AND embedding IS NOT NULL"
        ).fetchone()[0]
        == 0
    )

    kq2 = embed.embed_tat_ca(csdl, api, "m")
    assert (kq2.can, kq2.so_lan_goi) == (0, 0)


def test_dung_lai_cache_sau_khi_nap_lai(csdl, tmp_path):
    api = ApiGia()
    embed.embed_tat_ca(csdl, api, "m")
    nap_docx(
        csdl, tmp_path, dong(406627, "98/2020/NĐ-CP"), ND_98, ten="lai.docx"
    )  # chunk mới, chữ cũ

    kq = embed.embed_tat_ca(csdl, api, "m")
    assert kq.tu_cache == kq.can > 0 and kq.so_lan_goi == 0


def test_doi_model_thi_embed_lai(csdl, tmp_path):
    api = ApiGia()
    embed.embed_tat_ca(csdl, api, "model-a")
    csdl.execute("UPDATE chunk SET embedding = NULL")

    kq = embed.embed_tat_ca(csdl, api, "model-b")
    assert kq.tu_cache == 0 and kq.tu_api == kq.can


def test_chia_lo(monkeypatch):
    monkeypatch.setattr(embed, "LO_TOI_DA", 3)
    monkeypatch.setattr(embed, "KY_TU_LO_TOI_DA", 10)
    cac = [(i, f"h{i}", "x" * n) for i, n in enumerate([4, 4, 4, 1, 1, 1, 1])]
    assert [len(lo) for lo in embed._lo(cac)] == [2, 3, 2]


def test_api_tra_thieu_vector_thi_bao_loi():
    api = ApiGia()
    api.create = lambda **kw: NS(data=[], usage=None)
    with pytest.raises(ValueError, match="cần 1 vector"):
        embed.goi_api(api, "m", ["a"])
