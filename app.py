
import hmac
import os
import secrets
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

from flask import Flask, abort, request, session
from flask_login import LoginManager, current_user
from flask_migrate import Migrate

from models import db, HandoverEvidence, ListingImage, User
from services import booking_service, notification_service
from routes import register_blueprints
from database_config import (
    get_database_uri,
    get_rental_test_postgresql_uri,
    is_flask_migrate_command,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(32)
if is_flask_migrate_command(sys.argv):
    app.config["SQLALCHEMY_DATABASE_URI"] = get_rental_test_postgresql_uri()
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri(BASE_DIR)
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "uploads")
app.config["PRIVATE_UPLOAD_FOLDER"] = os.path.join(
    app.instance_path, "private_uploads"
)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

app.config["VNPAY_TMN_CODE"] = os.environ.get("VNPAY_TMN_CODE", "")
app.config["VNPAY_HASH_SECRET"] = os.environ.get("VNPAY_HASH_SECRET", "")
vnpay_payment_url = os.environ.get(
    "VNPAY_PAYMENT_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
)
app.config["VNPAY_PAYMENT_URL"] = vnpay_payment_url
return_confirmation_default = (
    "1" if urlparse(vnpay_payment_url).hostname == "sandbox.vnpayment.vn" else "0"
)
app.config["VNPAY_CONFIRM_ON_RETURN"] = os.environ.get(
    "VNPAY_CONFIRM_ON_RETURN", return_confirmation_default
).strip().lower() in ("1", "true", "yes", "on")
app.config["VNPAY_RETURN_URL"] = os.environ.get("VNPAY_RETURN_URL", "")

db.init_app(app)
Migrate(app, db, compare_type=True)


@app.before_request
def protect_post_requests_from_csrf():
    if request.method == "POST":
        expected = session.get("_csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not submitted or not hmac.compare_digest(expected, submitted):
            abort(400)


@app.before_request
def prepare_database_and_expire_bookings():
    if request.path.startswith(("/don-hang", "/san-pham/")):
        booking_service.expire_stale_bookings()


@app.before_request
def protect_private_static_uploads():
    if request.endpoint != "static":
        return
    filename = request.view_args.get("filename", "") if request.view_args else ""
    if not filename.startswith("uploads/"):
        return
    if (
        User.query.filter_by(kyc_card_image=filename).first()
        or HandoverEvidence.query.filter_by(media_url=filename).first()
    ):
        abort(404)
    if not ListingImage.query.filter_by(image_url=filename).first():
        abort(404)


login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_unread_notification_count():
    token = session.setdefault("_csrf_token", secrets.token_urlsafe(32))
    if current_user.is_authenticated:
        return {
            "unread_notification_count": notification_service.unread_count(current_user.id),
            "notification_preview": notification_service.list_for_user(current_user.id, limit=5),
            "csrf_token": token,
        }
    return {"unread_notification_count": 0, "notification_preview": [], "csrf_token": token}


register_blueprints(app)


@app.cli.command("expire-bookings")
def expire_bookings_command():
    """Expire stale requests; suitable for a scheduled task."""
    count = booking_service.expire_stale_bookings()
    print(f"Expired {count} booking(s).")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)
