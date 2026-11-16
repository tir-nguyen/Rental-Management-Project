"""Admin moderation HTTP handlers."""

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from models import Dispute, User
from services import admin_service
from services.upload_service import send_private_upload

admin_bp = Blueprint("admin", __name__)


def admin_required():
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)

@login_required
def admin_dashboard():
    admin_required()
    return render_template(
        "admin/dashboard.html",
        pending_kyc=admin_service.pending_kyc_users(),
        disputes=admin_service.open_disputes(),
    )

@login_required
def admin_resolve_kyc(user_id):
    admin_required()
    user = User.query.get_or_404(user_id)
    try:
        admin_service.resolve_kyc(user, request.form.get("decision"))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.admin_dashboard"))
    flash(f"Đã cập nhật KYC cho {user.full_name}.", "success")
    return redirect(url_for("admin.admin_dashboard"))


@login_required
def admin_kyc_image(user_id):
    admin_required()
    user = User.query.get_or_404(user_id)
    image_path = user.kyc_card_image or ""
    if not image_path.startswith("uploads/"):
        abort(404)
    return send_private_upload(image_path)


@login_required
def admin_resolve_dispute(dispute_id):
    admin_required()
    dispute = Dispute.query.get_or_404(dispute_id)
    try:
        admin_service.resolve_dispute(dispute, request.form.get("resolution"), request.form.get("note", ""))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.admin_dashboard"))
    flash("Đã xử lý tranh chấp.", "success")
    return redirect(url_for("admin.admin_dashboard"))


admin_bp.add_url_rule("/admin", endpoint="admin_dashboard", view_func=admin_dashboard, methods=["GET"])
admin_bp.add_url_rule(
    "/admin/kyc/<int:user_id>", endpoint="admin_resolve_kyc",
    view_func=admin_resolve_kyc, methods=["POST"],
)
admin_bp.add_url_rule(
    "/admin/kyc/<int:user_id>/image", endpoint="admin_kyc_image",
    view_func=admin_kyc_image, methods=["GET"],
)
admin_bp.add_url_rule(
    "/admin/tranh-chap/<int:dispute_id>", endpoint="admin_resolve_dispute",
    view_func=admin_resolve_dispute, methods=["POST"],
)
