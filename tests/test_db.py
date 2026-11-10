import re

from qltt import db

TAT_CA = db.BANG_DAN_XUAT + db.BANG_GOC + db.BANG_CACHE


def test_moi_bang_trong_schema_deu_duoc_phan_loai():
    trong_schema = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db.schema_sql())
    assert sorted(trong_schema) == sorted(TAT_CA)
    assert len(set(TAT_CA)) == len(TAT_CA)  # không bảng nào nằm ở hai nhóm


def test_khoi_tao_hai_lan_khong_loi(conn):
    db.khoi_tao(conn)
    db.khoi_tao(conn)
    tt = db.thong_tin(conn)
    assert set(tt["extension"]) == set(db.EXTENSION)
    assert set(tt["so_dong"]) == set(TAT_CA)


def test_xoa_dan_xuat_giu_bang_goc_va_cache(conn):
    db.khoi_tao(conn)
    conn.execute(
        "INSERT INTO van_ban (tvpl_id, so_hieu, ngay_ban_hanh, loai, con_hieu_luc, link_tvpl,"
        " so_hieu_chuan) VALUES (406627, '98/2020/NĐ-CP', '2020-08-26', 'nghi_dinh', true, 'x',"
        " '98/2020/NĐ-CP')"
    )
    conn.execute("INSERT INTO chat_log (cau_hoi) VALUES ('bán hàng giả')")
    conn.execute(
        "INSERT INTO xac_nhan (loai, khoa, noi_dung, noi_dung_hash)"
        " VALUES ('go_tim_kiem', 'tvpl:406627', '{}', 'h')"
    )
    conn.execute(
        "INSERT INTO embed_cache (hash, model, embedding) VALUES ('h', 'm', %s::vector)",
        [str([0.0] * 1536)],
    )

    db.khoi_tao(conn, xoa_dan_xuat=True)

    so_dong = db.thong_tin(conn)["so_dong"]
    assert so_dong["van_ban"] == 0
    assert (so_dong["chat_log"], so_dong["xac_nhan"], so_dong["embed_cache"]) == (1, 1, 1)


def test_bang_goc_khong_co_khoa_ngoai_toi_bang_dan_xuat(conn):
    db.khoi_tao(conn)
    khoa_ngoai = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text"
        " FROM pg_constraint WHERE contype = 'f'"
    ).fetchall()
    vi_pham = [
        (tu, den)
        for tu, den in khoa_ngoai
        if tu in db.BANG_GOC + db.BANG_CACHE and den in db.BANG_DAN_XUAT
    ]
    assert vi_pham == []


def test_so_hieu_vbhn_trung_nhau_khac_nam_van_nap_duoc(conn):
    db.khoi_tao(conn)
    cau = (
        "INSERT INTO van_ban (tvpl_id, so_hieu, ngay_ban_hanh, loai, con_hieu_luc, link_tvpl,"
        " so_hieu_chuan) VALUES (%s, '03/VBHN-BCT', %s, 'vbhn', true, 'x', '03/VBHN-BCT')"
    )
    conn.execute(cau, [506541, "2022-02-15"])
    conn.execute(cau, [654519, "2025-03-10"])
    assert conn.execute("SELECT count(*) FROM van_ban").fetchone()[0] == 2


def test_xoa_dan_xuat_don_bang_phien_ban_cu(conn):
    """DB tạo bằng schema cũ (còn phien_ban trỏ vào van_ban) vẫn dọn được."""
    db.khoi_tao(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS phien_ban (id bigint PRIMARY KEY,"
        " tvpl_id integer REFERENCES van_ban ON DELETE CASCADE)"
    )

    db.khoi_tao(conn, xoa_dan_xuat=True)

    con = conn.execute("SELECT to_regclass('phien_ban')").fetchone()[0]
    assert con is None


def test_khoi_tao_bo_rang_buoc_so_chieu_cua_db_cu(conn):
    """DB tạo trước 10/11/2026 có vector(1536); khoi_tao phải cho nhận vector số chiều khác."""
    db.khoi_tao(conn)
    conn.execute("DELETE FROM embed_cache")
    conn.execute("ALTER TABLE embed_cache ALTER COLUMN embedding TYPE vector(3)")

    db.khoi_tao(conn)

    conn.execute("INSERT INTO embed_cache (hash, model, embedding) VALUES ('a', 'm', '[1,2]')")
    conn.execute("INSERT INTO embed_cache (hash, model, embedding) VALUES ('b', 'm', '[1,2,3,4]')")
