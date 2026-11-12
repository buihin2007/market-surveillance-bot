"""Cổng kiểm sau parse: những tính chất mọi văn bản parse đúng đều phải có.

loi: trượt gate, văn bản không được nạp. canh_bao: vẫn nạp, ghi lại để báo chú.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from qltt.parse import VanBanParse, chuan_so_hieu

R_KHUNG = re.compile(r"từ\s+([\d.]+)\s+đồng\s+đến\s+([\d.]+)\s+đồng")


@dataclass
class KetQuaGate:
    loi: list[str] = field(default_factory=list)
    canh_bao: list[str] = field(default_factory=list)

    @property
    def qua(self) -> bool:
        return not self.loi


def kiem(
    vb: VanBanParse, so_hieu_sheet: str, ngay_sheet: date | None, la_vbhn: bool = False
) -> KetQuaGate:
    kq = KetQuaGate()

    if vb.so_hieu is None:
        kq.loi.append("Không tìm thấy dòng 'Số:' ở đầu văn bản")
    elif chuan_so_hieu(vb.so_hieu) != chuan_so_hieu(so_hieu_sheet):
        kq.loi.append(
            f"Số trong file {vb.so_hieu} khác sheet {so_hieu_sheet}: có thể tải nhầm file"
        )
    if ngay_sheet and vb.ngay_ky and vb.ngay_ky != ngay_sheet:
        kq.canh_bao.append(
            f"Ngày ký trong file {vb.ngay_ky:%d/%m/%Y} khác sheet {ngay_sheet:%d/%m/%Y}"
        )

    if not vb.dieu:
        kq.loi.append("Không tìm thấy Điều nào")
        return kq

    # Điều: bắt đầu từ 1, không giảm, không nhảy quá 1 (4 → 4a → 5 là hợp lệ)
    so = [d.so for d in vb.dieu]
    if so[0] != 1:
        kq.loi.append(f"Điều đầu tiên là Điều {so[0]}, không phải Điều 1")
    for a, b in zip(vb.dieu, vb.dieu[1:], strict=False):
        if b.so < a.so or b.so > a.so + 1 or (b.so == a.so and b.suffix <= a.suffix):
            loi = f"Số Điều không liên tục: Điều {a.ky_hieu} → Điều {b.ky_hieu}"
            # VBHN bỏ hẳn Điều đã bị bãi bỏ (17/VBHN-BCT: Điều 35 → 37) → chỉ cảnh báo
            if la_vbhn and b.so > a.so + 1:
                kq.canh_bao.append(loi + " (VBHN có thể bỏ Điều đã bị bãi bỏ)")
            else:
                kq.loi.append(loi)

    # khoản trong mỗi Điều: tăng dần (1 → 2 → 2a → 3). Nguồn có lỗi gõ thật (Luật Thủy sản
    # Điều 32 đánh hai khoản 1); chữ vẫn nằm trong Điều nên lệch khoản chỉ là cảnh báo
    for d in vb.dieu:
        for a, b in zip(d.khoan, d.khoan[1:], strict=False):
            if (b.so, b.suffix) <= (a.so, a.suffix) or b.so > a.so + 1:
                kq.canh_bao.append(
                    f"Điều {d.ky_hieu}: khoản {a.so}{a.suffix} → khoản {b.so}{b.suffix}"
                )
                break

    for d in vb.dieu:
        for x, y in R_KHUNG.findall(d.text):
            if int(x.replace(".", "")) >= int(y.replace(".", "")):
                kq.loi.append(f"Điều {d.ky_hieu}: khung phạt từ {x} đến {y} đồng không hợp lệ")

    if vb.co_file_nhung:
        kq.canh_bao.append(
            "Có đối tượng nhúng (file đính kèm hoặc công thức), phần đó không được đọc"
        )
    return kq
