"""Nghiệp vụ đơn thuê: state machine (PENDING -> ... -> COMPLETED/CANCELLED/DISPUTED)."""
from datetime import datetime, timedelta

from models import (
    db, Booking, AvailabilityBlock, HandoverEvidence, Transaction,
    Message, Dispute, TrustScoreLog, User,
)
from services.upload_service import save_upload
from services.upload_service import EVIDENCE_EXTENSIONS, UploadError
from services import notification_service


class BookingError(Exception):
    """Lỗi nghiệp vụ booking — route bắt và hiển thị flash hoặc trả 403."""


def add_trust_delta(user, delta, reason, booking_id=None):
    user.trust_score = max(0, user.trust_score + delta)
    db.session.add(TrustScoreLog(user_id=user.id, booking_id=booking_id, delta=delta, reason=reason))


def is_range_free(listing_id, start_date, end_date, exclude_booking_id=None):
    blocks = AvailabilityBlock.query.filter_by(listing_id=listing_id).all()
    for b in blocks:
        if b.booking_id == exclude_booking_id:
            continue
        if start_date < b.end_date and end_date > b.start_date:
            return False
    return True


def create_request(listing, renter, start_date, end_date):
    if listing.owner_id == renter.id:
        raise BookingError("Bạn không thể tự thuê đồ của chính mình.")
    if not renter.can_rent:
        raise BookingError("Bạn cần xác minh thẻ sinh viên và có Trust Score từ 70 để gửi yêu cầu thuê.")
    if start_date < datetime.utcnow().date():
        raise BookingError("Ngày nhận không thể ở trong quá khứ.")
    if listing.status != "AVAILABLE":
        raise BookingError("Món đồ hiện không còn sẵn sàng cho thuê.")
    if end_date <= start_date:
        raise BookingError("Ngày trả phải sau ngày nhận.")
    if not is_range_free(listing.id, start_date, end_date):
        raise BookingError("Khoảng thời gian này đã có người đặt.")

    days = (end_date - start_date).days
    deposit = int(listing.deposit_amount * renter.deposit_discount)

    booking = Booking(
        listing_id=listing.id,
        renter_id=renter.id,
        lender_id=listing.owner_id,
        start_date=start_date,
        end_date=end_date,
        status="PENDING",
        total_rent_amount=listing.price_per_day * days,
        deposit_amount=deposit,
    )
    db.session.add(booking)
    db.session.flush()
    db.session.add(AvailabilityBlock(
        listing_id=listing.id, start_date=start_date, end_date=end_date,
        reason="BOOKED", booking_id=booking.id,
    ))
    notification_service.notify(booking.lender_id, "Bạn có yêu cầu thuê mới cần phản hồi.", booking.id)
    db.session.commit()
    return booking


def respond(booking, actor, decision):
    if actor.id != booking.lender_id or booking.status != "PENDING":
        raise BookingError("Không có quyền thực hiện hành động này.", )
    if decision not in ("approve", "reject"):
        raise BookingError("Quyết định không hợp lệ.")
    booking.status = "APPROVED" if decision == "approve" else "REJECTED"
    if decision == "approve":
        booking.approved_at = datetime.utcnow()
    else:
        AvailabilityBlock.query.filter_by(booking_id=booking.id).delete()
    notification_service.notify(
        booking.renter_id,
        "Yêu cầu thuê đã được chấp nhận." if decision == "approve" else "Yêu cầu thuê đã bị từ chối.",
        booking.id,
    )
    db.session.commit()
    return booking


def _ensure_party(booking, user):
    if user.id not in (booking.renter_id, booking.lender_id):
        raise BookingError("Bạn không liên quan đến đơn hàng này.")


def _save_evidence_files(files, upload_folder):
    files = [file for file in (files or []) if file and file.filename]
    if not 4 <= len(files) <= 6:
        raise BookingError("Vui lòng tải lên từ 4 đến 6 ảnh/video làm bằng chứng.")
    try:
        return [save_upload(file, upload_folder, EVIDENCE_EXTENSIONS) for file in files]
    except UploadError as exc:
        raise BookingError(str(exc)) from exc


def checkin(booking, actor, note, media_files, upload_folder):
    _ensure_party(booking, actor)
    if HandoverEvidence.query.filter_by(
        booking_id=booking.id, type="CHECK_IN", uploaded_by=actor.id
    ).first():
        raise BookingError("Bạn đã xác nhận bàn giao đơn hàng này.")
    if booking.status != "READY_FOR_PICKUP":
        raise BookingError("Đơn chưa sẵn sàng để bàn giao.")

    media_urls = _save_evidence_files(media_files, upload_folder)
    db.session.add_all([HandoverEvidence(
        booking_id=booking.id, type="CHECK_IN", uploaded_by=actor.id,
        media_url=media, note=note,
    ) for media in media_urls])
    db.session.commit()

    checkins = [e for e in booking.evidences if e.type == "CHECK_IN"]
    uploaders = {e.uploaded_by for e in checkins}
    both_confirmed = booking.renter_id in uploaders and booking.lender_id in uploaders
    if both_confirmed:
        booking.status = "IN_USE"
    notification_service.notify_booking_parties(
        booking,
        "Một bên đã xác nhận bàn giao đồ." if not both_confirmed else "Hai bên đã xác nhận bàn giao; đơn đang IN_USE.",
        exclude_user_id=actor.id,
    )
    db.session.commit()
    return booking, both_confirmed


def checkout(booking, actor, note, media_files, upload_folder):
    _ensure_party(booking, actor)
    if actor.id != booking.renter_id:
        raise BookingError("Chỉ người thuê mới có thể xác nhận trả đồ.")
    if booking.status != "IN_USE":
        raise BookingError("Đơn chưa ở trạng thái đang sử dụng.")

    media_urls = _save_evidence_files(media_files, upload_folder)
    db.session.add_all([HandoverEvidence(
        booking_id=booking.id, type="CHECK_OUT", uploaded_by=actor.id,
        media_url=media, note=note,
    ) for media in media_urls])
    booking.status = "RETURN_PENDING"
    notification_service.notify(booking.lender_id, "Người thuê đã gửi xác nhận trả đồ; hãy kiểm tra và xác nhận.", booking.id)
    db.session.commit()
    return booking


def complete(booking, actor):
    if actor.id != booking.lender_id or booking.status != "RETURN_PENDING":
        raise BookingError("Không có quyền thực hiện hành động này.")

    db.session.add(Transaction(booking_id=booking.id, type="RENT_PAYOUT", amount=booking.total_rent_amount))
    db.session.add(Transaction(booking_id=booking.id, type="DEPOSIT_REFUND", amount=booking.deposit_amount))
    booking.status = "COMPLETED"
    AvailabilityBlock.query.filter_by(booking_id=booking.id).delete()
    add_trust_delta(booking.renter, 3, "Hoàn tất đơn thuê", booking.id)
    add_trust_delta(booking.lender, 3, "Hoàn tất đơn cho thuê", booking.id)
    notification_service.notify(booking.renter_id, "Đơn thuê đã hoàn tất; bạn có thể gửi đánh giá.", booking.id)
    db.session.commit()
    return booking


def cancel(booking, actor):
    _ensure_party(booking, actor)
    if booking.status not in ("PENDING", "APPROVED", "DEPOSIT_WAITING"):
        raise BookingError("Không thể hủy đơn ở trạng thái hiện tại.")
    booking.status = "CANCELLED"
    AvailabilityBlock.query.filter_by(booking_id=booking.id).delete()
    notification_service.notify_booking_parties(booking, "Đơn thuê đã bị hủy.", exclude_user_id=actor.id)
    db.session.commit()
    return booking


def open_dispute(booking, actor, reason):
    _ensure_party(booking, actor)
    if booking.status not in ("IN_USE", "RETURN_PENDING"):
        raise BookingError("Không thể mở tranh chấp ở trạng thái hiện tại.")
    db.session.add(Dispute(booking_id=booking.id, opened_by=actor.id, reason=reason))
    booking.status = "DISPUTED"
    notification_service.notify_booking_parties(booking, "Một bên đã mở tranh chấp cho đơn thuê.", exclude_user_id=actor.id)
    for admin in User.query.filter_by(is_admin=True).all():
        notification_service.notify(admin.id, "Có tranh chấp mới cần xử lý.", booking.id)
    db.session.commit()
    return booking


def send_message(booking, actor, content):
    _ensure_party(booking, actor)
    content = (content or "").strip()
    if content:
        db.session.add(Message(booking_id=booking.id, sender_id=actor.id, content=content))
        other_id = booking.lender_id if actor.id == booking.renter_id else booking.renter_id
        notification_service.notify(other_id, "Bạn có tin nhắn mới trong đơn thuê.", booking.id)
        db.session.commit()
    return booking


def expire_stale_bookings(now=None):
    """Expire requests after 24h and approved deposits after 4h."""
    now = now or datetime.utcnow()
    pending_cutoff = now - timedelta(hours=24)
    approved_cutoff = now - timedelta(hours=4)
    expired = Booking.query.filter(
        db.or_(
            db.and_(Booking.status == "PENDING", Booking.created_at <= pending_cutoff),
            db.and_(Booking.status.in_(("APPROVED", "DEPOSIT_WAITING")),
                    Booking.approved_at.is_not(None), Booking.approved_at <= approved_cutoff),
        )
    ).all()
    for booking in expired:
        booking.status = "EXPIRED"
        AvailabilityBlock.query.filter_by(booking_id=booking.id).delete()
        notification_service.notify_booking_parties(booking, "Yêu cầu thuê đã hết hạn và được tự động đóng.")
    reminder_date = now.date() + timedelta(days=1)
    returning = Booking.query.filter(
        Booking.status == "IN_USE", Booking.end_date == reminder_date
    ).all()
    overdue = Booking.query.filter(
        Booking.status == "IN_USE", Booking.end_date < now.date()
    ).all()
    for booking in returning:
        notification_service.notify_once(
            booking.renter_id, "Ngày mai là hạn trả món đồ đang thuê.", booking.id
        )
    for booking in overdue:
        notification_service.notify_once(
            booking.renter_id, "Đơn thuê đã quá hạn trả đồ; hãy liên hệ người cho thuê.", booking.id
        )
    if expired or returning or overdue:
        db.session.commit()
    return len(expired)
