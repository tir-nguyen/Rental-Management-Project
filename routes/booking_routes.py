"""Rental requests and booking lifecycle HTTP handlers."""

from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import Booking, PaymentAttempt
from services import booking_service, listing_service, review_service
from services.booking_service import BookingError

bookings_bp = Blueprint("bookings", __name__)


@login_required
def request_rental(listing_id):
    listing = listing_service.get_listing_or_404(listing_id)
    try:
        start_date = datetime.strptime(request.form.get("start_date", ""), "%Y-%m-%d").date()
        end_date = datetime.strptime(request.form.get("end_date", ""), "%Y-%m-%d").date()
        booking = booking_service.create_request(listing, current_user, start_date, end_date)
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("listings.listing_detail", listing_id=listing_id))
    except ValueError:
        flash("Vui lòng chọn ngày nhận và ngày trả hợp lệ.", "error")
        return redirect(url_for("listings.listing_detail", listing_id=listing_id))

    flash("Đã gửi yêu cầu thuê! Chờ người cho thuê phản hồi trong 24 giờ.", "success")
    return redirect(url_for("bookings.booking_detail", booking_id=booking.id))

@login_required
def booking_list():
    tab = request.args.get("tab", "thue")  # thue = renter, cho = lender
    if tab == "cho":
        bookings = Booking.query.filter_by(lender_id=current_user.id).order_by(Booking.created_at.desc()).all()
    else:
        bookings = Booking.query.filter_by(renter_id=current_user.id).order_by(Booking.created_at.desc()).all()
    return render_template("bookings/list.html", bookings=bookings, tab=tab)

@login_required
def booking_detail(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if current_user.id not in (booking.renter_id, booking.lender_id):
        abort(403)
    already_reviewed = review_service.already_reviewed(booking, current_user)
    latest_payment = PaymentAttempt.query.filter_by(booking_id=booking.id).order_by(
        PaymentAttempt.created_at.desc()
    ).first()
    return render_template(
        "bookings/detail.html", booking=booking,
        already_reviewed=already_reviewed, latest_payment=latest_payment,
    )

@login_required
def respond_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.respond(booking, current_user, request.form.get("decision"))
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    flash(
        "Đã chấp nhận yêu cầu. Người thuê cần thanh toán trong 2-4 giờ."
        if booking.status == "APPROVED" else "Đã từ chối yêu cầu.",
        "success" if booking.status == "APPROVED" else "info",
    )
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

@login_required
def checkin(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking, both_confirmed = booking_service.checkin(
            booking, current_user, request.form.get("note", ""),
            request.files.getlist("media"), current_app.config["UPLOAD_FOLDER"],
        )
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

    if both_confirmed:
        flash("Hai bên đã xác nhận bàn giao. Chúc bạn sử dụng đồ vui vẻ!", "success")
    else:
        flash("Đã ghi nhận xác nhận của bạn. Chờ bên còn lại xác nhận.", "info")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

@login_required
def checkout(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.checkout(
            booking, current_user, request.form.get("note", ""),
            request.files.getlist("media"), current_app.config["UPLOAD_FOLDER"],
        )
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    flash("Đã ghi nhận trả đồ. Chờ người cho thuê kiểm tra và xác nhận.", "info")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

@login_required
def complete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.complete(booking, current_user)
    except BookingError:
        abort(403)
    flash("Đơn hàng đã hoàn tất! Tiền thuê và tiền cọc đã được giải ngân.", "success")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.cancel(booking, current_user)
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    flash("Đơn hàng đã được hủy.", "info")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

@login_required
def open_dispute(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.open_dispute(booking, current_user, request.form.get("reason", ""))
    except BookingError:
        abort(403)
    flash("Đã mở tranh chấp. Admin sẽ xem xét và phản hồi sớm.", "info")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

@login_required
def send_message(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.send_message(booking, current_user, request.form.get("content", ""))
    except BookingError:
        abort(403)
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))

@login_required
def submit_review(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        review_service.submit_review(
            booking, current_user, request.form.get("rating", 5), request.form.get("comment", "")
        )
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("bookings.booking_detail", booking_id=booking_id))
    flash("Cảm ơn bạn đã đánh giá!", "success")
    return redirect(url_for("bookings.booking_detail", booking_id=booking_id))


bookings_bp.add_url_rule(
    "/san-pham/<int:listing_id>/thue", endpoint="request_rental",
    view_func=request_rental, methods=["POST"],
)
bookings_bp.add_url_rule("/don-hang", endpoint="booking_list", view_func=booking_list, methods=["GET"])
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>", endpoint="booking_detail",
    view_func=booking_detail, methods=["GET"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/phan-hoi", endpoint="respond_booking",
    view_func=respond_booking, methods=["POST"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/checkin", endpoint="checkin",
    view_func=checkin, methods=["POST"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/checkout", endpoint="checkout",
    view_func=checkout, methods=["POST"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/hoan-tat", endpoint="complete_booking",
    view_func=complete_booking, methods=["POST"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/huy", endpoint="cancel_booking",
    view_func=cancel_booking, methods=["POST"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/tranh-chap", endpoint="open_dispute",
    view_func=open_dispute, methods=["POST"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/chat", endpoint="send_message",
    view_func=send_message, methods=["POST"],
)
bookings_bp.add_url_rule(
    "/don-hang/<int:booking_id>/danh-gia", endpoint="submit_review",
    view_func=submit_review, methods=["POST"],
)
