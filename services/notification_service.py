from datetime import datetime

from models import db, Notification


def notify(user_id, message, booking_id=None):
    db.session.add(Notification(user_id=user_id, message=message, booking_id=booking_id))


def notify_once(user_id, message, booking_id=None):
    existing = Notification.query.filter_by(
        user_id=user_id, message=message, booking_id=booking_id
    ).first()
    if not existing:
        notify(user_id, message, booking_id)


def notify_booking_parties(booking, message, exclude_user_id=None):
    for user_id in (booking.renter_id, booking.lender_id):
        if user_id != exclude_user_id:
            notify(user_id, message, booking.id)


def unread_count(user_id):
    return Notification.query.filter_by(user_id=user_id, read_at=None).count()


def list_for_user(user_id, limit=None):
    query = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def mark_read(notification, user_id):
    if notification.user_id != user_id:
        return False
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        db.session.commit()
    return True
