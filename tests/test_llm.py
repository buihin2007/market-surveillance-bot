from test_viet_lai import ChatGia

from qltt import db, llm


def test_bo_qua_cache_van_goi_api_va_van_ghi(conn, monkeypatch):
    db.khoi_tao(conn)
    conn.execute("DELETE FROM llm_cache")
    api = ChatGia('{"x": 1}', '{"x": 2}')
    kiem = __import__("json").loads
    tin = [{"role": "user", "content": "q"}]
    assert llm.goi(conn, api, "m", tin, "k", kiem).dau_ra == {"x": 1}
    assert llm.goi(conn, api, "m", tin, "k", kiem).tu_cache  # lần 2: cache
    monkeypatch.setattr(llm, "BO_QUA_CACHE", True)
    kq = llm.goi(conn, api, "m", tin, "k", kiem)
    assert (kq.tu_cache, kq.dau_ra, len(api.goi)) == (False, {"x": 2}, 2)
