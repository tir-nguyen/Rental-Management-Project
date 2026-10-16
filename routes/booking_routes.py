"""Rental requests and booking lifecycle HTTP handlers."""

from datetime import datetime

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import Booking
from services import booking_service, listing_service, review_service
from services.booking_service import BookingError

@login_required
def request_rental(listing_id):
    listing = listing_service.get_listing_or_404(listing_id)
    try:
        start_date = datetime.strptime(request.form.get("start_date", ""), "%Y-%m-%d").date()
        end_date = datetime.strptime(request.form.get("end_date", ""), "%Y-%m-%d").date()
        booking = booking_service.create_request(listing, current_user, start_date, end_date)
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))
    except ValueError:
        flash("Vui lòng chọn ngày nhận và ngày trả hợp lệ.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))

    flash("Đã gửi yêu cầu thuê! Chờ người cho thuê phản hồi trong 24 giờ.", "success")
    return redirect(url_for("booking_detail", booking_id=booking.id))

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
    return render_template("bookings/detail.html", booking=booking, already_reviewed=already_reviewed)

@login_required
def respond_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.respond(booking, current_user, request.form.get("decision"))
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("booking_detail", booking_id=booking_id))
    flash(
        "Đã chấp nhận yêu cầu. Người thuê cần thanh toán trong 2-4 giờ."
        if booking.status == "APPROVED" else "Đã từ chối yêu cầu.",
        "success" if booking.status == "APPROVED" else "info",
    )
    return redirect(url_for("booking_detail", booking_id=booking_id))

@login_required
def pay_deposit(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.pay_deposit(booking, current_user)
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("booking_detail", booking_id=booking_id))
    flash("Thanh toán thành công! Hẹn gặp để nhận đồ.", "success")
    return redirect(url_for("booking_detail", booking_id=booking_id))

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
        return redirect(url_for("booking_detail", booking_id=booking_id))

    if both_confirmed:
        flash("Hai bên đã xác nhận bàn giao. Chúc bạn sử dụng đồ vui vẻ!", "success")
    else:
        flash("Đã ghi nhận xác nhận của bạn. Chờ bên còn lại xác nhận.", "info")
    return redirect(url_for("booking_detail", booking_id=booking_id))

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
        return redirect(url_for("booking_detail", booking_id=booking_id))
    flash("Đã ghi nhận trả đồ. Chờ người cho thuê kiểm tra và xác nhận.", "info")
    return redirect(url_for("booking_detail", booking_id=booking_id))

@login_required
def complete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.complete(booking, current_user)
    except BookingError:
        abort(403)
    flash("Đơn hàng đã hoàn tất! Tiền thuê và tiền cọc đã được giải ngân.", "success")
    return redirect(url_for("booking_detail", booking_id=booking_id))

@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.cancel(booking, current_user)
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("booking_detail", booking_id=booking_id))
    flash("Đơn hàng đã được hủy.", "info")
    return redirect(url_for("booking_detail", booking_id=booking_id))

@login_required
def open_dispute(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.open_dispute(booking, current_user, request.form.get("reason", ""))
    except BookingError:
        abort(403)
    flash("Đã mở tranh chấp. Admin sẽ xem xét và phản hồi sớm.", "info")
    return redirect(url_for("booking_detail", booking_id=booking_id))

@login_required
def send_message(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        booking_service.send_message(booking, current_user, request.form.get("content", ""))
    except BookingError:
        abort(403)
    return redirect(url_for("booking_detail", booking_id=booking_id))

@login_required
def submit_review(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        review_service.submit_review(
            booking, current_user, request.form.get("rating", 5), request.form.get("comment", "")
        )
    except BookingError as e:
        flash(str(e), "error")
        return redirect(url_for("booking_detail", booking_id=booking_id))
    flash("Cảm ơn bạn đã đánh giá!", "success")
    return redirect(url_for("booking_detail", booking_id=booking_id))


def register_routes(app):
    route_definitions = [
        ("/san-pham/<int:listing_id>/thue", "request_rental", request_rental, ["POST"]),
        ("/don-hang", "booking_list", booking_list, ["GET"]),
        ("/don-hang/<int:booking_id>", "booking_detail", booking_detail, ["GET"]),
        ("/don-hang/<int:booking_id>/phan-hoi", "respond_booking", respond_booking, ["POST"]),
        ("/don-hang/<int:booking_id>/dat-coc", "pay_deposit", pay_deposit, ["POST"]),
        ("/don-hang/<int:booking_id>/checkin", "checkin", checkin, ["POST"]),
        ("/don-hang/<int:booking_id>/checkout", "checkout", checkout, ["POST"]),
        ("/don-hang/<int:booking_id>/hoan-tat", "complete_booking", complete_booking, ["POST"]),
        ("/don-hang/<int:booking_id>/huy", "cancel_booking", cancel_booking, ["POST"]),
        ("/don-hang/<int:booking_id>/tranh-chap", "open_dispute", open_dispute, ["POST"]),
        ("/don-hang/<int:booking_id>/chat", "send_message", send_message, ["POST"]),
        ("/don-hang/<int:booking_id>/danh-gia", "submit_review", submit_review, ["POST"]),
    ]
    for rule, endpoint, view, methods in route_definitions:
        app.add_url_rule(rule, endpoint=endpoint, view_func=view, methods=methods)
