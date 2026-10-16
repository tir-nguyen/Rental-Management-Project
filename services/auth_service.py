"""Nghiệp vụ tài khoản: đăng ký, đăng nhập, xác minh OTP + KYC."""
import re
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User
from services.upload_service import save_upload
from services import notification_service


class AuthError(Exception):
    """Lỗi nghiệp vụ auth, route sẽ bắt và hiển thị flash message."""


def find_by_email(school_email):
    return User.query.filter_by(school_email=school_email.strip().lower()).first()


def register_user(full_name, school_email, phone_number, password, district):
    full_name = full_name.strip()
    school_email = school_email.strip().lower()
    phone_number = phone_number.strip()

    if not all([full_name, school_email, phone_number, password]):
        raise AuthError("Vui lòng điền đầy đủ thông tin.")

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", school_email):
        raise AuthError("Vui lòng nhập địa chỉ email hợp lệ.")
    if len(password) < 6:
        raise AuthError("Mật khẩu cần có ít nhất 6 ký tự.")

    if find_by_email(school_email):
        raise AuthError("Email này đã được đăng ký.")
    if User.query.filter_by(phone_number=phone_number).first():
        raise AuthError("Số điện thoại này đã được đăng ký.")

    user = User(
        full_name=full_name,
        school_email=school_email,
        phone_number=phone_number,
        password_hash=generate_password_hash(password),
        district=district,
    )
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(school_email, password):
    user = find_by_email(school_email)
    if user and check_password_hash(user.password_hash, password):
        return user
    return None


def generate_otp():
    """(Demo) Mô phỏng gửi OTP — thực tế cần tích hợp SMS/email gateway."""
    return f"{secrets.randbelow(10000):04d}"


def confirm_otp(user, otp_input, expected_otp):
    if otp_input and otp_input == expected_otp:
        user.email_verified = True
        user.phone_verified = True
        db.session.commit()
        return True
    return False


def submit_kyc_card(user, upload_folder, card_file):
    if not card_file or not card_file.filename:
        return False
    url = save_upload(card_file, upload_folder)
    user.kyc_card_image = url
    user.kyc_status = "PENDING"
    for admin in User.query.filter_by(is_admin=True).all():
        notification_service.notify(admin.id, f"Có hồ sơ KYC mới cần duyệt: {user.full_name}.")
    db.session.commit()
    return True
