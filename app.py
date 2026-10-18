import hmac
import os
import secrets

from flask import Flask, abort, request, session
from flask_login import LoginManager, current_user
from dotenv import load_dotenv
from sqlalchemy import inspect, text

from models import db, User, Booking, AvailabilityBlock
from services import booking_service, notification_service, seed_service
from routes import register_blueprints

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(32)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'rental.db')}"
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
app.config["VNPAY_TMN_CODE"] = os.environ.get("VNPAY_TMN_CODE", "")
app.config["VNPAY_HASH_SECRET"] = os.environ.get("VNPAY_HASH_SECRET", "")
app.config["VNPAY_PAYMENT_URL"] = os.environ.get(
    "VNPAY_PAYMENT_URL", "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
)
app.config["VNPAY_RETURN_URL"] = os.environ.get("VNPAY_RETURN_URL", "")

db.init_app(app)
_schema_ready = False


def ensure_database_schema():
    global _schema_ready
    if not _schema_ready:
        db.create_all()
        columns = {column["name"] for column in inspect(db.engine).get_columns("bookings")}
        if "approved_at" not in columns:
            db.session.execute(text("ALTER TABLE bookings ADD COLUMN approved_at DATETIME"))
        db.session.execute(text(
            "UPDATE bookings SET approved_at = created_at "
            "WHERE status IN ('APPROVED', 'DEPOSIT_WAITING') AND approved_at IS NULL"
        ))
        active_bookings = Booking.query.filter(Booking.status.in_(
            ("PENDING", "APPROVED", "DEPOSIT_WAITING", "READY_FOR_PICKUP", "IN_USE", "RETURN_PENDING", "DISPUTED")
        )).all()
        for booking in active_bookings:
            if not AvailabilityBlock.query.filter_by(booking_id=booking.id).first():
                db.session.add(AvailabilityBlock(
                    listing_id=booking.listing_id, start_date=booking.start_date,
                    end_date=booking.end_date, reason="BOOKED", booking_id=booking.id,
                ))
        db.session.commit()
        _schema_ready = True


@app.before_request
def protect_post_requests_from_csrf():
    if request.method == "POST":
        expected = session.get("_csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not submitted or not hmac.compare_digest(expected, submitted):
            abort(400)


@app.before_request
def prepare_database_and_expire_bookings():
    ensure_database_schema()
    if request.path.startswith(("/don-hang", "/san-pham/")):
        booking_service.expire_stale_bookings()


login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.context_processor
def inject_unread_notification_count():
    token = session.setdefault("_csrf_token", secrets.token_urlsafe(32))
    if current_user.is_authenticated:
        return {
            "unread_notification_count": notification_service.unread_count(current_user.id),
            "csrf_token": token,
        }
    return {"unread_notification_count": 0, "csrf_token": token}


register_blueprints(app)


@app.cli.command("init-db")
def init_db():
    """Initialize the local database schema."""
    ensure_database_schema()
    print("Database initialized.")


@app.cli.command("seed")
def seed():
    """Create the initial demo accounts and listing if missing."""
    ensure_database_schema()
    seed_service.seed_base_data()


@app.cli.command("seed-demo-data")
def seed_demo_data():
    """Add repeatable demo accounts and listings without replacing user data."""
    ensure_database_schema()
    seed_service.seed_demo_data()


@app.cli.command("expire-bookings")
def expire_bookings_command():
    """Expire stale requests; suitable for a scheduled task."""
    ensure_database_schema()
    count = booking_service.expire_stale_bookings()
    print(f"Expired {count} booking(s).")


if __name__ == "__main__":
    with app.app_context():
        ensure_database_schema()
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)
