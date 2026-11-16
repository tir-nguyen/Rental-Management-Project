# Web cho thuê đồ giữa sinh viên (Hà Nội)

Flask + SQLAlchemy, dùng SQLite ở local và PostgreSQL khi có `DATABASE_URL`, mobile-first (responsive): mở link bằng trình duyệt điện thoại sẽ ra đúng
layout giống mockup app (bottom nav, card 1 cột...); mở trên máy tính thì layout vẫn hiển thị
gọn ở giữa màn hình.

## Cài đặt & chạy

```bash
# 1. Tạo virtual environment (khuyến nghị)
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 2. Cài thư viện
pip install -r requirements.txt

# 3. Chạy server với rental.db hiện có
python app.py
```

Mở trình duyệt tại: http://127.0.0.1:5000
Để xem đúng giao diện mobile, mở DevTools (F12) → Toggle device toolbar, hoặc mở bằng điện thoại
thật cùng mạng Wi-Fi (dùng IP máy tính, VD http://192.168.x.x:5000).

## Database và migration local

Khi không đặt `DATABASE_URL`, ứng dụng dùng `rental.db` ở thư mục dự án. Trên Render, ứng dụng
bắt buộc phải có `DATABASE_URL` PostgreSQL; nếu thiếu hoặc trỏ đến SQLite, ứng dụng dừng với lỗi
rõ ràng thay vì tạo database SQLite mới. Đặt biến này trong phần Environment của Web Service bằng
Internal Database URL do Render cung cấp. Render đánh dấu môi trường bằng `RENDER=true`.
Không đưa URL có thông tin xác thực vào source code.

Ứng dụng không tự tạo hoặc sửa schema khi khởi động/request. Khi chạy local với DB hiện có, chỉ
khởi động ứng dụng như bình thường; đừng chạy `flask db stamp` hoặc `flask db upgrade` lên
`rental.db`.

Để tránh nhầm SQLite local khi thao tác Alembic, mọi lệnh `flask db ...` chỉ chấp nhận
`RENTAL_TEST_DATABASE_URL` trỏ đến PostgreSQL local `localhost:5432/rental_test`. Các lệnh này
không dùng `DATABASE_URL` và không fallback sang `rental.db`; các cấu hình SQLite, host/port khác
hoặc database `postgres` đều bị từ chối. Engine migration chỉ được tạo sau khi URL qua kiểm tra.
Không tự động chạy migration khi ứng dụng Flask khởi động.

### Kiểm thử chuyển dữ liệu (chỉ môi trường local)

1. Dùng PostgreSQL thử nghiệm local `localhost:5432/rental_test`, cấu hình
   `RENTAL_TEST_DATABASE_URL`, và tạo một bản sao SQLite thử nghiệm riêng.
2. `flask --app app.py db upgrade` chỉ sử dụng biến `RENTAL_TEST_DATABASE_URL`; lệnh từ chối
   SQLite, host/port khác và database `postgres`. Không dùng `DATABASE_URL` và không fallback
   sang `rental.db`.
3. Đặt `RENTAL_SQLITE_SOURCE` thành đường dẫn bản sao SQLite riêng. Script từ chối
   `rental.db` và `rental-before-postgresql.db`, không tự chọn nguồn. Nó xác nhận schema 13 bảng,
   khóa ngoại, revision `f5d032bff585` và đích trống trước khi nhập trong một transaction.
   Sequence chỉ được reset/kiểm tra sau khi dữ liệu đã commit.
4. Chỉ sau khi được phê duyệt mới chạy `python scripts/migrate_sqlite_to_postgres.py` hoặc
   `python scripts/migrate_sqlite_to_postgres.py --repair-sequences`. Nếu nhập lỗi, dữ liệu
   rollback. Nếu reset sequence lỗi sau commit, dữ liệu vẫn được giữ nguyên; không chạy lại lệnh
   import. Sửa nguyên nhân rồi chạy `--repair-sequences`, chế độ chỉ đặt lại và xác minh sequence.
   PostgreSQL `setval()` không rollback; có thể chạy lại chế độ sửa nếu lần trước dừng giữa chừng.

Các lệnh và script này hiện bị khóa vào PostgreSQL local thử nghiệm; chúng không phải quy trình
migration production. Cần thiết kế và rà soát riêng một đường chạy production trước khi chuyển
dữ liệu hoặc chạy migration trên Render.

## Chuẩn bị migration production trên Render

Các lệnh production là công cụ độc lập, không phải lệnh `flask db`; chúng chỉ đọc
`RENTAL_PRODUCTION_DATABASE_URL` và không fallback sang `DATABASE_URL`, `rental.db` hay
`rental-before-postgresql.db`. Không đưa URL, password, snapshot hoặc manifest có dữ liệu nhạy cảm
vào mã nguồn, README, command history hay GitHub.

### Phương thức kết nối được chọn

Phương án được khuyến nghị cho dự án này là chạy runner từ máy tính cá nhân đã được kiểm soát,
dùng **External Database URL** của Render. Runner chỉ chấp nhận `sslmode=require` hoặc
`sslmode=verify-full`, không chấp nhận tắt TLS. Render hướng dẫn dùng `require` để bắt buộc mã hóa
kết nối external. `verify-full` mạnh hơn: ngoài mã hóa, xác minh CA và hostname của máy chủ;
`require` chỉ bắt buộc mã hóa, không bảo đảm xác minh danh tính hostname. Ưu tiên `verify-full` nếu
certificate chain được máy local tin cậy; nếu URL External của Render dùng `require`, vẫn giữ TLS
bắt buộc và chỉ tiếp tục sau khi preflight xác nhận đúng target. Không ghi URL có credential vào
command history, source code hoặc log.

Chạy từ **Render Internal Database URL** sẽ giảm phụ thuộc vào endpoint công khai và phù hợp khi
runner ở cùng private network. Nhưng snapshot SQLite phải được chuyển an toàn vào runner (ví dụ
private encrypted object storage hoặc một job có storage phù hợp); filesystem Render Free là tạm
thời. Điều này tạo thêm bản sao nhạy cảm và bước quản lý/xóa. Có thể chọn phương án này nếu có
runner/disk riêng và quy trình staging/xóa được kiểm thử; hiện chưa triển khai.

### Các bước — chưa chạy

1. Đóng băng thao tác ghi website. Tạo backup PostgreSQL/Render và xác nhận khả năng restore
   sang database mới riêng. Không dùng thao tác restore ghi đè database đang chạy.
2. Tạo bản SQLite snapshot ở đường dẫn bảo mật ngoài Git từ nguồn chính thức `rental.db`.
   `scripts/create_sqlite_snapshot.py` đọc nguồn ở chế độ chỉ đọc, yêu cầu xác nhận tên nguồn,
   tạo file mới (không overwrite) và kiểm tra schema/FK. Không dùng file backup thay nguồn.
3. Đưa credential External URL vào biến tiến trình tạm `RENTAL_PRODUCTION_DATABASE_URL`; đặt
   `RENTAL_PRODUCTION_EXPECTED_HOST`, `RENTAL_PRODUCTION_EXPECTED_DATABASE`,
   `RENTAL_PRODUCTION_EXPECTED_PORT` đúng theo Render, và
   `RENTAL_PRODUCTION_SQLITE_SOURCE` trỏ đến snapshot. Không ghi các giá trị này vào file được
   commit. Production tool từ chối loopback, `DATABASE_URL`, SQLite, database tên `postgres`,
   host/port không khớp, TLS không phải `verify-full`, sai schema và thiếu xác nhận.
4. Chạy `python scripts/render_schema_migrate.py --plan`. Chỉ khi identity đúng và schema
   production hoàn toàn trống, schema migration mới được xét. Tạo schema là thao tác ghi riêng;
   chỉ thực hiện sau khi người vận hành đã kiểm tra backup rồi xác nhận bằng
   `--apply --confirm-target "<hostname>/<database>"`. Migration chỉ tạo revision
   `f5d032bff585` lên `public` trống.
5. Chạy `python scripts/migrate_sqlite_to_render.py --plan`. Xem target, revision, row counts và
   checksum theo bảng. Dừng nếu bất kỳ bảng nào đã có hàng hoặc nếu schema/revision khác kỳ vọng.
6. Chỉ sau một xác nhận riêng cho nhập dữ liệu mới chạy
   `python scripts/migrate_sqlite_to_render.py --apply --confirm-target "<hostname>/<database>" --confirm-import "IMPORT <hostname>/<database>"`.
   Import dùng transaction, khóa bảng, giữ ID/password hash/timestamp, so sánh count và checksum,
   rồi reset/verify sequence. Nếu import đã commit nhưng reset sequence lỗi, không chạy lại import;
   giữ maintenance mode và dùng `--repair-sequences` cùng `--confirm-target` và
   `--confirm-repair "REPAIR SEQUENCES <hostname>/<database>"`.
7. So sánh manifest/count từng bảng, FK, checksum, revision và sequence; kiểm tra ứng dụng/ảnh
   trên target; chỉ sau khi mọi xác minh đạt mới mở lại ghi. Giữ snapshot và backup cho tới khi
   xác nhận khôi phục/cutover hoàn tất.

Target có dữ liệu, revision không đúng, object/table lạ, hoặc manifest mismatch là điều kiện dừng:
không tự xóa, stamp, upsert hay retry import. Các lệnh `--apply` có hai xác nhận riêng, nhưng
người vận hành vẫn phải tự kiểm tra đúng target và backup trước khi nhập.

## Ảnh tải lên trên Render

Ảnh bài đăng công khai vẫn nằm trong `static/uploads/`. KYC và `handover_evidences` mới được ghi
ngoài static vào `instance/private_uploads/`; database tiếp tục lưu logical key
`uploads/<uuid>.<ext>`. KYC chỉ được đọc bởi Admin; evidence chỉ bởi Admin hoặc người thuê/chủ tin
của booking. URL static chỉ được phép phục vụ file đang được `ListingImage` tham chiếu, nên file
private cũ hoặc mồ côi không được phục vụ qua Flask static. Các file cũ không bị di chuyển hay
xóa; handler private có thể đọc chúng sau khi xác thực quyền.

Filesystem của Web Service Render Free là tạm thời, nên cả upload công khai và private trên
filesystem có thể mất khi deploy/restart. Chưa tích hợp object storage; cần triển khai R2 private
ACL/serving và kiểm thử quyền trước khi mở upload production. Inventory trước đây có 23 file và
khoảng 47 tham chiếu; cần tái lập manifest từ snapshot trong giai đoạn migration, lưu SHA-256/kích
thước, xác nhận đủ mọi tham chiếu và không xóa nguồn cho tới khi đối chiếu/khôi phục thử nghiệm
hoàn tất.

## Cấu trúc project

```
rentalweb/
├── .gitignore                 # Bỏ qua môi trường, cache, database và file upload cục bộ
├── .env.example               # Mẫu biến môi trường; không chứa thông tin thật
├── app.py                     # Khởi tạo Flask, middleware và CLI commands
├── database_config.py         # Chọn/chuẩn hóa SQLite hoặc PostgreSQL URL
├── migrations/                # Schema migrations Flask-Migrate/Alembic
├── migrations_production/     # Alembic environment production tách khỏi local guard
├── scripts/
│   ├── create_sqlite_snapshot.py       # Tạo snapshot SQLite riêng, chỉ đọc nguồn
│   ├── render_schema_migrate.py        # Preflight/tạo schema production có xác nhận
│   ├── migrate_sqlite_to_render.py     # Import snapshot có xác nhận và kiểm tra
│   └── migrate_sqlite_to_postgres.py   # Import thử nghiệm PostgreSQL local
├── models.py                  # SQLAlchemy models (theo ERD đã thiết kế)
├── ptnv.pdf                   # Tài liệu PDF của dự án
├── routes/                    # Flask Blueprints, chia theo nhóm chức năng
│   ├── __init__.py
│   ├── auth_routes.py         # Blueprint auth
│   ├── listing_routes.py      # Blueprint listings
│   ├── booking_routes.py      # Blueprint bookings
│   ├── admin_routes.py        # Blueprint admin
│   ├── payment_routes.py      # Blueprint payments: tạo yêu cầu, Return, IPN VNPay
│   └── profile_routes.py      # Hồ sơ riêng và hồ sơ công khai người dùng
├── services/                  # Xử lý nghiệp vụ, tách khỏi HTTP handlers
│   ├── __init__.py
│   ├── admin_service.py
│   ├── auth_service.py
│   ├── booking_service.py
│   ├── listing_service.py
│   ├── notification_service.py
│   ├── payment_service.py     # Tạo URL VNPay và xác minh Return/IPN
│   ├── profile_service.py     # Cập nhật hồ sơ và truy vấn dữ liệu công khai
│   ├── review_service.py
│   └── upload_service.py
├── requirements.txt
├── templates/
│   ├── base.html              # Khung chung: top bar + bottom nav
│   ├── index.html             # Khám phá / tìm kiếm / lọc
│   ├── listing_detail.html    # Chi tiết sản phẩm + form gửi yêu cầu thuê
│   ├── listing_form.html      # Đăng và chỉnh sửa tin cho thuê
│   ├── my_listings.html       # Tin của tôi, trạng thái và lịch bận
│   ├── notifications.html     # Danh sách thông báo
│   ├── profiles/
│   │   ├── my_profile.html    # Hồ sơ riêng, chỉ chủ tài khoản chỉnh sửa
│   │   └── public_profile.html # Thông tin công khai và tin đang cho thuê
│   ├── auth/
│   │   ├── register.html
│   │   ├── login.html
│   │   └── verify.html        # Xác minh OTP + upload thẻ SV (KYC)
│   ├── bookings/
│   │   ├── list.html          # Danh sách hợp đồng (tab Đi thuê / Cho thuê)
│   │   └── detail.html        # Trạng thái, hành động, chat và đánh giá
│   └── admin/
│       └── dashboard.html     # Duyệt KYC + xử lý tranh chấp
└── static/
    ├── css/style.css           # Giao diện responsive desktop-first
    ├── demo/                   # Ảnh minh họa cho tin demo
    ├── js/app.js               # Tương tác dùng chung
    └── uploads/                # File người dùng tải lên; không đưa lên Git
```

Database `rental.db` và các bản sao lưu SQLite ở thư mục gốc không được theo dõi bởi Git.
Thư mục `static/uploads/` cũng được tạo khi cần lưu file tải lên; các file bên trong không được
đưa lên Git.

## Đã triển khai theo đúng phân tích nghiệp vụ trước đó

- **Booking state machine đầy đủ**: PENDING → APPROVED/REJECTED/EXPIRED →
  DEPOSIT_WAITING → READY_FOR_PICKUP → IN_USE → RETURN_PENDING → COMPLETED,
  cộng DISPUTED và CANCELLED.
- **Thanh toán VNPay sandbox**: thanh toán tiền thuê + tiền cọc qua VNPay;
  khi chạy sandbox local, Return có chữ ký hợp lệ cũng xác nhận được đơn vì
  VNPay không thể gửi IPN trực tiếp tới `localhost`.
- **Handover có bằng chứng**: check-in/check-out yêu cầu 4-6 ảnh/video + ghi chú, xác nhận
  2 chiều mới chuyển trạng thái.
- **Reputation system**: điểm bắt đầu 100, +điểm khi hoàn tất/5 sao, -điểm khi
  1 sao hoặc vi phạm; dưới 70 điểm không thể gửi yêu cầu thuê; trên 120 điểm
  được giảm 50% tiền cọc.
- **Availability calendar**: khi đặt cọc thành công, hệ thống tự khóa ngày đó
  trên lịch của món đồ, không cho người khác đặt trùng.
- **Chỉnh sửa tin đăng**: chủ tin có thể cập nhật thông tin và thêm ảnh tại
  `/san-pham/<id>/sua`; khi chọn ảnh mới, ảnh cũ được thay thế, còn khi không
  chọn ảnh thì ảnh hiện tại được giữ nguyên. Tin có đơn thuê chưa hoàn tất
  tạm thời không thể chỉnh sửa để tránh ảnh hưởng giao dịch đang diễn ra.
- **Admin module**: duyệt KYC (xem ảnh thẻ SV), xử lý tranh chấp (hoàn 100% /
  trích cọc đền lender / chia đôi), tự động cập nhật trust score người vi phạm.
- **Hồ sơ người dùng**: `/ho-so` cho chủ tài khoản cập nhật tên/khu vực;
  `/nguoi-dung/<id>` chỉ hiển thị tên, ngày tham gia, trạng thái xác minh,
  thống kê đánh giá/giao dịch và tin đang công khai. Email, điện thoại, ảnh KYC
  và khu vực cá nhân không xuất hiện trên hồ sơ công khai. Email/số điện thoại
  hiện chưa cho sửa vì ứng dụng chưa có luồng xác minh lại an toàn.
- **Giới hạn Hà Nội**: danh sách quận/huyện cố định dùng cho lọc & đăng tin.
- **Giao nhận trực tiếp**: không có logic vận chuyển — chỉ có ô ghi chú hẹn gặp
  và khung chat để 2 bên tự thỏa thuận địa điểm.

## Cấu hình VNPay sandbox khi chạy local

Tạo file `.env` ở thư mục gốc dự án bằng cách sao chép mẫu:

```powershell
Copy-Item .env.example .env
```

Mở `.env` và tự điền `VNPAY_TMN_CODE` cùng `VNPAY_HASH_SECRET` do VNPay cấp.
Không gửi các giá trị này trong chat, không đưa vào mã nguồn và không commit
`.env`; file đã được loại trừ trong `.gitignore`. Ứng dụng nạp file `.env` lúc
khởi động, trước khi đọc cấu hình. Có thể đặt `VNPAY_PAYMENT_URL` và
`VNPAY_RETURN_URL` như biến môi trường riêng nếu cần ghi đè giá trị mặc định/
URL Return.

Để nhận kết quả quay về/IPN thực tế, VNPay cần truy cập được URL công khai. Chạy
một HTTPS tunnel trỏ tới cổng 5000, sau đó cấu hình:

```powershell
$env:VNPAY_RETURN_URL = "https://<host-cong-khai>/thanh-toan/vnpay/return"
```

Đăng ký IPN URL `https://<host-cong-khai>/thanh-toan/vnpay/ipn` trong cấu hình
merchant sandbox của VNPay. Với URL sandbox mặc định, Return có chữ ký hợp lệ
sẽ cập nhật trạng thái để hỗ trợ chạy local không có tunnel/IPN. Khi triển khai
công khai, đặt `VNPAY_CONFIRM_ON_RETURN=0` và chỉ dùng IPN đã xác thực để xác
nhận thanh toán. Tùy chọn này mặc định bật riêng cho host `sandbox.vnpayment.vn`
và tắt khi URL thanh toán không phải host sandbox đó.
Nếu tiền về sau khi đơn đã bị hủy/hết hạn, giao dịch được đánh dấu cần kiểm tra;
ứng dụng hiện chưa tự động gọi API hoàn tiền.

Khởi động app trong cùng PowerShell để các biến môi trường được áp dụng:

```powershell
.venv\Scripts\python.exe app.py
```

## Việc cần làm thêm trước khi triển khai thật

1. Hoàn tất kiểm thử sandbox, sau đó đăng ký và cấu hình bộ thông tin VNPay production riêng.
2. Gửi OTP/email thật (hiện đang hiển thị mã ngay trên giao diện demo)
3. Ràng buộc email theo domain chính xác của từng trường (hiện chỉ kiểm tra đuôi `.edu.vn`)
4. Lên lịch chạy `flask --app app.py expire-bookings` định kỳ bằng Windows Task Scheduler/cron;
   quá hạn cũng được quét khi có truy cập vào trang tin/đơn thuê
5. Thêm xác thực nội dung file upload (hiện giới hạn dung lượng request và kiểm tra phần mở rộng)
6. Đặt biến môi trường `SECRET_KEY` cố định khi chạy nhiều worker hoặc triển khai thật
