"""Marketplace, listing management, and notification HTTP handlers."""

from datetime import date, datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import AvailabilityBlock, CATEGORIES, DISTRICTS, Notification
from services import listing_service, notification_service

listings_bp = Blueprint("listings", __name__)


def index():
    q = request.args.get("q", "").strip()
    district = request.args.get("district", "")
    category = request.args.get("category", "")

    try:
        min_price = int(request.args["min_price"]) if request.args.get("min_price") else None
        max_price = int(request.args["max_price"]) if request.args.get("max_price") else None
        if (min_price is not None and min_price < 0) or (max_price is not None and max_price < 0):
            raise ValueError
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValueError
    except ValueError:
        flash("Khoảng giá không hợp lệ.", "error")
        min_price = max_price = None
    try:
        available_from = (datetime.strptime(request.args["available_from"], "%Y-%m-%d").date()
                          if request.args.get("available_from") else None)
        available_to = (datetime.strptime(request.args["available_to"], "%Y-%m-%d").date()
                        if request.args.get("available_to") else None)
        if bool(available_from) != bool(available_to) or (available_from and available_to <= available_from):
            raise ValueError
    except ValueError:
        flash("Khoảng ngày tìm đồ còn trống không hợp lệ.", "error")
        available_from = available_to = None
    listings = listing_service.search_listings(
        q, district, category, min_price, max_price, available_from, available_to
    )
    return render_template(
        "index.html", listings=listings, districts=DISTRICTS, categories=CATEGORIES,
        q=q, selected_district=district, selected_category=category,
        min_price=min_price, max_price=max_price,
        available_from=available_from, available_to=available_to,
    )

def listing_detail(listing_id):
    listing = listing_service.get_listing_or_404(listing_id)
    if listing.status == "HIDDEN" and (
        not current_user.is_authenticated or current_user.id != listing.owner_id
    ):
        abort(404)
    return render_template("listing_detail.html", listing=listing, today=date.today())

@login_required
def create_listing():
    if not current_user.is_verified:
        flash("Bạn cần xác minh tài khoản trước khi đăng tin.", "error")
        return redirect(url_for("auth.verify_account"))

    if request.method == "POST":
        try:
            listing = listing_service.create_listing(
                current_user.id, request.form, request.files, current_app.config["UPLOAD_FOLDER"]
            )
        except listing_service.ListingError as e:
            flash(str(e), "error")
            return render_template("listing_form.html", districts=DISTRICTS, categories=CATEGORIES)
        flash("Đăng tin thành công!", "success")
        return redirect(url_for("listings.listing_detail", listing_id=listing.id))

    return render_template("listing_form.html", districts=DISTRICTS, categories=CATEGORIES)

@login_required
def my_listings():
    listings = listing_service.list_owned(current_user.id)
    return render_template("my_listings.html", listings=listings)

@login_required
def notifications():
    return render_template("notifications.html", notifications=notification_service.list_for_user(current_user.id))

@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if not notification_service.mark_read(notification, current_user.id):
        abort(403)
    if notification.booking_id:
        return redirect(url_for("bookings.booking_detail", booking_id=notification.booking_id))
    return redirect(url_for("listings.notifications"))

@login_required
def block_listing_dates(listing_id):
    listing = listing_service.get_listing_or_404(listing_id)
    try:
        start = datetime.strptime(request.form.get("start_date", ""), "%Y-%m-%d").date()
        end = datetime.strptime(request.form.get("end_date", ""), "%Y-%m-%d").date()
        listing_service.block_dates(listing, current_user.id, start, end)
    except (ValueError, listing_service.ListingError) as e:
        flash(str(e) or "Vui lòng chọn ngày hợp lệ.", "error")
        return redirect(url_for("listings.my_listings"))
    flash("Đã khóa ngày trong lịch của món đồ.", "success")
    return redirect(url_for("listings.my_listings"))

@login_required
def toggle_listing_visibility(listing_id):
    listing = listing_service.get_listing_or_404(listing_id)
    try:
        listing_service.toggle_visibility(listing, current_user.id)
    except listing_service.ListingError as e:
        flash(str(e), "error")
    return redirect(url_for("listings.my_listings"))

@login_required
def remove_listing_block(block_id):
    block = AvailabilityBlock.query.get_or_404(block_id)
    try:
        listing_service.remove_owner_block(block, current_user.id)
    except listing_service.ListingError as e:
        flash(str(e), "error")
    return redirect(url_for("listings.my_listings"))


listings_bp.add_url_rule("/", endpoint="index", view_func=index, methods=["GET"])
listings_bp.add_url_rule("/san-pham/<int:listing_id>", endpoint="listing_detail", view_func=listing_detail, methods=["GET"])
listings_bp.add_url_rule("/dang-tin", endpoint="create_listing", view_func=create_listing, methods=["GET", "POST"])
listings_bp.add_url_rule("/tin-cua-toi", endpoint="my_listings", view_func=my_listings, methods=["GET"])
listings_bp.add_url_rule("/thong-bao", endpoint="notifications", view_func=notifications, methods=["GET"])
listings_bp.add_url_rule(
    "/thong-bao/<int:notification_id>/doc", endpoint="mark_notification_read",
    view_func=mark_notification_read, methods=["POST"],
)
listings_bp.add_url_rule(
    "/san-pham/<int:listing_id>/lich-ban", endpoint="block_listing_dates",
    view_func=block_listing_dates, methods=["POST"],
)
listings_bp.add_url_rule(
    "/san-pham/<int:listing_id>/hien-an", endpoint="toggle_listing_visibility",
    view_func=toggle_listing_visibility, methods=["POST"],
)
listings_bp.add_url_rule(
    "/lich-ban/<int:block_id>/xoa", endpoint="remove_listing_block",
    view_func=remove_listing_block, methods=["POST"],
)
