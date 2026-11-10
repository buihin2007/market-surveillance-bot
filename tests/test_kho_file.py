import hashlib

from qltt import kho_file

DOCX = b"PK\x03\x04 noi dung docx gia"


def file_drive(ten, noi_dung=DOCX, **them):
    return {"id": ten, "name": ten, "md5Checksum": hashlib.md5(noi_dung).hexdigest(), **them}


def tai_tu(bang: dict, goi: list):
    def tai(f):
        goi.append(f["name"])
        return bang[f["name"]]

    return tai


def test_tai_file_moi_vao_dung_cho(tmp_path):
    f = file_drive("98_2020_ND-CP_406627.docx")
    kq = kho_file.dong_bo_file([f], tmp_path, tai_tu({f["name"]: DOCX}, []))

    dich = tmp_path / "406627" / f"{f['md5Checksum']}.docx"
    assert kq.moi == [dich]
    assert dich.read_bytes() == DOCX
    assert list(tmp_path.rglob("*.part")) == []


def test_chay_lai_khong_tai_lai(tmp_path):
    f = file_drive("98_2020_ND-CP_406627.docx")
    goi = []
    tai = tai_tu({f["name"]: DOCX}, goi)
    kho_file.dong_bo_file([f], tmp_path, tai)

    kq = kho_file.dong_bo_file([f], tmp_path, tai)

    assert goi == [f["name"]]  # chỉ tải ở lần đầu
    assert (len(kq.moi), len(kq.da_co)) == (0, 1)


def test_file_doi_tren_drive_thanh_ban_sao_moi(tmp_path):
    cu = file_drive("98_2020_ND-CP_406627.docx")
    moi_nd = DOCX + b" ban sua"
    moi = file_drive("98_2020_ND-CP_406627.docx", moi_nd)
    kho_file.dong_bo_file([cu], tmp_path, tai_tu({cu["name"]: DOCX}, []))

    kq = kho_file.dong_bo_file([moi], tmp_path, tai_tu({moi["name"]: moi_nd}, []))

    assert len(kq.moi) == 1
    assert len(list((tmp_path / "406627").glob("*.docx"))) == 2  # bản cũ không bị ghi đè


def test_md5_khong_khop_thi_khong_ghi(tmp_path):
    f = file_drive("98_2020_ND-CP_406627.docx")
    kq = kho_file.dong_bo_file([f], tmp_path, tai_tu({f["name"]: DOCX + b"hong"}, []))

    assert kq.moi == [] and "md5 không khớp" in kq.loi[0]
    assert list(tmp_path.rglob("*")) == []


def test_khong_phai_docx_thi_bao_loi(tmp_path):
    noi_dung = b"<html>trang loi</html>"
    f = file_drive("98_2020_ND-CP_406627.docx", noi_dung)
    kq = kho_file.dong_bo_file([f], tmp_path, tai_tu({f["name"]: noi_dung}, []))

    assert "không phải docx" in kq.loi[0]


def test_mot_file_loi_khong_chan_file_khac(tmp_path):
    hong = file_drive("17_2022_ND-CP_502253.docx")
    tot = file_drive("98_2020_ND-CP_406627.docx")

    def tai(f):
        if f is hong:
            raise TimeoutError("hết giờ")
        return DOCX

    kq = kho_file.dong_bo_file([hong, tot], tmp_path, tai)

    assert len(kq.moi) == 1
    assert "TimeoutError" in kq.loi[0]


def test_ten_khong_co_ma_thi_bo_qua(tmp_path):
    kq = kho_file.dong_bo_file([file_drive("ghi chu.docx")], tmp_path, tai_tu({}, []))
    assert kq.bo_qua == ["ghi chu.docx: tên file không có mã TVPL"]


def test_google_docs_khong_md5_dat_ten_theo_thoi_diem_sua(tmp_path):
    f = {
        "id": "x",
        "name": "98_2020_ND-CP_406627",
        "mimeType": kho_file.GDOC_MIME,
        "modifiedTime": "2026-11-10T06:00:00.000Z",
    }
    kq = kho_file.dong_bo_file([f], tmp_path, lambda _: DOCX)

    assert kq.moi == [tmp_path / "406627" / "gdoc_2026-11-10T06-00-00-000Z.docx"]
