"""Nạp văn bản vào DB: một dòng sheet + một file docx → van_ban, chunk, chú thích, quan hệ.

Không gọi Google, không embed. Gọi từ lệnh `qltt nap` (và sau này /dong-bo).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psycopg

from qltt import chunk, gate
from qltt.parse import R_SO_TRONG_CAU, chuan, chuan_so_hieu, parse

LOAI = {
    "luat": "luat",
    "phap lenh": "phap_lenh",
    "nghi dinh": "nghi_dinh",
    "vbhn": "vbhn",
    "van ban hop nhat": "vbhn",
    "thong tu": "thong_tu",
    "thong tu lien tich": "ttlt",
    "quyet dinh": "quyet_dinh",
    "nghi quyet": "nghi_quyet",
}


R_DA_SUA = re.compile(r"\b(?:ĐÃ ĐƯỢC|ĐƯỢC) SỬA ĐỔI")
R_NHIEU_DICH = re.compile(r"\b(?:CÁC|VÀ) (?:NGHỊ ĐỊNH|THÔNG TƯ|LUẬT|PHÁP LỆNH)\b")


def chi_sua_mot_van_ban(ten: str) -> str | None:
    """Tên kiểu "SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU CỦA NGHỊ ĐỊNH SỐ 98/2020/NĐ-CP … ĐÃ ĐƯỢC SỬA ĐỔI
    BỞI NGHỊ ĐỊNH SỐ 17/2022…" → số hiệu chuẩn của văn bản duy nhất bị sửa; sửa nhiều văn bản
    ("CÁC NGHỊ ĐỊNH", "… VÀ NGHỊ ĐỊNH SỐ …") hoặc không phải văn bản sửa đổi → None.
    Phần sau "đã được sửa đổi" chỉ là lịch sử của văn bản bị sửa, không tính."""
    ten = (ten or "").upper()
    if not ten.startswith(("SỬA ĐỔI", "SỬA ĐỔI, BỔ SUNG", "BỔ SUNG")):
        return None
    dau = R_DA_SUA.split(ten)[0]
    so = R_SO_TRONG_CAU.findall(dau.replace("SỐ", "số"))
    if len(so) != 1 or R_NHIEU_DICH.search(dau):
        return None
    return chuan_so_hieu(so[0])


@dataclass
class DongSheet:
    tvpl_id: int
    so_hieu: str
    ngay_ban_hanh: date
    loai: str  # khóa nội bộ: luat, nghi_dinh, vbhn...
    con_hieu_luc: bool
    ngay_hieu_luc: date | None
    ngay_het_hieu_luc: date | None
    link_tvpl: str
    dong: int  # số dòng trên sheet, để báo lỗi


@dataclass
class KetQuaNap:
    tvpl_id: int
    so_chunk: int = 0
    loi: list[str] = field(default_factory=list)
    canh_bao: list[str] = field(default_factory=list)


def nap_van_ban(
    conn: psycopg.Connection, d: DongSheet, path: Path, md5: str, drive_file_id: str | None
) -> KetQuaNap:
    """Parse + gate + ghi DB trong một transaction. Gate trượt: giữ chunk cũ (nếu có)."""
    vb = parse(path)
    g = gate.kiem(vb, d.so_hieu, d.ngay_ban_hanh, d.loai == "vbhn")
    kq = KetQuaNap(d.tvpl_id, loi=g.loi, canh_bao=g.canh_bao)
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO van_ban (tvpl_id, so_hieu, ngay_ban_hanh, loai, con_hieu_luc, ngay_hieu_luc,
                ngay_het_hieu_luc, link_tvpl, so_hieu_chuan, ten, chi_sua_van_ban, drive_file_id,
                loi, canh_bao, dong_bo_luc)
            VALUES (%(id)s, %(so)s, %(nbh)s, %(loai)s, %(chl)s, %(nhl)s, %(nhh)s, %(link)s, %(sc)s,
                %(ten)s, %(csvb)s, %(drive)s, %(loi)s, %(cb)s, now())
            ON CONFLICT (tvpl_id) DO UPDATE SET so_hieu = EXCLUDED.so_hieu,
                ngay_ban_hanh = EXCLUDED.ngay_ban_hanh, loai = EXCLUDED.loai,
                con_hieu_luc = EXCLUDED.con_hieu_luc, ngay_hieu_luc = EXCLUDED.ngay_hieu_luc,
                ngay_het_hieu_luc = EXCLUDED.ngay_het_hieu_luc, link_tvpl = EXCLUDED.link_tvpl,
                so_hieu_chuan = EXCLUDED.so_hieu_chuan, ten = EXCLUDED.ten,
                drive_file_id = EXCLUDED.drive_file_id, loi = EXCLUDED.loi,
                canh_bao = EXCLUDED.canh_bao, dong_bo_luc = now()
            """,
            {
                "id": d.tvpl_id,
                "so": d.so_hieu,
                "nbh": d.ngay_ban_hanh,
                "loai": d.loai,
                "chl": d.con_hieu_luc,
                "nhl": d.ngay_hieu_luc,
                "nhh": d.ngay_het_hieu_luc,
                "link": d.link_tvpl,
                "sc": chuan_so_hieu(d.so_hieu),
                "ten": vb.ten or None,
                "csvb": chi_sua_mot_van_ban(vb.ten),
                "drive": drive_file_id,
                "loi": json.dumps(g.loi, ensure_ascii=False),
                "cb": json.dumps(g.canh_bao, ensure_ascii=False),
            },
        )
        if not g.qua:
            return kq  # chunk cũ (nếu có) giữ nguyên; file_hash cũ giữ nguyên để lần sau thử lại

        cac_chunk = chunk.cat(vb, d.so_hieu)
        conn.execute("DELETE FROM chunk WHERE tvpl_id = %s", [d.tvpl_id])
        # chú thích không gắn chunk (chunk_id NULL) không bị xóa theo chunk → xóa riêng
        conn.execute("DELETE FROM chu_thich_vbhn WHERE tvpl_id = %s", [d.tvpl_id])
        conn.execute("DELETE FROM quan_he_van_ban WHERE tu = %s AND nguon <> 'tay'", [d.tvpl_id])
        ids: list[int] = []
        cho_chu_thich: dict[int, int] = {}
        cho_diem: dict[int, str] = {}
        for c in cac_chunk:
            cid = conn.execute(
                """
                INSERT INTO chunk (tvpl_id, cap, dieu_so, dieu_suffix, khoan_so, khoan_suffix,
                    phu_luc_so, cha_id, duong_dan, phan_ten, chuong_ten, muc_ten, dieu_ten,
                    loai_chunk, vai_tro, noi_dung, noi_dung_embed, tsv, embed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    to_tsvector('simple', %s), %s)
                RETURNING id
                """,
                [
                    d.tvpl_id, c.cap, c.dieu_so, c.dieu_suffix, c.khoan_so, c.khoan_suffix,
                    c.phu_luc_so, ids[c.cha] if c.cha is not None else None, c.duong_dan,
                    c.phan, c.chuong, c.muc, c.dieu_ten, c.loai_chunk, c.vai_tro, c.noi_dung,
                    c.noi_dung_embed,
                    c.noi_dung_embed.lower(), c.embed,
                ],
            ).fetchone()[0]  # fmt: skip
            ids.append(cid)
            for so in c.chu_thich:
                cho_chu_thich.setdefault(so, cid)
            cho_diem.update(c.chu_thich_diem)

        for so, noi_dung in vb.chu_thich.items():
            m = R_SO_TRONG_CAU.search(noi_dung)
            conn.execute(
                "INSERT INTO chu_thich_vbhn (tvpl_id, so, chunk_id, diem, noi_dung, vb_sua)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    d.tvpl_id,
                    so,
                    cho_chu_thich.get(so),
                    cho_diem.get(so),
                    noi_dung,
                    m.group(1) if m else None,
                ],  # fmt: skip
            )
        if d.loai == "vbhn":
            # văn bản đầu danh sách là văn bản gốc, các văn bản sau là văn bản sửa đổi đã hợp nhất
            for i, so_hieu in enumerate(dict.fromkeys(vb.hop_nhat)):  # bỏ trùng, giữ thứ tự
                conn.execute(
                    "INSERT INTO quan_he_van_ban (tu, den_so_hieu, loai, nguon)"
                    " VALUES (%s, %s, %s, 'dau_vbhn') ON CONFLICT DO NOTHING",
                    [d.tvpl_id, chuan_so_hieu(so_hieu), "hop_nhat" if i == 0 else "hop_nhat_sua"],
                )
        conn.execute(
            "UPDATE van_ban SET file_hash = %s, parse_luc = now(), so_dieu = %s, so_chunk = %s"
            " WHERE tvpl_id = %s",
            [md5, len(vb.dieu), len(cac_chunk), d.tvpl_id],
        )
        kq.so_chunk = len(cac_chunk)
    return kq


def cap_nhat_dong(conn: psycopg.Connection, d: DongSheet) -> None:
    """File không đổi: chỉ chép lại 7 cột sheet (tick, ngày) vào DB, không parse lại."""
    conn.execute(
        "UPDATE van_ban SET so_hieu = %s, ngay_ban_hanh = %s, loai = %s, con_hieu_luc = %s,"
        " ngay_hieu_luc = %s, ngay_het_hieu_luc = %s, link_tvpl = %s, so_hieu_chuan = %s,"
        " dong_bo_luc = now() WHERE tvpl_id = %s",
        [d.so_hieu, d.ngay_ban_hanh, d.loai, d.con_hieu_luc, d.ngay_hieu_luc,
         d.ngay_het_hieu_luc, d.link_tvpl, chuan_so_hieu(d.so_hieu), d.tvpl_id],
    )  # fmt: skip


def thong_ke(conn: psycopg.Connection) -> dict:
    tt = dict(conn.execute("SELECT trang_thai, count(*) FROM van_ban GROUP BY 1").fetchall())
    return {
        "van_ban": sum(tt.values()),
        "trang_thai": tt,
        "dung_de_tra": conn.execute("SELECT count(*) FROM van_ban WHERE dung_de_tra").fetchone()[0],
        "chunk": conn.execute("SELECT count(*) FROM chunk").fetchone()[0],
        "chunk_tim_kiem": conn.execute(
            "SELECT count(*) FROM chunk c JOIN van_ban v USING (tvpl_id)"
            " WHERE c.embed AND v.dung_de_tra"
        ).fetchone()[0],
    }


def tinh_lai(conn: psycopg.Connection, hom_nay: date) -> None:
    """Tính lại toàn kho: nối quan hệ, trạng thái, dung_de_tra, vai_tro, qltt_lien_quan."""
    with conn.transaction():
        conn.execute(
            "UPDATE quan_he_van_ban q SET den = v.tvpl_id FROM van_ban v"
            " WHERE v.so_hieu_chuan = q.den_so_hieu"
        )
        conn.execute(
            """
            UPDATE van_ban v SET trang_thai = CASE
                WHEN NOT EXISTS (SELECT 1 FROM chunk c WHERE c.tvpl_id = v.tvpl_id) THEN 'loi'
                WHEN NOT v.con_hieu_luc
                    OR (v.ngay_het_hieu_luc IS NOT NULL AND v.ngay_het_hieu_luc <= %(d)s)
                    THEN 'het_hieu_luc'
                WHEN v.ngay_hieu_luc IS NOT NULL AND v.ngay_hieu_luc > %(d)s THEN 'chua_hieu_luc'
                ELSE 'hieu_luc' END
            """,
            {"d": hom_nay},
        )
        # Dùng để tra = đang hiệu lực, và không bị thay bởi một VBHN đang hiệu lực:
        #   - văn bản gốc của VBHN;
        #   - văn bản sửa đổi đã hợp nhất, nếu nó chỉ sửa đúng văn bản gốc (chi_sua_van_ban, xem
        #     chi_sua_mot_van_ban). Văn bản sửa nhiều văn bản (17/2022, 14/2022, 124/2021, Luật Thủy
        #     sản sửa Luật XLVPHC) vẫn để tra: phần sửa văn bản khác chưa được hợp nhất ở đâu.
        #   - VBHN cũ khi có VBHN mới hơn của cùng văn bản gốc.
        #   - văn bản bị một văn bản đang hiệu lực thay thế / bãi bỏ cả văn bản (Điều hiệu lực thi
        #     hành, sua_doi.chi_dan_hieu_luc; hoặc quan hệ nhập tay). Sheet vẫn ghi còn hiệu lực thì
        #     qltt sua-doi báo để chú sửa.
        conn.execute(
            """
            UPDATE van_ban v SET dung_de_tra = v.trang_thai = 'hieu_luc' AND NOT v.go_khoi_sheet
                AND NOT EXISTS (
                    SELECT 1 FROM quan_he_van_ban q JOIN van_ban h ON h.tvpl_id = q.tu
                    WHERE q.den = v.tvpl_id AND q.loai = 'hop_nhat' AND h.trang_thai = 'hieu_luc')
                AND NOT EXISTS (
                    SELECT 1 FROM quan_he_van_ban q
                    JOIN van_ban h ON h.tvpl_id = q.tu AND h.trang_thai = 'hieu_luc'
                    JOIN quan_he_van_ban qg ON qg.tu = q.tu AND qg.loai = 'hop_nhat'
                    WHERE q.den = v.tvpl_id AND q.loai = 'hop_nhat_sua'
                        AND v.chi_sua_van_ban = qg.den_so_hieu)
                AND NOT EXISTS (
                    SELECT 1 FROM quan_he_van_ban q1
                    JOIN quan_he_van_ban q2 ON q2.den = q1.den AND q2.loai = 'hop_nhat'
                        AND q2.tu <> q1.tu
                    JOIN van_ban h ON h.tvpl_id = q2.tu
                    WHERE q1.tu = v.tvpl_id AND q1.loai = 'hop_nhat'
                        AND h.trang_thai = 'hieu_luc' AND h.ngay_ban_hanh > v.ngay_ban_hanh)
                AND NOT EXISTS (
                    SELECT 1 FROM quan_he_van_ban q JOIN van_ban h ON h.tvpl_id = q.tu
                    WHERE q.den = v.tvpl_id AND q.loai IN ('thay_the', 'bai_bo')
                        AND q.nguon IN ('dieu_hieu_luc', 'tay') AND h.trang_thai = 'hieu_luc')
            """
        )
        conn.execute(
            """
            UPDATE van_ban v SET vai_tro = x.vai_tro FROM (
                SELECT tvpl_id, CASE
                    WHEN bool_or(vai_tro = 'xu_phat') AND bool_or(vai_tro = 'quy_pham')
                        THEN 'ca_hai'
                    WHEN bool_or(vai_tro = 'xu_phat') THEN 'xu_phat' ELSE 'quy_pham' END AS vai_tro
                FROM chunk WHERE embed GROUP BY tvpl_id) x
            WHERE x.tvpl_id = v.tvpl_id
            """
        )
        # Có Điều thẩm quyền nhắc Quản lý thị trường, hoặc được một VBHN như vậy hợp nhất
        conn.execute(
            """
            UPDATE van_ban v SET qltt_lien_quan = EXISTS (
                SELECT 1 FROM chunk c WHERE c.tvpl_id = v.tvpl_id
                    AND c.loai_chunk = 'tham_quyen' AND c.noi_dung ILIKE '%%quản lý thị trường%%')
            """
        )
        conn.execute(
            """
            UPDATE van_ban v SET qltt_lien_quan = true FROM quan_he_van_ban q
            JOIN van_ban h ON h.tvpl_id = q.tu AND h.qltt_lien_quan
            WHERE q.den = v.tvpl_id AND q.loai = 'hop_nhat'
            """
        )


def dong_tu_sheet(d: dict, tvpl_id: int, ngay_tu_serial) -> DongSheet | str:
    """Dòng thô từ google_io.doc_sheet → DongSheet, hoặc chuỗi mô tả lỗi."""
    from qltt.google_io import bo_dau

    def ngay(gt, ten_cot, bat_buoc):
        if gt in ("", None):
            if bat_buoc:
                raise ValueError(f"thiếu {ten_cot}")
            return None
        if not isinstance(gt, int | float):
            raise ValueError(f"{ten_cot} không phải kiểu ngày")
        return ngay_tu_serial(gt)

    try:
        loai = LOAI.get(bo_dau(d["loai"]))
        if loai is None:
            raise ValueError(f"loại văn bản lạ: {d['loai']!r}")
        if not isinstance(d["con_hieu_luc"], bool):
            raise ValueError("ô Còn hiệu lực không phải hộp kiểm")
        return DongSheet(
            tvpl_id=tvpl_id,
            so_hieu=chuan(str(d["so_hieu"])),
            ngay_ban_hanh=ngay(d["ngay_ban_hanh"], "Ngày ban hành", True),
            loai=loai,
            con_hieu_luc=d["con_hieu_luc"],
            ngay_hieu_luc=ngay(d["ngay_hieu_luc"], "Ngày có hiệu lực", False),
            ngay_het_hieu_luc=ngay(d["ngay_het_hieu_luc"], "Hiệu lực đến", False),
            link_tvpl=str(d["link_tvpl"]),
            dong=d["dong"],
        )
    except ValueError as e:
        return f"dòng {d.get('dong')}: {e}"
