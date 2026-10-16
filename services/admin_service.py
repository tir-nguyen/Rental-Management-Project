"""Nghiệp vụ Admin: duyệt KYC, xử lý tranh chấp (giải ngân theo quyết định)."""
from datetime import datetime

from models import db, User, Dispute, Transaction, AvailabilityBlock
from services.booking_service import add_trust_delta
from services import notification_service


def pending_kyc_users():
    return User.query.filter_by(kyc_status="PENDING").all()


def open_disputes():
    return Dispute.query.filter_by(status="OPEN").all()


def resolve_kyc(user, decision):
    if user.kyc_status != "PENDING" or decision not in ("approve", "reject"):
        raise ValueError("Hồ sơ KYC không còn chờ duyệt hoặc quyết định không hợp lệ.")
    user.kyc_status = "APPROVED" if decision == "approve" else "REJECTED"
    notification_service.notify(user.id, "Hồ sơ sinh viên đã được duyệt." if decision == "approve" else "Hồ sơ sinh viên chưa được duyệt.")
    db.session.commit()
    return user


def resolve_dispute(dispute, resolution, note):
    if dispute.status != "OPEN":
        raise ValueError("Tranh chấp này đã được xử lý.")
    if resolution not in ("FULL_REFUND", "LENDER_COMPENSATION", "SPLIT"):
        raise ValueError("Quyết định xử lý tranh chấp không hợp lệ.")
    booking = dispute.booking

    if resolution == "FULL_REFUND":
        db.session.add(Transaction(booking_id=booking.id, type="DEPOSIT_REFUND", amount=booking.deposit_amount))
    elif resolution == "LENDER_COMPENSATION":
        db.session.add(Transaction(booking_id=booking.id, type="DEPOSIT_DEDUCTION", amount=booking.deposit_amount))
        add_trust_delta(booking.renter, -50, "Vi phạm xác định qua tranh chấp", booking.id)
    else:  # SPLIT
        half = booking.deposit_amount // 2
        db.session.add(Transaction(booking_id=booking.id, type="DEPOSIT_REFUND", amount=half))
        db.session.add(Transaction(booking_id=booking.id, type="DEPOSIT_DEDUCTION", amount=half))

    if resolution == "FULL_REFUND":
        db.session.add(Transaction(booking_id=booking.id, type="RENT_REFUND", amount=booking.total_rent_amount))
    else:
        db.session.add(Transaction(booking_id=booking.id, type="RENT_PAYOUT", amount=booking.total_rent_amount))

    dispute.resolution = resolution
    dispute.resolution_note = note
    dispute.status = "RESOLVED"
    dispute.resolved_at = datetime.utcnow()
    booking.status = "CANCELLED"
    AvailabilityBlock.query.filter_by(booking_id=booking.id).delete()
    notification_service.notify_booking_parties(booking, "Tranh chấp đã được Admin xử lý.")
    db.session.commit()
    return dispute
