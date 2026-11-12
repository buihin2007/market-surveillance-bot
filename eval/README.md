# Evaluation set

`cases.jsonl`: one case per line. First built from the QLTT operations handbook (40 violations,
26/10/2026 edition) plus 3 out-of-scope questions; edit this file directly from now on.

| Field | Meaning |
|---|---|
| `id` | Violation code from the handbook (QLTT-xx-yyy) or PV-xxx |
| `nhom` | `chinh`: has a legal basis. `khong_co`: the store has no rule for it; the bot must say nothing was found |
| `loai` | Question type, default `hanh_vi`. `quy_dinh`: asks what a rule says (basis is the regulating article). `ngoai_pham_vi`: authority, validity, criminal liability, other fields. `khac`: greetings etc. The last two are always `khong_co` |
| `cau_hoi` | How the officer would type it (first version written by Claude, to be made realistic by the officer) |
| `cau_hoi_nguyen_van` | Handbook name of the violation, close to the legal wording: easier to find, for comparison only |
| `can_cu` | List of `{van_ban, dieu, khoan, diem}` against the original document; VBHN is mapped automatically. Empty `khoan` = whole article |
| `cap_cham` | `dieu`: a hit is any chunk of the article (the clause depends on the goods value). `khoan`: must return the exact clause or the whole-article chunk |
| `kiem` | `so_tay` (from the handbook, not reviewed), `claude_de_xuat` (found in the store by Claude, needs review), `nguoi_da_kiem` (reviewed by a person) |
| `giu_lai` | `true`: held out; never looked at while tuning, only run in the final measurement |
| `khung_phat`, `bo_sung`, `khac_phuc` | From the handbook, not reviewed; used to grade answers |

Check that every legal basis points to the right chunk: `uv run qltt eval kiem-tra`.

Added 11/11/2026: 9 `quy_dinh` cases (QD-xxx), 4 `ngoai_pham_vi` (NP-xxx), 4 `khac` (KH-xxx),
written by Claude; PV-001 and PV-003 → `ngoai_pham_vi`, PV-002 → `quy_dinh`. `eval tim-kiem`
grades only `hanh_vi` cases; `eval phan-loai` grades classification on all cases.
