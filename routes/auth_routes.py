"""Authentication and student verification HTTP handlers."""

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import DISTRICTS
from services import auth_service
from services.auth_service import AuthError

def register():
    if request.method == "POST":
        try:
            user = auth_service.register_user(
                full_name=request.form.get("full_name", ""),
                school_email=request.form.get("school_email", ""),
                phone_number=request.form.get("phone_number", ""),
                password=request.form.get("password", ""),
                district=request.form.get("district"),
            )
        except AuthError as e:
            flash(str(e), "error")
            return render_template("auth/register.html", districts=DISTRICTS)

        login_user(user)
        otp = auth_service.generate_otp()
        session["pending_otp"] = otp
        flash(f"(Demo) Mã OTP của bạn là {otp}", "info")
        return redirect(url_for("verify_account"))

    return render_template("auth/register.html", districts=DISTRICTS)

@login_required
def verify_account():
    if request.method == "POST":
        otp_input = request.form.get("otp", "")
        card_file = request.files.get("kyc_card")

        if auth_service.confirm_otp(current_user, otp_input, session.get("pending_otp")):
            session.pop("pending_otp", None)
            flash("Xác minh email & SĐT thành công!", "success")
        elif otp_input:
            flash("Mã OTP không đúng.", "error")

        try:
            if auth_service.submit_kyc_card(current_user, current_app.config["UPLOAD_FOLDER"], card_file):
                flash("Đã gửi ảnh thẻ sinh viên, chờ Admin duyệt.", "info")
        except (ValueError, AuthError) as e:
            flash(str(e), "error")

        if current_user.is_verified:
            return redirect(url_for("index"))

    return render_template("auth/verify.html")

def login():
    if request.method == "POST":
        user = auth_service.authenticate(
            request.form.get("school_email", ""), request.form.get("password", "")
        )
        if user:
            login_user(user)
            return redirect(url_for("index"))
        flash("Email hoặc mật khẩu không đúng.", "error")
    return render_template("auth/login.html")

def logout():
    logout_user()
    return redirect(url_for("index"))


def register_routes(app):
    route_definitions = [
        ("/dang-ky", "register", register, ["GET", "POST"]),
        ("/xac-minh", "verify_account", verify_account, ["GET", "POST"]),
        ("/dang-nhap", "login", login, ["GET", "POST"]),
        ("/dang-xuat", "logout", logout, ["POST"]),
    ]
    for rule, endpoint, view, methods in route_definitions:
        app.add_url_rule(rule, endpoint=endpoint, view_func=view, methods=methods)
