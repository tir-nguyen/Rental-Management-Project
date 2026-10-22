"""VNPay payment URL generation and signed callback processing."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

from flask import current_app
from sqlalchemy import update

from models import Booking, PaymentAttempt, Transaction, db
from services import notification_service

VNPAY_TIMEZONE = timezone(timedelta(hours=7))
PAYMENT_WINDOW = timedelta(minutes=15)


class PaymentError(ValueError):
    """Payment cannot be started for the current booking."""


class PaymentConfigurationError(RuntimeError):
    """Required VNPay configuration is missing or invalid."""


def _credentials():
    tmn_code = current_app.config.get("VNPAY_TMN_CODE", "")
    hash_secret = current_app.config.get("VNPAY_HASH_SECRET", "")
    payment_url = current_app.config.get("VNPAY_PAYMENT_URL", "")
    if not tmn_code or not hash_secret:
        raise PaymentConfigurationError(
            "VNPay sandbox chưa được cấu hình. Hãy điền VNPAY_TMN_CODE và "
            "VNPAY_HASH_SECRET trong file .env rồi khởi động lại ứng dụng."
        )
    if not payment_url.startswith("https://"):
        raise PaymentConfigurationError("VNPAY_PAYMENT_URL phải là URL HTTPS.")
    return tmn_code, hash_secret, payment_url


def _vnpay_timestamp(value):
    return value.replace(tzinfo=timezone.utc).astimezone(VNPAY_TIMEZONE).strftime("%Y%m%d%H%M%S")


def _signed_query(params, hash_secret):
    query = urlencode(sorted(params.items()))
    signature = sign_vnpay_params(params, hash_secret)
    return f"{query}&vnp_SecureHash={signature}"


def sign_vnpay_params(params, hash_secret):
    signed_params = {
        key: value for key, value in params.items()
        if key not in ("vnp_SecureHash", "vnp_SecureHashType")
    }
    query = urlencode(sorted(signed_params.items()))
    return hmac.new(
        hash_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha512
    ).hexdigest()


def _payment_url(booking, attempt, ip_address, return_url):
    tmn_code, hash_secret, payment_url = _credentials()
    params = {
        "vnp_Version": "2.1.0",
        "vnp_Command": "pay",
        "vnp_TmnCode": tmn_code,
        "vnp_Amount": str(attempt.amount * 100),
        "vnp_CurrCode": "VND",
        "vnp_TxnRef": attempt.txn_ref,
        "vnp_OrderInfo": f"Thanh toan don hang #{booking.id}",
        "vnp_OrderType": "other",
        "vnp_Locale": "vn",
        "vnp_ReturnUrl": return_url,
        "vnp_IpAddr": ip_address[:45],
        "vnp_CreateDate": _vnpay_timestamp(attempt.created_at),
        "vnp_ExpireDate": _vnpay_timestamp(attempt.expires_at),
    }
    return f"{payment_url}?{_signed_query(params, hash_secret)}"


def create_payment_url(booking, actor, ip_address, return_url):
    _credentials()
    if actor.id != booking.renter_id or booking.status not in ("APPROVED", "DEPOSIT_WAITING"):
        raise PaymentError("Đơn hàng hiện không thể thanh toán.")
    if PaymentAttempt.query.filter_by(booking_id=booking.id, status="SUCCESS").first():
        raise PaymentError("Đơn hàng này đã được thanh toán.")

    amount = booking.total_rent_amount + booking.deposit_amount
    if amount <= 0:
        raise PaymentError("Số tiền thanh toán phải lớn hơn 0.")

    now = datetime.utcnow()
    attempt = PaymentAttempt.query.filter_by(
        booking_id=booking.id, status="PENDING"
    ).order_by(PaymentAttempt.created_at.desc()).first()
    if attempt and attempt.expires_at > now:
        return _payment_url(booking, attempt, ip_address, return_url)
    if attempt:
        attempt.status = "EXPIRED"

    attempt = PaymentAttempt(
        booking_id=booking.id,
        txn_ref=uuid4().hex,
        amount=amount,
        status="PENDING",
        created_at=now,
        expires_at=now + PAYMENT_WINDOW,
    )
    db.session.add(attempt)
    db.session.commit()
    return _payment_url(booking, attempt, ip_address, return_url)


def _valid_signature(params, hash_secret):
    supplied_hash = params.get("vnp_SecureHash", "")
    expected_hash = sign_vnpay_params(params, hash_secret)
    return bool(supplied_hash) and hmac.compare_digest(
        supplied_hash.lower(), expected_hash.lower()
    )


def _get_verified_attempt(params, has_duplicates=False):
    tmn_code, hash_secret, _ = _credentials()
    if has_duplicates or not _valid_signature(params, hash_secret):
        return None
    if params.get("vnp_TmnCode") != tmn_code:
        return None
    attempt = PaymentAttempt.query.filter_by(txn_ref=params.get("vnp_TxnRef", "")).first()
    if attempt is None or params.get("vnp_Amount") != str(attempt.amount * 100):
        return None
    return attempt


def get_verified_return(params, has_duplicates=False):
    """Verify the browser return without using it to mutate payment state."""
    return _get_verified_attempt(params, has_duplicates)


def confirm_verified_return(params, has_duplicates=False):
    """Apply a signed sandbox return when local VNPay IPN is unavailable."""
    attempt = _get_verified_attempt(params, has_duplicates)
    if attempt is None:
        return None
    if not current_app.config.get("VNPAY_CONFIRM_ON_RETURN", False):
        return attempt

    _apply_verified_result(attempt, params)
    db.session.refresh(attempt)
    return attempt


def _apply_verified_result(attempt, params):
    if not params.get("vnp_ResponseCode") or not params.get("vnp_TransactionStatus"):
        return "04", "Invalid transaction status"
    if attempt.status not in ("PENDING", "EXPIRED"):
        return "02", "Order already confirmed"

    paid = (
        params.get("vnp_ResponseCode") == "00"
        and params.get("vnp_TransactionStatus") == "00"
    )
    now = datetime.utcnow()
    if not paid:
        result = db.session.execute(
            update(PaymentAttempt)
            .where(PaymentAttempt.id == attempt.id, PaymentAttempt.status == attempt.status)
            .values(status="FAILED", response_code=params.get("vnp_ResponseCode"))
        )
        if result.rowcount:
            db.session.commit()
        else:
            db.session.rollback()
        return "00", "Confirm Success"

    booking = db.session.get(Booking, attempt.booking_id)
    within_booking_window = (
        booking is not None
        and booking.status in ("APPROVED", "DEPOSIT_WAITING")
        and booking.approved_at is not None
        and booking.approved_at > now - timedelta(hours=4)
        and attempt.status == "PENDING"
    )
    final_status = "SUCCESS" if within_booking_window else "PAID_REVIEW"
    result = db.session.execute(
        update(PaymentAttempt)
        .where(
            PaymentAttempt.id == attempt.id,
            PaymentAttempt.status == attempt.status,
        )
        .values(
            status=final_status,
            response_code=params.get("vnp_ResponseCode"),
            transaction_no=params.get("vnp_TransactionNo"),
            paid_at=now,
        )
    )
    if not result.rowcount:
        db.session.rollback()
        return "02", "Order already confirmed"

    db.session.add(Transaction(
        booking_id=attempt.booking_id,
        type="VNPAY_PAYMENT",
        amount=attempt.amount,
        status="SUCCESS",
    ))
    if within_booking_window:
        booking.status = "READY_FOR_PICKUP"
        notification_service.notify(
            booking.lender_id, "VNPay đã xác nhận thanh toán; hãy hẹn giao nhận đồ.", booking.id
        )
    elif booking is not None:
        notification_service.notify_booking_parties(
            booking,
            "Đã nhận thanh toán VNPay nhưng đơn không còn trong thời hạn thanh toán; cần kiểm tra và hoàn tiền thủ công.",
        )
    db.session.commit()
    return "00", "Confirm Success"


def process_ipn(params, has_duplicates=False):
    """Apply a signed IPN once and return the VNPay acknowledgement."""
    if has_duplicates:
        return "97", "Invalid signature"

    tmn_code, hash_secret, _ = _credentials()
    if not _valid_signature(params, hash_secret) or params.get("vnp_TmnCode") != tmn_code:
        return "97", "Invalid signature"
    if not params.get("vnp_ResponseCode") or not params.get("vnp_TransactionStatus"):
        return "04", "Invalid transaction status"

    attempt = PaymentAttempt.query.filter_by(txn_ref=params.get("vnp_TxnRef", "")).first()
    if attempt is None:
        return "01", "Order not found"
    if params.get("vnp_Amount") != str(attempt.amount * 100):
        return "04", "Invalid amount"
    return _apply_verified_result(attempt, params)
