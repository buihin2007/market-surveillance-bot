# Bộ đánh giá

`cases.jsonl`: mỗi dòng một tình huống. Tạo lần đầu từ Sổ tay nghiệp vụ QLTT (40 hành vi, bản 26/10/2026) + 3 câu ngoài phạm vi; từ nay sửa thẳng file này.

| Trường | Ý nghĩa |
|---|---|
| `id` | Mã hành vi trong sổ tay (QLTT-xx-yyy) hoặc PV-xxx |
| `nhom` | `chinh`: có căn cứ. `khong_co`: kho không có quy định, bot phải nói không tìm thấy |
| `cau_hoi` | Cách chú gõ ngoài đời (bản đầu do Claude viết, cần chú sửa cho giống thật) |
| `cau_hoi_nguyen_van` | Tên hành vi trong sổ tay, gần câu chữ luật: dễ tìm hơn, chỉ để so |
| `can_cu` | Danh sách `{van_ban, dieu, khoan, diem}` theo văn bản gốc; VBHN tự quy đổi. `khoan` trống = cả Điều |
| `cap_cham` | `dieu`: trúng nếu ra bất kỳ chunk nào của Điều (khoản phụ thuộc giá trị hàng). `khoan`: phải ra đúng khoản hoặc chunk cả Điều |
| `kiem` | `so_tay` (từ sổ tay, chưa rà soát), `claude_de_xuat` (Claude tra trong kho, cần người kiểm), `nguoi_da_kiem` |
| `giu_lai` | `true`: không nhìn khi tinh chỉnh, chỉ chạy ở lần đo cuối |
| `khung_phat`, `bo_sung`, `khac_phuc` | Lấy từ sổ tay, chưa rà soát; dùng ở GĐ 2 để chấm câu trả lời |

Kiểm mọi căn cứ trỏ đúng chunk: `uv run qltt eval kiem-tra`.
