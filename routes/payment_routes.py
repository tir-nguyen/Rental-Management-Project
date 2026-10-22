"""VNPay payment initiation and callback HTTP handlers."""
from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required

from models import Booking
from services import payment_service
from services.payment_service import PaymentConfigurationError, PaymentError

payments_bp = Blueprint("payments", __name__)


@payments_bp.post("/don-hang/<int:booking_id>/dat-coc")
@login_required
def pay_deposit(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        payment_url = payment_service.create_payment_url(
            booking,
            current_user,
            request.remote_addr or "127.0.0.1",
            current_app.config.get("VNPAY_RETURN_URL")
            or url_for("payments.vnpay_return", _external=True),
        )
    except (PaymentError, PaymentConfigurationError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    return redirect(payment_url)


@payments_bp.get("/thanh-toan/vnpay/return")
def vnpay_return():
    params = request.args.to_dict(flat=True)
    has_duplicates = any(len(request.args.getlist(key)) != 1 for key in request.args.keys())
    try:
        attempt = payment_service.confirm_verified_return(params, has_duplicates)
    except PaymentConfigurationError:
        current_app.logger.error("VNPay return received while payment credentials are not configured.")
        attempt = None

    if attempt is None:
        flash("Không xác minh được kết quả trả về từ VNPay.", "error")
        return redirect(url_for("bookings.booking_list"))

    if attempt.status == "SUCCESS":
        flash("VNPay đã xác nhận thanh toán thành công.", "success")
    elif attempt.status == "FAILED":
        flash("Giao dịch chưa thành công. Bạn có thể thử thanh toán lại.", "error")
    elif attempt.status == "PAID_REVIEW":
        flash("Đã nhận thanh toán nhưng đơn cần được kiểm tra thủ công. Vui lòng liên hệ hỗ trợ.", "error")
    else:
        flash("Đang chờ hệ thống xác nhận thanh toán từ VNPay. Vui lòng tải lại đơn sau ít phút.", "info")
    return redirect(url_for("bookings.booking_detail", booking_id=attempt.booking_id))


@payments_bp.get("/thanh-toan/vnpay/ipn")
def vnpay_ipn():
    params = request.args.to_dict(flat=True)
    has_duplicates = any(len(request.args.getlist(key)) != 1 for key in request.args.keys())
    try:
        response_code, message = payment_service.process_ipn(params, has_duplicates)
    except PaymentConfigurationError:
        current_app.logger.error("VNPay IPN received while payment credentials are not configured.")
        response_code, message = "99", "Payment configuration error"
    return jsonify(RspCode=response_code, Message=message)
