# UniRent

UniRent là ứng dụng web Flask giúp sinh viên tại Hà Nội đăng tin và thuê đồ của
nhau. Giao diện hỗ trợ desktop và mobile.

## Tính năng

- Tìm kiếm, lọc và đăng tin cho thuê; quản lý lịch bận và ảnh sản phẩm.
- Tạo và theo dõi đơn thuê, thanh toán VNPay, chat giữa hai bên, bàn giao có
  bằng chứng và đánh giá sau giao dịch.
- Hồ sơ cá nhân, thông báo, xác minh tài khoản và khu vực quản trị để duyệt KYC,
  xử lý tranh chấp.

## Chạy local

Yêu cầu Python và pip. Trên Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Mở <http://127.0.0.1:5000>. Khi `DATABASE_URL` chưa được đặt, ứng dụng dùng
`rental.db` tại thư mục gốc. App không tự tạo hoặc nâng cấp schema khi khởi
động.

Điền các thông tin VNPay sandbox vào `.env` nếu cần kiểm thử thanh toán. Ảnh tin
đăng sử dụng Cloudinary khi `CLOUDINARY_URL` được cấu hình; KYC và bằng chứng
bàn giao được lưu trên filesystem local.

## Database và triển khai

- Trên Render, đặt `DATABASE_URL` thành **Internal Database URL** của PostgreSQL.
  Ứng dụng từ chối khởi chạy nếu biến này thiếu hoặc không phải PostgreSQL.
- Không commit `.env`, URL database, mật khẩu hoặc khóa dịch vụ.
- Chạy migration có chủ đích; ứng dụng không tự thay đổi schema. Lệnh Flask
  Alembic local bị giới hạn vào PostgreSQL thử nghiệm
  `localhost:5432/rental_test` qua `RENTAL_TEST_DATABASE_URL`.
- Các script chuyển dữ liệu production là công cụ riêng: dùng
  `scripts/render_schema_migrate.py` và `scripts/migrate_sqlite_to_render.py`.
  Chạy `--plan`, kiểm tra backup và database đích trước; chỉ dùng `--apply` sau
  khi xác nhận đúng target. Không dùng importer local để ghi production.
- Filesystem của Web Service Render có thể mất file khi deploy/restart. Không
  xem `static/uploads/` hoặc `instance/private_uploads/` là lưu trữ bền vững;
  cần thiết kế lưu trữ phù hợp trước khi dựa vào chúng trên production.

## Cấu trúc chính

```text
app.py                         Khởi tạo Flask và đăng ký middleware
models.py                      SQLAlchemy models
database_config.py             Chọn database cho app và migration local
production_database_config.py  Kiểm tra target cho công cụ production
routes/                        Flask routes theo chức năng
services/                      Nghiệp vụ ứng dụng
templates/                     Jinja templates
static/                        CSS, JavaScript và ảnh demo
migrations/                    Alembic migrations của ứng dụng
migrations_production/         Alembic environment cho production
scripts/                       Snapshot và chuyển dữ liệu SQLite/PostgreSQL
tests/                         Unit và migration-safety tests
```

`rental.db`, `rental-before-postgresql.db`, `.env`, môi trường ảo, cache và file
upload cục bộ được loại khỏi Git theo `.gitignore`. Không xóa database hoặc ảnh
người dùng nếu chưa xác minh backup và tham chiếu.

## Kiểm thử

Các test nghiệp vụ và an toàn migration nằm trong `tests/`. Lưu ý:
`tests/test_cloudinary.py` thực hiện upload thật khi được import; không chạy
`unittest discover` khi chưa chủ ý kiểm thử Cloudinary và chấp nhận tạo asset
trên dịch vụ.
