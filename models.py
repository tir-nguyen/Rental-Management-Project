from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

DISTRICTS = [
    "Ba Đình", "Hoàn Kiếm", "Hai Bà Trưng", "Đống Đa", "Cầu Giấy",
    "Thanh Xuân", "Hoàng Mai", "Long Biên", "Nam Từ Liêm", "Bắc Từ Liêm",
    "Tây Hồ", "Hà Đông", "Gia Lâm", "Đông Anh", "Thanh Trì",
]

CATEGORIES = [
    "Máy ảnh & Thiết bị", "Xe cộ", "Trang phục", "Sách & Giáo trình",
    "Phụ kiện sự kiện", "Dụng cụ thể thao", "Đồ gia dụng & Khác",
]

BOOKING_STATUSES = [
    "PENDING", "APPROVED", "REJECTED", "EXPIRED",
    "DEPOSIT_WAITING", "READY_FOR_PICKUP", "IN_USE",
    "RETURN_PENDING", "COMPLETED", "DISPUTED", "CANCELLED",
]


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    school_email = db.Column(db.String(160), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email_verified = db.Column(db.Boolean, default=False)
    phone_verified = db.Column(db.Boolean, default=False)
    kyc_status = db.Column(db.String(20), default="NONE")  # NONE, PENDING, APPROVED, REJECTED
    kyc_card_image = db.Column(db.String(255))
    trust_score = db.Column(db.Integer, default=100)
    district = db.Column(db.String(60))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    listings = db.relationship("Listing", backref="owner", lazy=True)

    @property
    def is_verified(self):
        return self.email_verified and self.phone_verified and self.kyc_status == "APPROVED"

    @property
    def can_rent(self):
        return self.is_verified and self.trust_score >= 70

    @property
    def deposit_discount(self):
        return 0.5 if self.trust_score > 120 else 1.0


class Listing(db.Model):
    __tablename__ = "listings"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(60))
    district = db.Column(db.String(60))
    price_per_day = db.Column(db.Integer, nullable=False)
    deposit_amount = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="AVAILABLE")  # AVAILABLE, RENTED, HIDDEN
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    images = db.relationship("ListingImage", backref="listing", lazy=True, cascade="all, delete-orphan")
    bookings = db.relationship("Booking", backref="listing", lazy=True)
    blocks = db.relationship("AvailabilityBlock", backref="listing", lazy=True, cascade="all, delete-orphan")

    @property
    def cover_image(self):
        return self.images[0].image_url if self.images else None


class ListingImage(db.Model):
    __tablename__ = "listing_images"
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)


class AvailabilityBlock(db.Model):
    __tablename__ = "availability_blocks"
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(20), default="BOOKED")  # BOOKED, LENDER_BLOCKED
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"))


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    renter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    lender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default="PENDING")
    meetup_note = db.Column(db.String(255))
    total_rent_amount = db.Column(db.Integer, default=0)
    deposit_amount = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)

    renter = db.relationship("User", foreign_keys=[renter_id])
    lender = db.relationship("User", foreign_keys=[lender_id])
    messages = db.relationship("Message", backref="booking", lazy=True, order_by="Message.sent_at")
    evidences = db.relationship("HandoverEvidence", backref="booking", lazy=True)
    transactions = db.relationship("Transaction", backref="booking", lazy=True)
    payment_attempts = db.relationship("PaymentAttempt", backref="booking", lazy=True)
    dispute = db.relationship("Dispute", backref="booking", uselist=False)
    review = db.relationship("Review", backref="booking", lazy=True)

    @property
    def rental_days(self):
        return max((self.end_date - self.start_date).days, 1)


class HandoverEvidence(db.Model):
    __tablename__ = "handover_evidences"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    type = db.Column(db.String(20))  # CHECK_IN, CHECK_OUT
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    media_url = db.Column(db.String(255))
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    type = db.Column(db.String(30))  # VNPAY_PAYMENT, RENT_PAYOUT, RENT_REFUND, DEPOSIT_REFUND, DEPOSIT_DEDUCTION
    amount = db.Column(db.Integer)
    status = db.Column(db.String(20), default="SUCCESS")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PaymentAttempt(db.Model):
    __tablename__ = "payment_attempts"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    txn_ref = db.Column(db.String(64), unique=True, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    response_code = db.Column(db.String(10))
    transaction_no = db.Column(db.String(32))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    paid_at = db.Column(db.DateTime)


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User")


class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Dispute(db.Model):
    __tablename__ = "disputes"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reason = db.Column(db.Text)
    resolution = db.Column(db.String(30))  # FULL_REFUND, LENDER_COMPENSATION, SPLIT
    resolution_note = db.Column(db.Text)
    status = db.Column(db.String(20), default="OPEN")  # OPEN, RESOLVED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)


class TrustScoreLog(db.Model):
    __tablename__ = "trust_score_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"))
    delta = db.Column(db.Integer)
    reason = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"))
    message = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)

    user = db.relationship("User", backref=db.backref("notifications", lazy=True))
    booking = db.relationship("Booking")
