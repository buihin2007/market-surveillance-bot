"""Đồ thị trả lời (LangGraph): nối các bước trong tra_loi.py, rẽ nhánh theo loại câu hỏi.

    START → hieu_cau_hoi ─┬─ khac / ngoai_pham_vi ───────────────────────────────┐
                          ├─ quy_dinh → tim_quy_dinh ─┬─ (không đoạn) ───────────┤
                          │                           └→ chon_trich ─────────────┤
                          └─ hanh_vi → tim_hanh_vi ─┬─ (không ứng viên) ─────────┤
                                                    └→ chon_hanh_vi → tra_muc_phat┤
                                                                     dinh_dang ←─┘ → END
Kiểm trích dẫn: luồng hanh_vi chỉ chọn mã có thật (doc_chon từ chối mã lạ, gọi lại một lần);
luồng quy_dinh kiểm phần chép nguyên văn, nhắc lại một lần, sai tiếp thì in cả khoản.
Kết nối DB, client API và cấu hình truyền qua config["configurable"], không nằm trong state.
"""

from functools import lru_cache
from typing import Any, TypedDict

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from qltt import tra_loi
from qltt.tra_loi import TraLoi


class TrangThai(TypedDict, total=False):
    cau_hoi: str
    tl: TraLoi
    ung_vien: list  # list[UngVien]
    dinh_nghia: list
    chon_llm: dict
    doan: list  # list[quy_dinh.Doan]


def _cfg(config: RunnableConfig) -> tuple[psycopg.Connection, Any, Any]:
    cf = config["configurable"]
    return cf["conn"], cf["client"], cf["c"]


def hieu_cau_hoi(s: TrangThai, config: RunnableConfig) -> TrangThai:
    conn, client, c = _cfg(config)
    return {"tl": tra_loi.b_hieu_cau_hoi(conn, client, c, s["cau_hoi"])}


def tim_hanh_vi(s: TrangThai, config: RunnableConfig) -> TrangThai:
    conn, client, c = _cfg(config)
    uv, dn = tra_loi.b_tim_hanh_vi(conn, client, c, s["tl"])
    return {"ung_vien": uv, "dinh_nghia": dn}


def chon_hanh_vi(s: TrangThai, config: RunnableConfig) -> TrangThai:
    conn, client, c = _cfg(config)
    d = tra_loi.b_chon_hanh_vi(conn, client, c, s["tl"], s["ung_vien"], s["dinh_nghia"])
    return {"chon_llm": d}


def tra_muc_phat(s: TrangThai, config: RunnableConfig) -> TrangThai:
    conn, _, _ = _cfg(config)
    tra_loi.b_tra_muc_phat(conn, s["tl"], s["ung_vien"], s["chon_llm"])
    return {}


def tim_quy_dinh(s: TrangThai, config: RunnableConfig) -> TrangThai:
    conn, client, c = _cfg(config)
    return {"doan": tra_loi.b_tim_quy_dinh(conn, client, c, s["tl"])}


def chon_trich(s: TrangThai, config: RunnableConfig) -> TrangThai:
    conn, client, c = _cfg(config)
    tra_loi.b_chon_trich(conn, client, c, s["tl"], s["doan"])
    return {}


def dinh_dang(s: TrangThai, config: RunnableConfig) -> TrangThai:
    conn, _, _ = _cfg(config)
    s["tl"].van_ban = tra_loi.dinh_dang(conn, s["tl"])
    return {}


def sau_hieu(s: TrangThai) -> str:
    return {"hanh_vi": "tim_hanh_vi", "quy_dinh": "tim_quy_dinh"}.get(s["tl"].loai, "dinh_dang")


@lru_cache
def do_thi():
    g = StateGraph(TrangThai)
    for ten, f in [
        ("hieu_cau_hoi", hieu_cau_hoi), ("tim_hanh_vi", tim_hanh_vi),
        ("chon_hanh_vi", chon_hanh_vi), ("tra_muc_phat", tra_muc_phat),
        ("tim_quy_dinh", tim_quy_dinh), ("chon_trich", chon_trich), ("dinh_dang", dinh_dang),
    ]:  # fmt: skip
        g.add_node(ten, f)
    g.add_edge(START, "hieu_cau_hoi")
    g.add_conditional_edges("hieu_cau_hoi", sau_hieu, ["tim_hanh_vi", "tim_quy_dinh", "dinh_dang"])
    g.add_conditional_edges(
        "tim_hanh_vi", lambda s: "chon_hanh_vi" if s["ung_vien"] else "dinh_dang",
        ["chon_hanh_vi", "dinh_dang"],
    )  # fmt: skip
    g.add_edge("chon_hanh_vi", "tra_muc_phat")
    g.add_edge("tra_muc_phat", "dinh_dang")
    g.add_conditional_edges(
        "tim_quy_dinh", lambda s: "chon_trich" if s["doan"] else "dinh_dang",
        ["chon_trich", "dinh_dang"],
    )  # fmt: skip
    g.add_edge("chon_trich", "dinh_dang")
    g.add_edge("dinh_dang", END)
    return g.compile()


def chay(conn: psycopg.Connection, client, c, cau_hoi: str) -> TraLoi:
    tra_loi.kiem_cau_hinh(c)
    kq = do_thi().invoke(
        {"cau_hoi": cau_hoi}, {"configurable": {"conn": conn, "client": client, "c": c}}
    )
    return kq["tl"]


def mermaid() -> str:
    return do_thi().get_graph().draw_mermaid()
