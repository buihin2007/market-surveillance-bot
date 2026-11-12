-- Schema chatbot QLTT. Chạy bằng: uv run qltt db init (chạy lại nhiều lần không sao).
-- Thiết kế: qltt-kien-truc-du-lieu.md mục 3.
--
-- Ba loại bảng (danh sách ở src/qltt/db.py, có test kiểm):
--   DẪN XUẤT  dựng lại được từ Sheet + Drive; lệnh rebuild được phép xóa
--   GỐC       không dựng lại được (xác nhận của chú, lịch sử hỏi đáp); không xóa tự động, phải backup
--   CACHE     dựng lại được nhưng tốn tiền API; giữ qua các lần rebuild
-- Quy tắc: bảng GỐC và CACHE không có khóa ngoại trỏ tới bảng DẪN XUẤT,
-- và không lưu id tự tăng của bảng DẪN XUẤT (id đổi sau mỗi lần rebuild).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- ============================ DẪN XUẤT ============================

-- 1 dòng = 1 văn bản.
CREATE TABLE IF NOT EXISTS van_ban (
    tvpl_id           integer PRIMARY KEY,  -- mã trong link TVPL (-{id}.aspx) và trong tên file
    -- 7 cột chú điền trên sheet
    so_hieu           text    NOT NULL,
    ngay_ban_hanh     date    NOT NULL,
    loai              text    NOT NULL CHECK (loai IN (
                          'luat', 'phap_lenh', 'nghi_dinh', 'vbhn',
                          'thong_tu', 'ttlt', 'quyet_dinh', 'nghi_quyet')),
    con_hieu_luc      boolean NOT NULL,
    ngay_hieu_luc     date,
    ngay_het_hieu_luc date,
    link_tvpl         text    NOT NULL,
    -- lấy từ sheet và file
    so_hieu_chuan     text    NOT NULL,     -- so_hieu đã chuẩn hóa ký tự, để so với dòng "Số:" trong file
    ten               text,
    chi_sua_van_ban   text,                 -- văn bản sửa đổi chỉ sửa đúng một văn bản: số hiệu chuẩn của nó
    drive_file_id     text,
    file_hash         text,                 -- md5 của file đang dùng; đổi thì parse lại
    -- kết quả parse lần gần nhất (file mới trượt gate thì giữ nguyên chunk cũ, chỉ ghi canh_bao)
    parse_luc         timestamptz,
    so_dieu           integer,
    so_chunk          integer,
    -- bot tính lại mỗi lần đồng bộ và ở job 00:05
    trang_thai        text    NOT NULL DEFAULT 'loi' CHECK (trang_thai IN (
                          'chua_hieu_luc', 'hieu_luc', 'het_hieu_luc', 'loi')),
    dung_de_tra       boolean NOT NULL DEFAULT false,
    vai_tro           text    CHECK (vai_tro IN ('xu_phat', 'quy_pham', 'ca_hai')),
    qltt_lien_quan    boolean NOT NULL DEFAULT false,
    mucphat_cua       text    CHECK (mucphat_cua IN ('ca_nhan', 'to_chuc')),
    mucphat_ngoai_le  jsonb   NOT NULL DEFAULT '[]',
    -- van_ban: câu "Mức phạt tiền quy định tại … là mức phạt đối với cá nhân/tổ chức";
    -- suy_ra: chỉ có câu "tổ chức gấp 02 lần cá nhân" / "cá nhân bằng 1/2 tổ chức" → cần người xác nhận
    mucphat_cua_nguon text    CHECK (mucphat_cua_nguon IN ('van_ban', 'suy_ra')),
    canh_bao          jsonb   NOT NULL DEFAULT '[]',  -- cảnh báo của lần parse gần nhất
    loi               jsonb   NOT NULL DEFAULT '[]',  -- lỗi gate lần gần nhất; có chunk cũ thì vẫn dùng chunk cũ
    dong_bo_luc       timestamptz,
    -- số hiệu VBHN lặp lại theo năm (03/VBHN-BCT có bản 2022 và 2025) nên phải kèm ngày
    UNIQUE (so_hieu_chuan, ngay_ban_hanh)
);
-- DB tạo trước 11/11/2026: thêm cột không cần xóa bảng
ALTER TABLE van_ban ADD COLUMN IF NOT EXISTS mucphat_cua_nguon text
    CHECK (mucphat_cua_nguon IN ('van_ban', 'suy_ra'));

-- Đơn vị tìm kiếm, 2 cấp: Điều (toàn văn) và khoản.
-- File đổi: xóa chunk cũ và ghi chunk mới trong một transaction (không giữ phiên bản cũ).
CREATE TABLE IF NOT EXISTS chunk (
    id             bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tvpl_id        integer NOT NULL REFERENCES van_ban ON DELETE CASCADE,
    cap            text    NOT NULL CHECK (cap IN ('dieu', 'khoan', 'phu_luc')),
    dieu_so        integer,                      -- trống với phụ lục
    dieu_suffix    text    NOT NULL DEFAULT '',  -- "a" trong Điều 4a
    khoan_so       integer,                      -- trống nếu cap = 'dieu'
    khoan_suffix   text    NOT NULL DEFAULT '',  -- "a" trong khoản 2a
    phu_luc_so     text,                         -- "01", "II"; chỉ với cap = 'phu_luc'
    cha_id         bigint  REFERENCES chunk ON DELETE CASCADE,  -- chunk Điều chứa khoản này
    duong_dan      text    NOT NULL,             -- "Điều 17 khoản 1"
    phan_ten       text,
    chuong_ten     text,
    muc_ten        text,
    dieu_ten       text,
    loai_chunk     text    NOT NULL CHECK (loai_chunk IN (
                       'hanh_vi', 'xu_phat_bo_sung', 'khac_phuc', 'giai_thich',
                       'quy_dinh_chung', 'tham_quyen', 'hieu_luc', 'phu_luc', 'khac')),
    vai_tro        text    NOT NULL CHECK (vai_tro IN ('xu_phat', 'quy_pham')),
    noi_dung       text    NOT NULL,
    noi_dung_embed text,                         -- noi_dung kèm prefix ngữ cảnh
    embed_hash     text,                         -- khóa tra embed_cache
    embedding      vector,                       -- số chiều theo EMBED_MODEL (bge-m3: 1024)
    tsv            tsvector,
    embed          boolean NOT NULL DEFAULT true -- false: thẩm quyền, hiệu lực (không tìm kiếm)
);
CREATE INDEX IF NOT EXISTS chunk_vi_tri ON chunk (tvpl_id, dieu_so, dieu_suffix, khoan_so, khoan_suffix);
CREATE INDEX IF NOT EXISTS chunk_cha ON chunk (cha_id);
CREATE INDEX IF NOT EXISTS chunk_tsv ON chunk USING gin (tsv);
-- Chưa tạo index vector (HNSW): kho dưới 100 nghìn chunk, quét chính xác trước,
-- đo thời gian ở GĐ 1 rồi mới quyết.

-- Một dòng = một chỗ văn bản vb_sua sửa vào văn bản khác. (GĐ 3, có thể chỉnh khi viết phần trích.)
-- Khung phạt tách từ chữ khoản xử phạt (muc_phat.py). Dựng lại toàn bộ sau mỗi lần nạp.
-- Mỗi dòng: một hành vi (khoản hoặc điểm) + khung + điều kiện định lượng. Code tra bảng này để
-- đưa mức phạt; LLM không viết con số.
CREATE TABLE IF NOT EXISTS muc_phat (
    id             serial  PRIMARY KEY,
    chunk_id       integer NOT NULL REFERENCES chunk ON DELETE CASCADE,
    tvpl_id        integer NOT NULL REFERENCES van_ban ON DELETE CASCADE,
    dieu_so        integer,
    dieu_suffix    text    NOT NULL DEFAULT '',
    khoan_so       integer,
    khoan_suffix   text    NOT NULL DEFAULT '',
    diem           text,                 -- null: cả khoản
    hanh_vi        text    NOT NULL,     -- chữ gốc mô tả hành vi
    loai           text    NOT NULL CHECK (loai IN (
                       'tien', 'canh_cao', 'canh_cao_hoac_tien', 'gap_lan', 'lan_gia_tri',
                       'khong_tach', 'sua_doi')),
    tu             bigint,               -- đồng (loai tien, canh_cao_hoac_tien)
    den            bigint,
    he_so          numeric,              -- gap_lan: N; lan_gia_tri: từ N lần
    he_so_den      numeric,              -- lan_gia_tri: đến M lần
    tran           bigint,               -- "nhưng không vượt quá X đồng"
    tham_chieu     jsonb   NOT NULL DEFAULT '[]',  -- gap_lan: các khoản được nhân
    hanh_vi_tai    jsonb   NOT NULL DEFAULT '[]',  -- bậc phạt cho hành vi định nghĩa ở khoản khác
    dk_tu          numeric,              -- điều kiện định lượng (giá trị hàng, số lợi, số lượng)
    dk_tu_bao_gom  boolean,
    dk_den         numeric,
    dk_den_bao_gom boolean,
    dk_don_vi      text,
    dk_doi_tuong   text    CHECK (dk_doi_tuong IN ('gia_tri', 'so_loi', 'so_luong')),
    dk_chu         text,                 -- chữ gốc của điều kiện
    nguon          text    NOT NULL DEFAULT ''     -- chữ gốc của khung
);
CREATE INDEX IF NOT EXISTS muc_phat_dieu ON muc_phat (tvpl_id, dieu_so, dieu_suffix, khoan_so);

-- Hình thức xử phạt bổ sung / biện pháp khắc phục hậu quả tách theo biện pháp (bien_phap.py).
-- Dựng lại sau mỗi lần nạp. ap_dung: [{"khoan": 1, "diem": ["a", "b"]}] (diem rỗng: cả khoản);
-- ca_dieu: áp cho mọi hành vi của Điều; tach_duoc = false: không đọc được dẫn chiếu, bot trích
-- nguyên văn.
CREATE TABLE IF NOT EXISTS bien_phap (
    id          serial  PRIMARY KEY,
    chunk_id    integer NOT NULL REFERENCES chunk ON DELETE CASCADE,
    tvpl_id     integer NOT NULL REFERENCES van_ban ON DELETE CASCADE,
    dieu_so     integer,
    dieu_suffix text    NOT NULL DEFAULT '',
    khoan_so    integer,
    diem        text,
    loai        text    NOT NULL CHECK (loai IN ('bo_sung', 'khac_phuc')),
    noi_dung    text    NOT NULL,
    ap_dung     jsonb   NOT NULL DEFAULT '[]',
    ca_dieu     boolean NOT NULL DEFAULT false,
    tach_duoc   boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS bien_phap_dieu ON bien_phap (tvpl_id, dieu_so, dieu_suffix);

CREATE TABLE IF NOT EXISTS sua_doi (
    id                bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vb_sua            integer NOT NULL REFERENCES van_ban ON DELETE CASCADE,
    chunk_sua_id      bigint  REFERENCES chunk ON DELETE CASCADE,    -- chunk chứa nội dung mới
    vb_dich_so_hieu   text    NOT NULL,                              -- số hiệu văn bản bị sửa, như ghi trong vb_sua
    vb_dich           integer REFERENCES van_ban ON DELETE SET NULL, -- trống nếu văn bản bị sửa chưa có trong kho
    dich_dieu         integer,
    dich_dieu_suffix  text    NOT NULL DEFAULT '',
    dich_khoan        integer,
    dich_khoan_suffix text    NOT NULL DEFAULT '',
    dich_diem         text,
    dich_chunk_id     bigint  REFERENCES chunk ON DELETE SET NULL,   -- trống nếu chưa tìm được đích
    loai              text    NOT NULL CHECK (loai IN ('sua_doi', 'bo_sung', 'bai_bo', 'thay_cum_tu')),
    ngay_hieu_luc     date,
    nguon_trich       text    NOT NULL CHECK (nguon_trich IN ('regex', 'llm')),
    da_xac_nhan       boolean NOT NULL DEFAULT false                 -- chép từ xac_nhan mỗi lần đồng bộ
);
CREATE INDEX IF NOT EXISTS sua_doi_dich ON sua_doi (vb_dich, dich_dieu, dich_dieu_suffix);
CREATE INDEX IF NOT EXISTS sua_doi_dich_chunk ON sua_doi (dich_chunk_id);

-- Chú thích "[n]" trong văn bản hợp nhất: khoản nào được sửa bởi nghị định nào.
CREATE TABLE IF NOT EXISTS chu_thich_vbhn (
    tvpl_id      integer NOT NULL REFERENCES van_ban ON DELETE CASCADE,
    so           integer NOT NULL,                           -- n trong "[n]"
    chunk_id     bigint  REFERENCES chunk ON DELETE CASCADE, -- nơi "[n]" xuất hiện
    noi_dung     text    NOT NULL,
    vb_sua       text,                                       -- số hiệu văn bản sửa đổi trích được
    PRIMARY KEY (tvpl_id, so)
);

-- Quan hệ mức văn bản, đọc là "tu <loai> den": VBHN hop_nhat nghị định gốc, nghị định mới thay_the nghị định cũ.
CREATE TABLE IF NOT EXISTS quan_he_van_ban (
    tu          integer NOT NULL REFERENCES van_ban ON DELETE CASCADE,
    den_so_hieu text    NOT NULL,
    den         integer REFERENCES van_ban ON DELETE SET NULL,  -- trống nếu văn bản kia chưa có trong kho
    loai        text    NOT NULL CHECK (loai IN (
                    'thay_the', 'sua_doi', 'bai_bo', 'hop_nhat', 'hop_nhat_sua', 'huong_dan')),
    -- hop_nhat: VBHN → văn bản gốc; hop_nhat_sua: VBHN → văn bản sửa đổi đã được hợp nhất
    nguon       text    NOT NULL CHECK (nguon IN ('dieu_hieu_luc', 'dau_vbhn', 'tay')),
    PRIMARY KEY (tu, den_so_hieu, loai)
);
-- 11/11 (GĐ 3.1): thêm nguồn ten_dieu (tên Điều "Sửa đổi … Nghị định số X" của văn bản sửa đổi)
ALTER TABLE quan_he_van_ban DROP CONSTRAINT IF EXISTS quan_he_van_ban_nguon_check;
ALTER TABLE quan_he_van_ban ADD CONSTRAINT quan_he_van_ban_nguon_check
    CHECK (nguon IN ('dieu_hieu_luc', 'dau_vbhn', 'ten_dieu', 'tay'));

-- Dẫn chiếu từ một chunk sang văn bản khác, một bước. (GĐ 3.)
CREATE TABLE IF NOT EXISTS dan_chieu (
    id               bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tu_chunk_id      bigint  NOT NULL REFERENCES chunk ON DELETE CASCADE,
    den_loai         text    NOT NULL CHECK (den_loai IN ('ten_luat', 'so_hieu', 'chu_de')),
    den_khoa         text    NOT NULL,  -- tên luật chuẩn / số hiệu / "pháp luật về X"
    den_tvpl_id      integer REFERENCES van_ban ON DELETE SET NULL,
    den_dieu         integer,
    den_dieu_suffix  text    NOT NULL DEFAULT '',
    den_khoan        integer,
    den_khoan_suffix text    NOT NULL DEFAULT '',
    trang_thai       text    NOT NULL DEFAULT 'chua_anh_xa' CHECK (trang_thai IN (
                         'ok', 'thieu_van_ban', 'thieu_dieu', 'chua_anh_xa'))
);
CREATE INDEX IF NOT EXISTS dan_chieu_tu ON dan_chieu (tu_chunk_id);


-- ============================== GỐC ==============================

-- Mỗi lần /dong-bo một dòng.
CREATE TABLE IF NOT EXISTS nhat_ky_dong_bo (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bat_dau  timestamptz NOT NULL DEFAULT now(),
    ket_thuc timestamptz,
    nguoi    bigint,  -- Telegram chat_id; trống = chạy từ dòng lệnh
    tom_tat  jsonb,
    bao_cao  text
);

-- Điều bot hỏi chú và câu trả lời của chú. Dựng lại DB xong thì áp lại, không hỏi lần hai.
CREATE TABLE IF NOT EXISTS xac_nhan (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    loai          text   NOT NULL CHECK (loai IN ('go_tim_kiem', 'mucphat_cua', 'sua_doi_llm')),
    khoa          text   NOT NULL,  -- khóa tự nhiên, ví dụ "tvpl:406627"
    noi_dung      jsonb  NOT NULL,  -- điều được hỏi; nội dung đổi thì hỏi lại
    noi_dung_hash text   NOT NULL,
    quyet_dinh    text   CHECK (quyet_dinh IN ('dong_y', 'tu_choi')),  -- trống = đang chờ chú bấm
    tao_luc       timestamptz NOT NULL DEFAULT now(),
    tra_loi_luc   timestamptz,
    nguoi         bigint,
    UNIQUE (loai, khoa, noi_dung_hash)
);

-- Mỗi câu hỏi một dòng, kèm vết từng bước để tra khi chú bấm "Báo sai".
CREATE TABLE IF NOT EXISTS chat_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    luc             timestamptz NOT NULL DEFAULT now(),
    kenh            text   NOT NULL DEFAULT 'cli' CHECK (kenh IN ('cli', 'eval', 'telegram')),
    nguoi           bigint,  -- Telegram chat_id
    cau_hoi         text   NOT NULL,
    loai_ket_qua    text,    -- tra_loi | ngoai_pham_vi | khong_tim_thay | nguyen_van | loi
    ket_qua         jsonb,
    vet             jsonb,   -- đầu ra, thời gian, token của từng node
    thoi_gian_ms    integer,
    bao_sai         boolean NOT NULL DEFAULT false,
    bao_sai_ghi_chu text
);
CREATE INDEX IF NOT EXISTS chat_log_luc ON chat_log (luc);

-- Chú bấm "Báo sai" (một câu trả lời có thể bị báo nhiều lần). ikm xem vết trong chat_log, ghi
-- nguyên nhân (khâu hỏng), sửa, đưa thành case eval, rồi báo lại chú.
CREATE TABLE IF NOT EXISTS bao_sai (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_log_id   bigint NOT NULL REFERENCES chat_log ON DELETE CASCADE,
    luc           timestamptz NOT NULL DEFAULT now(),
    nguoi         bigint,
    ly_do         text,
    trang_thai    text   NOT NULL DEFAULT 'moi'
                  CHECK (trang_thai IN ('moi', 'da_sua', 'khong_loi', 'chua_sua_duoc')),
    kieu          text,      -- nút chú bấm: sai_hanh_vi | sai_muc_phat | sai_bien_phap | ...
    nguyen_nhan   text,      -- khâu hỏng ikm xác nhận (ràng buộc ở dưới)
    case_id       text,      -- case eval tạo từ báo cáo này
    ghi_chu_xu_ly text,
    xu_ly_luc     timestamptz,
    da_bao_lai    boolean NOT NULL DEFAULT false  -- đã nhắn lại chú kết quả xử lý
);
CREATE INDEX IF NOT EXISTS bao_sai_trang_thai ON bao_sai (trang_thai);
-- Bản bao_sai đầu (11/11) chưa có kieu và nguyen_nhan chưa có bien_phap: thêm / đặt lại ràng buộc.
ALTER TABLE bao_sai ADD COLUMN IF NOT EXISTS kieu text;
ALTER TABLE bao_sai DROP CONSTRAINT IF EXISTS bao_sai_kieu_check;
ALTER TABLE bao_sai ADD CONSTRAINT bao_sai_kieu_check CHECK (kieu IN (
    'sai_hanh_vi', 'sai_muc_phat', 'sai_bien_phap', 'van_ban_cu', 'khong_tim_thay',
    'sai_quy_dinh', 'khac'));
ALTER TABLE bao_sai DROP CONSTRAINT IF EXISTS bao_sai_nguyen_nhan_check;
ALTER TABLE bao_sai ADD CONSTRAINT bao_sai_nguyen_nhan_check CHECK (nguyen_nhan IN (
    'phan_loai', 'tim_kiem', 'chon', 'muc_phat', 'bien_phap', 'kho_thieu', 'khong_loi', 'khac'));


-- ============================= CACHE =============================

-- Embedding đã trả tiền, tra theo hash của (model + noi_dung_embed).
CREATE TABLE IF NOT EXISTS embed_cache (
    hash      text PRIMARY KEY,
    model     text NOT NULL,
    embedding vector NOT NULL,  -- nhiều model, nhiều số chiều
    tao_luc   timestamptz NOT NULL DEFAULT now()
);

-- Cache câu trả lời LLM theo (model, phiên bản prompt, đầu vào): eval chạy lại không tốn tiền,
-- kết quả lặp lại được. Không có khóa ngoại.
CREATE TABLE IF NOT EXISTS llm_cache (
    hash   text PRIMARY KEY,
    model  text NOT NULL,
    dau_ra jsonb NOT NULL,
    tao_luc timestamptz NOT NULL DEFAULT now()
);

-- 11/11 (GĐ 3.2): từng chỉ dẫn sửa đổi của văn bản sửa đổi, trỏ tới Điều / khoản bị sửa.
-- Dựng lại toàn bộ sau nạp (sua_doi.dung_chi_tiet). Dùng để cảnh báo khi bot trích Điều / khoản đã
-- bị sửa mà văn bản bot đọc (gốc hoặc VBHN cũ) chưa có chữ mới.
CREATE TABLE IF NOT EXISTS sua_doi_chi_tiet (
    id           serial  PRIMARY KEY,
    tu           integer NOT NULL REFERENCES van_ban ON DELETE CASCADE,  -- văn bản sửa đổi
    chunk_id     integer NOT NULL REFERENCES chunk ON DELETE CASCADE,    -- khoản / Điều chứa chỉ dẫn
    vi_tri_tu    text    NOT NULL,           -- "khoản 3 Điều 1" của văn bản sửa đổi
    den_so_hieu  text    NOT NULL,
    den          integer REFERENCES van_ban ON DELETE SET NULL,
    dieu_so      integer,                    -- NULL: chỉ dẫn cho cả văn bản (đổi tên, thay cụm từ)
    dieu_suffix  text    NOT NULL DEFAULT '',
    khoan        integer[] NOT NULL DEFAULT '{}',  -- rỗng: cả Điều
    hanh_dong    text    NOT NULL,
    mo_ta        text    NOT NULL,           -- câu chỉ dẫn (bỏ phần trong ngoặc kép)
    noi_dung_moi text    NOT NULL DEFAULT '',  -- phần trong ngoặc kép: chữ mới
    chac         boolean NOT NULL            -- false: văn bản đích đoán (Điều sửa nhiều văn bản)
);
CREATE INDEX IF NOT EXISTS sua_doi_chi_tiet_den ON sua_doi_chi_tiet (den, dieu_so, dieu_suffix);
-- 12/11: thêm khong_thuc_hien (nghị quyết 19/2026, 66.18/2026: "Không thực hiện thủ tục … tại Điều …")
ALTER TABLE sua_doi_chi_tiet DROP CONSTRAINT IF EXISTS sua_doi_chi_tiet_hanh_dong_check;
ALTER TABLE sua_doi_chi_tiet ADD CONSTRAINT sua_doi_chi_tiet_hanh_dong_check
    CHECK (hanh_dong IN ('sua_doi', 'bo_sung', 'bai_bo', 'thay_cum_tu', 'khong_thuc_hien'));

-- 12/11 (GĐ 3.5): dòng sheet bị xóa → giữ dữ liệu nhưng thôi dùng để tra (qltt dong-bo)
ALTER TABLE van_ban ADD COLUMN IF NOT EXISTS go_khoi_sheet boolean NOT NULL DEFAULT false;

-- 12/11: chú thích "[n]" nằm ở điểm nào của khoản (dòng "b)[91] …"), để trích "điểm b khoản …
-- được sửa đổi tại …" đúng tới điểm. Cần qltt nap --lam-lai để điền cho VBHN đã nạp.
ALTER TABLE chu_thich_vbhn ADD COLUMN IF NOT EXISTS diem text;
