"""Profile queries and self-service profile updates."""
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from models import Booking, DISTRICTS, Listing, Review, User, db


class ProfileError(ValueError):
    """Profile data could not be saved."""


def update_own_profile(user, full_name, district):
    full_name = (full_name or "").strip()
    district = (district or "").strip()

    if not full_name:
        raise ProfileError("Vui lòng nhập họ tên.")
    if len(full_name) > 120:
        raise ProfileError("Họ tên không được vượt quá 120 ký tự.")
    if district and district not in DISTRICTS:
        raise ProfileError("Khu vực hoạt động không hợp lệ.")

    user.full_name = full_name
    user.district = district or None
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ProfileError("Không thể lưu hồ sơ. Vui lòng kiểm tra lại thông tin.") from exc
    return user


def get_public_profile(user_id, page=1, per_page=12):
    public_user = (
        db.session.query(
            User.id,
            User.full_name,
            User.created_at,
            User.email_verified,
            User.phone_verified,
            User.kyc_status,
        )
        .filter(User.id == user_id)
        .first()
    )
    if public_user is None:
        return None

    rating_average, review_count = (
        db.session.query(func.avg(Review.rating), func.count(Review.id))
        .join(Booking, Review.booking_id == Booking.id)
        .filter(
            Review.reviewee_id == user_id,
            Booking.status == "COMPLETED",
        )
        .one()
    )
    completed_count = Booking.query.filter(
        Booking.status == "COMPLETED",
        or_(Booking.renter_id == user_id, Booking.lender_id == user_id),
    ).count()
    listings = (
        Listing.query.filter_by(owner_id=user_id, status="AVAILABLE")
        .order_by(Listing.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return {
        "user_id": public_user.id,
        "display_name": public_user.full_name,
        "joined_at": public_user.created_at,
        "is_verified": (
            public_user.email_verified
            and public_user.phone_verified
            and public_user.kyc_status == "APPROVED"
        ),
        "rating_average": round(float(rating_average), 1) if review_count else None,
        "review_count": review_count,
        "completed_count": completed_count,
        "listings": listings,
    }
