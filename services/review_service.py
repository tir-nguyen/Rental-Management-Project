"""Nghiệp vụ đánh giá sau khi đơn hoàn tất, có tác động tới Trust Score."""
from models import db, Review, User
from services.booking_service import add_trust_delta, _ensure_party, BookingError


def already_reviewed(booking, user):
    return Review.query.filter_by(booking_id=booking.id, reviewer_id=user.id).first() is not None


def submit_review(booking, actor, rating, comment):
    _ensure_party(booking, actor)
    if booking.status != "COMPLETED":
        raise BookingError("Chỉ có thể đánh giá sau khi đơn đã hoàn tất.")

    reviewee_id = booking.lender_id if actor.id == booking.renter_id else booking.renter_id
    try:
        rating = int(rating)
    except (TypeError, ValueError) as exc:
        raise BookingError("Điểm đánh giá phải từ 1 đến 5 sao.") from exc
    if rating < 1 or rating > 5:
        raise BookingError("Điểm đánh giá phải từ 1 đến 5 sao.")
    if already_reviewed(booking, actor):
        raise BookingError("Bạn đã đánh giá đơn hàng này.")

    db.session.add(Review(
        booking_id=booking.id, reviewer_id=actor.id,
        reviewee_id=reviewee_id, rating=rating, comment=comment,
    ))

    reviewee = User.query.get(reviewee_id)
    if rating <= 1:
        add_trust_delta(reviewee, -15, "Bị đánh giá 1 sao", booking.id)
    elif rating >= 5:
        add_trust_delta(reviewee, 2, "Được đánh giá 5 sao", booking.id)

    db.session.commit()
