from datetime import datetime, timedelta, timezone

from models import db, Notification

VIETNAM_TIMEZONE = timezone(timedelta(hours=7))


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


def mark_all_read(user_id):
    count = Notification.query.filter_by(
        user_id=user_id, read_at=None
    ).update(
        {Notification.read_at: datetime.utcnow()},
        synchronize_session=False,
    )
    db.session.commit()
    return count


def group_by_date(notifications, today=None):
    today = today or datetime.now(VIETNAM_TIMEZONE).date()
    groups = {}
    group_order = []
    labels = (
        (0, "Hôm nay"),
        (1, "Hôm qua"),
        (6, "Tuần này"),
        (13, "Tuần trước"),
    )

    for notification in notifications:
        created_at = notification.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age = max((today - created_at.astimezone(VIETNAM_TIMEZONE).date()).days, 0)
        label = next(
            (name for max_age, name in labels if age <= max_age),
            "Trước đó",
        )
        if label not in groups:
            groups[label] = []
            group_order.append(label)
        groups[label].append(notification)

    return [
        {"label": label, "notifications": groups[label]}
        for label in group_order
    ]
