# SẵnThuê — Web cho thuê đồ giữa sinh viên (Hà Nội)

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
├── app.py                  # Khởi tạo Flask, middleware, schema và CLI commands
├── models.py                # SQLAlchemy models (theo ERD đã thiết kế)
├── routes/                  # HTTP handlers theo nhóm auth, listing, booking, admin
│   ├── auth_routes.py
│   ├── listing_routes.py
│   ├── booking_routes.py
│   └── admin_routes.py
├── services/                # Nghiệp vụ auth, listing, booking, review, admin, notification, seed
├── data/
│   └── seed_data.json        # Tài khoản và tin đăng dùng cho database demo
├── requirements.txt
├── rental.db                 # SQLite database (tự tạo sau khi init-db)
├── templates/
│   ├── base.html             # Khung chung: top bar + bottom nav
│   ├── index.html             # Khám phá / tìm kiếm / lọc
│   ├── listing_detail.html     # Chi tiết sản phẩm + form gửi yêu cầu thuê
│   ├── listing_form.html        # Đăng tin cho thuê
│   ├── my_listings.html          # Tin của tôi
│   ├── auth/
│   │   ├── register.html
│   │   ├── login.html
│   │   └── verify.html          # Xác minh OTP + upload thẻ SV (KYC)
│   ├── bookings/
│   │   ├── list.html              # Danh sách hợp đồng (tab Đi thuê / Cho thuê)
│   │   └── detail.html             # Trang trung tâm: trạng thái, hành động theo
│   │                                 từng bước (duyệt, cọc, bàn giao, trả đồ,
│   │                                 hoàn tất, tranh chấp), chat, đánh giá
│   └── admin/
│       └── dashboard.html          # Duyệt KYC + xử lý tranh chấp
└── static/
    ├── css/style.css          # Toàn bộ style mobile-first
    ├── js/app.js              # Tương tác dùng chung
    ├── demo/                   # Ảnh minh họa cho tin demo
    └── uploads/                 # Ảnh người dùng tải lên
```

## Đã triển khai theo đúng phân tích nghiệp vụ trước đó

- **Booking state machine đầy đủ**: PENDING → APPROVED/REJECTED/EXPIRED →
  DEPOSIT_WAITING → READY_FOR_PICKUP → IN_USE → RETURN_PENDING → COMPLETED,
  cộng DISPUTED và CANCELLED.
- **Escrow mô phỏng**: nút "Thanh Toán" demo luôn thành công (thay cho tích hợp
  VNPAY thật — xem phần "Việc cần làm thêm" bên dưới).
- **Handover có bằng chứng**: check-in/check-out yêu cầu 4-6 ảnh/video + ghi chú, xác nhận
  2 chiều mới chuyển trạng thái.
- **Reputation system**: điểm bắt đầu 100, +điểm khi hoàn tất/5 sao, -điểm khi
  1 sao hoặc vi phạm; dưới 70 điểm không thể gửi yêu cầu thuê; trên 120 điểm
  được giảm 50% tiền cọc.
- **Availability calendar**: khi đặt cọc thành công, hệ thống tự khóa ngày đó
  trên lịch của món đồ, không cho người khác đặt trùng.
- **Admin module**: duyệt KYC (xem ảnh thẻ SV), xử lý tranh chấp (hoàn 100% /
  trích cọc đền lender / chia đôi), tự động cập nhật trust score người vi phạm.
- **Giới hạn Hà Nội**: danh sách quận/huyện cố định dùng cho lọc & đăng tin.
- **Giao nhận trực tiếp**: không có logic vận chuyển — chỉ có ô ghi chú hẹn gặp
  và khung chat để 2 bên tự thỏa thuận địa điểm.

## Việc cần làm thêm trước khi triển khai thật (ngoài phạm vi đồ án demo)

1. Tích hợp cổng thanh toán VNPAY thật (hiện đang mô phỏng luôn thành công)
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
