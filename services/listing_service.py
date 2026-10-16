"""Nghiệp vụ tin đăng: tìm kiếm/lọc, đăng tin, quản lý ảnh."""
from datetime import datetime
from models import db, Listing, ListingImage, AvailabilityBlock, CATEGORIES, DISTRICTS
from services.upload_service import save_upload, UploadError


class ListingError(ValueError):
    pass


def search_listings(q="", district="", category="", min_price=None, max_price=None,
                    available_from=None, available_to=None):
    query = Listing.query.filter_by(status="AVAILABLE")
    if q:
        query = query.filter(Listing.title.ilike(f"%{q}%"))
    if district:
        query = query.filter_by(district=district)
    if category:
        query = query.filter_by(category=category)
    if min_price is not None:
        query = query.filter(Listing.price_per_day >= min_price)
    if max_price is not None:
        query = query.filter(Listing.price_per_day <= max_price)
    if available_from and available_to:
        overlap = db.and_(
            AvailabilityBlock.start_date < available_to,
            AvailabilityBlock.end_date > available_from,
        )
        query = query.filter(~Listing.blocks.any(overlap))
    return query.order_by(Listing.created_at.desc()).all()


def get_listing_or_404(listing_id):
    return Listing.query.get_or_404(listing_id)


def list_owned(owner_id):
    return Listing.query.filter_by(owner_id=owner_id).order_by(Listing.created_at.desc()).all()


def block_dates(listing, owner_id, start_date, end_date):
    if listing.owner_id != owner_id:
        raise ListingError("Bạn không có quyền cập nhật lịch của tin này.")
    if start_date < datetime.utcnow().date() or end_date <= start_date:
        raise ListingError("Khoảng ngày khóa không hợp lệ.")
    if not _range_is_free(listing.id, start_date, end_date):
        raise ListingError("Khoảng ngày này đã có đơn thuê hoặc ngày bận khác.")
    block = AvailabilityBlock(
        listing_id=listing.id, start_date=start_date, end_date=end_date,
        reason="LENDER_BLOCKED",
    )
    db.session.add(block)
    db.session.commit()
    return block


def _range_is_free(listing_id, start_date, end_date):
    blocks = AvailabilityBlock.query.filter_by(listing_id=listing_id).all()
    return not any(start_date < block.end_date and end_date > block.start_date for block in blocks)


def remove_owner_block(block, owner_id):
    if block.reason != "LENDER_BLOCKED" or block.listing.owner_id != owner_id:
        raise ListingError("Bạn không có quyền xóa ngày bận này.")
    db.session.delete(block)
    db.session.commit()


def toggle_visibility(listing, owner_id):
    if listing.owner_id != owner_id:
        raise ListingError("Bạn không có quyền cập nhật tin này.")
    if listing.status not in ("AVAILABLE", "HIDDEN"):
        raise ListingError("Chỉ có thể ẩn hoặc hiện tin khi món đồ chưa có giao dịch.")
    listing.status = "HIDDEN" if listing.status == "AVAILABLE" else "AVAILABLE"
    db.session.commit()
    return listing


def create_listing(owner_id, form, files, upload_folder):
    title = (form.get("title") or "").strip()
    try:
        price = int(form.get("price_per_day") or 0)
        deposit = int(form.get("deposit_amount") or 0)
    except (TypeError, ValueError) as exc:
        raise ListingError("Giá thuê và tiền cọc phải là số nguyên hợp lệ.") from exc
    if not title:
        raise ListingError("Vui lòng nhập tên món đồ.")
    if price <= 0 or deposit < 0:
        raise ListingError("Giá thuê phải lớn hơn 0 và tiền cọc không được âm.")
    if form.get("category") not in CATEGORIES or form.get("district") not in DISTRICTS:
        raise ListingError("Danh mục hoặc khu vực không hợp lệ.")

    listing = Listing(
        owner_id=owner_id,
        title=title,
        description=form.get("description", "").strip(),
        category=form.get("category"),
        district=form.get("district"),
        price_per_day=price,
        deposit_amount=deposit,
    )
    db.session.add(listing)
    db.session.flush()  # cần listing.id trước khi gắn ảnh

    try:
        for f in files.getlist("images"):
            url = save_upload(f, upload_folder)
            if url:
                db.session.add(ListingImage(listing_id=listing.id, image_url=url))
    except UploadError as exc:
        db.session.rollback()
        raise ListingError(str(exc)) from exc

    db.session.commit()
    return listing
