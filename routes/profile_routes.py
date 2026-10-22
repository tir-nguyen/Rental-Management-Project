"""Private and public user profile pages."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import DISTRICTS
from services import profile_service

profiles_bp = Blueprint("profiles", __name__)


@profiles_bp.route("/ho-so", methods=["GET", "POST"])
@login_required
def my_profile():
    form_values = None
    if request.method == "POST":
        form_values = request.form
        try:
            profile_service.update_own_profile(
                current_user,
                request.form.get("full_name"),
                request.form.get("district"),
            )
        except profile_service.ProfileError as exc:
            flash(str(exc), "error")
        else:
            flash("Đã cập nhật hồ sơ của bạn.", "success")
            return redirect(url_for("profiles.my_profile"))

    return render_template(
        "profiles/my_profile.html",
        districts=DISTRICTS,
        form_values=form_values,
    )


@profiles_bp.get("/nguoi-dung/<int:user_id>")
def public_profile(user_id):
    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1
    profile = profile_service.get_public_profile(user_id, page=page)
    if profile is None:
        abort(404)
    return render_template("profiles/public_profile.html", profile=profile)
