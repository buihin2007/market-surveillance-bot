import json
from datetime import date

import pytest
from test_nap import HOM_NAY, ND_98, dong, nap_docx

from qltt import danh_gia, db, nap
from qltt.danh_gia import CanCu, Case, DapAn, doc_cases, giai, hang, tong_hop, trung


def case(**them) -> dict:
    gt = dict(
        id="X-1", nhom="chinh", cau_hoi="bán hàng giả", cau_hoi_nguyen_van="Buôn bán hàng giả",
        can_cu=[{"van_ban": "98/2020/NĐ-CP", "dieu": "2", "khoan": [1]}], cap_cham="khoan",
        kiem="so_tay",
    )  # fmt: skip
    return gt | them


def ghi(tmp_path, *dong_json):
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in dong_json), encoding="utf-8")
    return p


def test_doc_cases_hop_le(tmp_path):
    (c,) = doc_cases(ghi(tmp_path, case()))
    assert c.can_cu == [CanCu("98/2020/NĐ-CP", "2", [1], [])]


@pytest.mark.parametrize(
    ("sai", "bao"),
    [
        ({"nhom": "la"}, "nhom lạ"),
        ({"can_cu": []}, "nhom chinh phải có can_cu"),
        ({"nhom": "khong_co"}, "nhom chinh phải có can_cu"),
        ({"can_cu": [{"van_ban": "x", "dieu": "2"}]}, "cap_cham khoan nhưng"),
        ({"can_cu": [{"van_ban": "x", "dieu": "Điều 2", "khoan": [1]}]}, "Điều lạ"),
        ({"cau_hoi": " "}, "thiếu cau_hoi"),
    ],
)
def test_doc_cases_bao_loi(tmp_path, sai, bao):
    with pytest.raises(ValueError, match=bao):
        doc_cases(ghi(tmp_path, case(**sai)))


def test_doc_cases_id_trung(tmp_path):
    with pytest.raises(ValueError, match="id trùng: X-1"):
        doc_cases(ghi(tmp_path, case(), case()))


@pytest.fixture
def kho(conn, tmp_path):
    """98/2020 gốc + VBHN đang dùng; 87/2024 tra thẳng."""
    db.khoi_tao(conn, xoa_dan_xuat=True)
    nap_docx(conn, tmp_path, dong(406627, "98/2020/NĐ-CP"), ND_98, ten="goc.docx")
    nap_docx(
        conn, tmp_path, dong(654519, "03/VBHN-BCT", loai="vbhn", ngay=date(2025, 4, 23)), ND_98,
        ten="vbhn.docx", ngay="ngày 23 tháng 4 năm 2025",
        dau=["Nghị định số 98/2020/NĐ-CP ngày 26 tháng 8 năm 2020, được sửa đổi bởi:"],
    )  # fmt: skip
    nap_docx(conn, tmp_path, dong(1, "87/2024/NĐ-CP"), ND_98, ten="gia.docx")
    nap.tinh_lai(conn, HOM_NAY)
    return conn


def lam(cap="khoan", *can_cu):
    return Case("X", "chinh", "q", "q", list(can_cu), cap, "so_tay")


def test_giai_quy_van_ban_goc_sang_vbhn(kho):
    da = giai(kho, lam("khoan", CanCu("98/2020/NĐ-CP", "2", [1]), CanCu("87/2024/NĐ-CP", "2")))
    assert da.loi == []
    assert da.dich == ["98/2020/NĐ-CP → 03/VBHN-BCT (2025-04-23)", "87/2024/NĐ-CP"]
    assert da.vi_tri == {(654519, 2, "", 1), (1, 2, "", None)}


def test_giai_bao_loi(kho):
    da = giai(
        kho,
        lam(
            "khoan",
            CanCu("98/2020/NĐ-CP", "2", [9]),  # không có khoản 9
            CanCu("98/2020/NĐ-CP", "3", [1]),  # Điều thẩm quyền: không tìm kiếm
            CanCu("117/2020/NĐ-CP", "68", [2]),  # chưa có trong kho
        ),
    )
    assert da.vi_tri == set()
    assert da.loi == [
        "98/2020/NĐ-CP Điều 2 khoản 9: không có trong 03/VBHN-BCT (2025-04-23)",
        "98/2020/NĐ-CP Điều 3 khoản 1: chunk không được tìm kiếm (thẩm quyền/hiệu lực)",
        "117/2020/NĐ-CP: chưa có trong kho",
    ]


def dap_an(cap, *vi_tri):
    return DapAn(lam(cap), set(vi_tri))


def test_trung_theo_cap_cham():
    khoan = dap_an("khoan", (1, 2, "", 1))
    assert trung((1, 2, "", 1), khoan)
    assert trung((1, 2, "", None), khoan)  # chunk cả Điều chứa khoản đáp án
    assert not trung((1, 2, "", 2), khoan)  # khoản khác cùng Điều
    assert not trung((9, 2, "", 1), khoan)  # văn bản khác

    dieu = dap_an("dieu", (1, 2, "", None))
    assert trung((1, 2, "", 5), dieu) and trung((1, 2, "", None), dieu)
    assert not trung((1, 2, "a", None), dieu)  # Điều 2a khác Điều 2


def test_hang_va_tong_hop():
    da = dap_an("khoan", (1, 2, "", 1))
    assert hang([(1, 5, "", None), (1, 2, "", 2), (1, 2, "", 1)], da) == 3
    assert hang([(1, 5, "", None)], da) is None
    kq = tong_hop([1, 3, 10, None], ks=(1, 5))
    assert kq == {"recall@1": 0.25, "recall@5": 0.5, "mrr": pytest.approx((1 + 1 / 3 + 0.1) / 4)}


def test_bo_eval_trong_repo_doc_duoc():
    from pathlib import Path

    cases = doc_cases(Path(__file__).parent.parent / "eval" / "cases.jsonl")
    assert len(cases) >= 40
    assert danh_gia.NHOM >= {c.nhom for c in cases}
