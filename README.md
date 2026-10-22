# Web cho thuê đồ giữa sinh viên (Hà Nội)

Flask + SQLite, mobile-first (responsive): mở link bằng trình duyệt điện thoại sẽ ra đúng
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

# 3. Khởi tạo & tạo dữ liệu mẫu (chỉ cần chạy 1 lần)
flask --app app.py init-db
flask --app app.py seed

# 4. Chạy server
python app.py
```

Mở trình duyệt tại: http://127.0.0.1:5000
Để xem đúng giao diện mobile, mở DevTools (F12) → Toggle device toolbar, hoặc mở bằng điện thoại
thật cùng mạng Wi-Fi (dùng IP máy tính, VD http://192.168.x.x:5000).

## Tài khoản demo (sau khi chạy `flask seed`)

| Vai trò | Email | Mật khẩu |
|---|---|---|
| Admin | admin@neu.edu.vn | admin123 |
| Sinh viên (có sẵn 1 tin đăng máy ảnh) | thao.vy@neu.edu.vn | 123456 |
| Sinh viên (dùng để thử thuê đồ) | nam.hai@neu.edu.vn | 123456 |

## Cấu trúc project

```
rentalweb/
├── .gitignore                 # Bỏ qua môi trường, cache, database và file upload cục bộ
├── .env.example               # Mẫu tên biến VNPay; không chứa thông tin thật
├── app.py                     # Khởi tạo Flask, middleware, schema và CLI commands
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
│   ├── seed_service.py
│   └── upload_service.py
├── data/
│   └── seed_data.json         # Tài khoản và tin đăng dùng cho database demo
├── requirements.txt
├── templates/
│   ├── base.html              # Khung chung: top bar + bottom nav
│   ├── index.html             # Khám phá / tìm kiếm / lọc
│   ├── listing_detail.html    # Chi tiết sản phẩm + form gửi yêu cầu thuê
│   ├── listing_form.html      # Đăng tin cho thuê
│   ├── my_listings.html       # Tin của tôi
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

Database `rental.db` được tạo cục bộ khi chạy `init-db` và không được theo dõi
bởi Git. Thư mục `static/uploads/` cũng được tạo khi cần lưu file tải lên; các
file bên trong không được đưa lên Git.

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
# Thêm dữ liệu trình diễn

Để bổ sung tài khoản người cho thuê và 28 tin đăng mẫu vào database hiện tại, chạy:

```powershell
.venv\Scripts\python.exe -m flask --app app.py seed-demo-data
```

Lệnh có thể chạy nhiều lần; tin đã tồn tại sẽ được giữ nguyên và không bị tạo trùng. Các tài khoản demo mới dùng mật khẩu `123456`.
