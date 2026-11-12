"""Kết nối Postgres và khởi tạo schema."""

from importlib import resources

import psycopg
from psycopg import sql

from qltt.config import cau_hinh

# Dựng lại được từ Sheet + Drive: lệnh rebuild được phép xóa.
BANG_DAN_XUAT = (
    "van_ban",
    "chunk",
    "sua_doi",
    "chu_thich_vbhn",
    "quan_he_van_ban",
    "dan_chieu",
    "muc_phat",
    "bien_phap",
    "sua_doi_chi_tiet",
)
# Bảng của schema cũ, đã bỏ: --xoa-dan-xuat xóa luôn nếu còn sót trong DB.
BANG_DA_BO = ("phien_ban",)  # bỏ 10/11/2026: văn bản không đổi, file đổi thì thay chunk
# Không dựng lại được: không bao giờ xóa tự động, phải nằm trong backup.
BANG_GOC = ("nhat_ky_dong_bo", "xac_nhan", "chat_log", "bao_sai")
# Dựng lại được nhưng tốn tiền API: giữ qua các lần rebuild.
BANG_CACHE = ("embed_cache", "llm_cache")

EXTENSION = ("vector", "unaccent", "pg_trgm")


def ket_noi(dbname: str | None = None) -> psycopg.Connection:
    c = cau_hinh()
    return psycopg.connect(
        host=c.db_host,
        port=c.db_port,
        user=c.db_user,
        password=c.postgres_password.get_secret_value(),
        dbname=dbname or c.db_name,
        connect_timeout=5,
        # chờ khóa quá 15 giây thì báo lỗi thay vì treo im lặng (vd phiên khác còn transaction dở)
        options="-c lock_timeout=15s",
    )


def schema_sql() -> str:
    return resources.files("qltt").joinpath("schema.sql").read_text(encoding="utf-8")


def khoi_tao(conn: psycopg.Connection, xoa_dan_xuat: bool = False) -> None:
    """Tạo extension, bảng, index. Chạy lại nhiều lần không sao.

    xoa_dan_xuat=True: xóa các bảng dẫn xuất rồi tạo lại; bảng gốc và cache giữ nguyên.
    Không dùng CASCADE: nếu bảng gốc lỡ có khóa ngoại tới bảng dẫn xuất thì lệnh báo lỗi
    thay vì lặng lẽ gỡ ràng buộc.
    """
    with conn.transaction():
        if xoa_dan_xuat:
            bang = BANG_DAN_XUAT + BANG_DA_BO
            ten = sql.SQL(", ").join(sql.Identifier(b) for b in bang)
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(ten))
        conn.execute(schema_sql())
        # DB tạo trước 10/11/2026 có vector(1536): bỏ ràng buộc số chiều để đổi model được.
        # Chỉ ALTER khi còn ràng buộc (atttypmod <> -1), vì ALTER viết lại cả bảng.
        con_rang_buoc = conn.execute(
            "SELECT attrelid::regclass::text FROM pg_attribute WHERE attname = 'embedding'"
            " AND attrelid IN ('chunk'::regclass, 'embed_cache'::regclass) AND atttypmod <> -1"
        ).fetchall()
        for (bang,) in con_rang_buoc:
            conn.execute(
                sql.SQL("ALTER TABLE {} ALTER COLUMN embedding TYPE vector").format(
                    sql.Identifier(bang)
                )
            )


def thong_tin(conn: psycopg.Connection) -> dict:
    """Phiên bản Postgres, phiên bản extension, số dòng từng bảng."""
    phien_ban_pg = conn.execute("SHOW server_version").fetchone()[0]
    ext = dict(
        conn.execute(
            "SELECT extname, extversion FROM pg_extension WHERE extname = ANY(%s)",
            [list(EXTENSION)],
        ).fetchall()
    )
    so_dong = {}
    for bang in BANG_DAN_XUAT + BANG_GOC + BANG_CACHE:
        cau = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(bang))
        so_dong[bang] = conn.execute(cau).fetchone()[0]
    return {"postgres": phien_ban_pg, "extension": ext, "so_dong": so_dong}
