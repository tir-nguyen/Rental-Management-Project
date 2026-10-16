"""Admin moderation HTTP handlers."""

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import Dispute, User
from services import admin_service

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
        return redirect(url_for("admin_dashboard"))
    flash(f"Đã cập nhật KYC cho {user.full_name}.", "success")
    return redirect(url_for("admin_dashboard"))

@login_required
def admin_resolve_dispute(dispute_id):
    admin_required()
    dispute = Dispute.query.get_or_404(dispute_id)
    try:
        admin_service.resolve_dispute(dispute, request.form.get("resolution"), request.form.get("note", ""))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin_dashboard"))
    flash("Đã xử lý tranh chấp.", "success")
    return redirect(url_for("admin_dashboard"))


def register_routes(app):
    route_definitions = [
        ("/admin", "admin_dashboard", admin_dashboard, ["GET"]),
        ("/admin/kyc/<int:user_id>", "admin_resolve_kyc", admin_resolve_kyc, ["POST"]),
        ("/admin/tranh-chap/<int:dispute_id>", "admin_resolve_dispute", admin_resolve_dispute, ["POST"]),
    ]
    for rule, endpoint, view, methods in route_definitions:
        app.add_url_rule(rule, endpoint=endpoint, view_func=view, methods=methods)
