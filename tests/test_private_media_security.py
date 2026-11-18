import os
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.datastructures import FileMultiDict, FileStorage, MultiDict

os.environ["DATABASE_URL"] = "sqlite://"

from app import app
from models import (
    Booking, CATEGORIES, DISTRICTS, Dispute, HandoverEvidence, Listing,
    ListingImage, Message, Notification, User, db,
)
from services import booking_service, notification_service
from services import listing_service


class PrivateMediaSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_directory.name)
        cls.static_root = cls.root / "static"
        cls.upload_root = cls.static_root / "uploads"
        cls.private_root = cls.root / "private_uploads"
        cls.upload_root.mkdir(parents=True)

        app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite://",
            UPLOAD_FOLDER=str(cls.upload_root),
            PRIVATE_UPLOAD_FOLDER=str(cls.private_root),
        )
        app.static_folder = str(cls.static_root)

        with app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        cls.temp_directory.cleanup()

    def setUp(self):
        with app.app_context():
            db.drop_all()
            db.create_all()

            self.renter = self._make_user("renter", "0900000001")
            self.lender = self._make_user("lender", "0900000002")
            self.outsider = self._make_user("outsider", "0900000003")
            self.admin = self._make_user("admin", "0900000004", is_admin=True)
            db.session.add_all(
                [self.renter, self.lender, self.outsider, self.admin]
            )
            db.session.flush()

            self.listing = Listing(
                owner_id=self.lender.id,
                title="Synthetic listing",
                price_per_day=100,
                status="AVAILABLE",
            )
            db.session.add(self.listing)
            db.session.flush()
            self.booking = Booking(
                listing_id=self.listing.id,
                renter_id=self.renter.id,
                lender_id=self.lender.id,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=1),
                status="READY_FOR_PICKUP",
            )
            db.session.add(self.booking)
            db.session.flush()
            self.evidence = HandoverEvidence(
                booking_id=self.booking.id,
                uploaded_by=self.renter.id,
                media_url="uploads/evidence.jpg",
            )
            self.kyc_key = "uploads/kyc.jpg"
            self.renter.kyc_card_image = self.kyc_key
            self.renter.kyc_status = "PENDING"
            db.session.add_all(
                [
                    self.evidence,
                    ListingImage(
                        listing_id=self.listing.id,
                        image_url="uploads/listing.jpg",
                    ),
                    Dispute(
                        booking_id=self.booking.id,
                        opened_by=self.renter.id,
                        reason="Synthetic dispute",
                        status="OPEN",
                    ),
                ]
            )
            db.session.commit()

            self.renter_id = self.renter.id
            self.lender_id = self.lender.id
            self.outsider_id = self.outsider.id
            self.admin_id = self.admin.id
            self.listing_id = self.listing.id
            self.booking_id = self.booking.id
            self.evidence_id = self.evidence.id

        self.client = app.test_client()

    def _make_user(self, label, phone, is_admin=False):
        return User(
            full_name=f"Synthetic {label}",
            school_email=f"{label}@example.invalid",
            phone_number=phone,
            password_hash="synthetic-hash",
            is_admin=is_admin,
        )

    def _login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
            session["_csrf_token"] = "test-csrf-token"

    def _write_upload(self, root, filename, content=b"synthetic-media"):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _get_status(self, url):
        response = self.client.get(url)
        try:
            return response.status_code
        finally:
            response.close()

    def test_static_allows_listing_images_but_denies_private_and_orphan_keys(self):
        self._write_upload(self.upload_root, "listing.jpg")
        self._write_upload(self.upload_root, "evidence.jpg")
        self._write_upload(self.upload_root, "kyc.jpg")
        self._write_upload(self.upload_root, "orphan.jpg")

        self.assertEqual(self._get_status("/static/uploads/listing.jpg"), 200)
        for key in ("evidence.jpg", "kyc.jpg", "orphan.jpg"):
            with self.subTest(key=key):
                self.assertEqual(self._get_status(f"/static/uploads/{key}"), 404)

        with app.app_context():
            renter = db.session.get(User, self.renter_id)
            renter.kyc_card_image = "uploads/replacement.jpg"
            db.session.commit()
        self.assertEqual(self._get_status("/static/uploads/kyc.jpg"), 404)

    def test_kyc_route_requires_admin_and_serves_private_or_legacy_file(self):
        self._write_upload(self.upload_root, "kyc.jpg")
        self.assertEqual(
            self._get_status(f"/admin/kyc/{self.renter_id}/image"), 302
        )

        self._login_as(self.outsider_id)
        self.assertEqual(
            self._get_status(f"/admin/kyc/{self.renter_id}/image"), 403
        )

        self._login_as(self.admin_id)
        response = self.client.get(f"/admin/kyc/{self.renter_id}/image")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers["Cache-Control"])
        finally:
            response.close()

    def test_evidence_route_allows_parties_and_admin_only(self):
        self._write_upload(self.private_root, "evidence.jpg")
        url = (
            f"/don-hang/{self.booking_id}/evidence/{self.evidence_id}"
        )
        self.assertEqual(self._get_status(url), 302)

        self._login_as(self.outsider_id)
        self.assertEqual(self._get_status(url), 403)

        for user_id in (self.renter_id, self.lender_id, self.admin_id):
            with self.subTest(user_id=user_id):
                self._login_as(user_id)
                response = self.client.get(url)
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("no-store", response.headers["Cache-Control"])
                finally:
                    response.close()

        self._login_as(self.renter_id)
        self.assertEqual(
            self._get_status(
                f"/don-hang/{self.booking_id + 100}/evidence/{self.evidence_id}"
            ),
            404,
        )

    def test_chat_endpoint_returns_new_messages_only_to_booking_parties(self):
        with app.app_context():
            first = Message(
                booking_id=self.booking_id,
                sender_id=self.renter_id,
                content="First synthetic message",
            )
            second = Message(
                booking_id=self.booking_id,
                sender_id=self.lender_id,
                content="Second synthetic message",
            )
            db.session.add_all([first, second])
            db.session.commit()
            first_id = first.id
            second_id = second.id

        self._login_as(self.renter_id)
        with patch("services.booking_service.expire_stale_bookings") as expire:
            response = self.client.get(
                f"/don-hang/{self.booking_id}/chat/messages?after_id={first_id}"
            )
            expire.assert_not_called()
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.get_json()["messages"],
                [
                    {
                        "id": second_id,
                        "sender_id": self.lender_id,
                        "content": "Second synthetic message",
                    }
                ],
            )
            self.assertIn("no-store", response.headers["Cache-Control"])
        finally:
            response.close()

        self._login_as(self.outsider_id)
        self.assertEqual(
            self._get_status(
                f"/don-hang/{self.booking_id}/chat/messages?after_id=0"
            ),
            403,
        )

    def test_sent_message_becomes_visible_to_other_party_without_posting_back(self):
        self._login_as(self.renter_id)
        sent = self.client.post(
            f"/don-hang/{self.booking_id}/chat",
            data={
                "csrf_token": "test-csrf-token",
                "content": "Hello from the renter",
            },
        )
        self.assertEqual(sent.status_code, 302)
        sent.close()

        self._login_as(self.lender_id)
        response = self.client.get(
            f"/don-hang/{self.booking_id}/chat/messages?after_id=0"
        )
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.get_json()["messages"][0]["content"],
                "Hello from the renter",
            )
        finally:
            response.close()

    def test_booking_detail_exposes_private_chat_polling_endpoint_and_cursor(self):
        with app.app_context():
            message = Message(
                booking_id=self.booking_id,
                sender_id=self.renter_id,
                content="Synthetic initial message",
            )
            db.session.add(message)
            db.session.commit()
            message_id = message.id

        self._login_as(self.lender_id)
        response = self.client.get(f"/don-hang/{self.booking_id}")
        try:
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                f'data-messages-url="/don-hang/{self.booking_id}/chat/messages"',
                body,
            )
            self.assertIn(f'data-last-message-id="{message_id}"', body)
            self.assertIn('data-message-id="' + str(message_id) + '"', body)
        finally:
            response.close()

    def test_booking_status_filter_returns_vietnamese_labels(self):
        labels = app.jinja_env.filters["status_vi"]
        self.assertEqual(labels("AVAILABLE"), "Đang cho thuê")
        self.assertEqual(labels("COMPLETED"), "Hoàn tất")
        self.assertEqual(labels("EXPIRED"), "Hết hạn")
        self.assertEqual(labels("IN_USE"), "Đang sử dụng")
        self.assertEqual(labels("UNEXPECTED"), "UNEXPECTED")

    def test_notifications_are_grouped_by_vietnam_local_day(self):
        items = [
            Notification(
                user_id=self.renter_id,
                message="Today",
                created_at=datetime(2026, 1, 7, 2),
            ),
            Notification(
                user_id=self.renter_id,
                message="Yesterday",
                created_at=datetime(2026, 1, 6, 2),
            ),
            Notification(
                user_id=self.renter_id,
                message="Last week",
                created_at=datetime(2025, 12, 30, 18),
            ),
        ]
        groups = notification_service.group_by_date(items, date(2026, 1, 7))
        self.assertEqual(
            [group["label"] for group in groups],
            ["Hôm nay", "Hôm qua", "Tuần trước"],
        )

    def test_mark_all_notifications_read_is_scoped_to_current_user(self):
        with app.app_context():
            db.session.add_all(
                [
                    Notification(user_id=self.renter_id, message="One"),
                    Notification(user_id=self.renter_id, message="Two"),
                    Notification(user_id=self.outsider_id, message="Other"),
                ]
            )
            db.session.commit()

        self._login_as(self.renter_id)
        page = self.client.get("/thong-bao")
        self.assertIn("2 chưa đọc · 2 tổng cộng", page.get_data(as_text=True))
        page.close()
        response = self.client.post(
            "/thong-bao/doc-tat-ca",
            data={"csrf_token": "test-csrf-token"},
        )
        self.assertEqual(response.status_code, 302)
        response.close()

        with app.app_context():
            self.assertEqual(
                Notification.query.filter_by(
                    user_id=self.renter_id, read_at=None
                ).count(),
                0,
            )
            self.assertEqual(
                Notification.query.filter_by(
                    user_id=self.outsider_id, read_at=None
                ).count(),
                1,
            )

    def test_expired_booking_notification_is_created_once_per_party(self):
        with app.app_context():
            booking = Booking(
                listing_id=self.listing_id,
                renter_id=self.renter_id,
                lender_id=self.lender_id,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=1),
                status="PENDING",
                created_at=datetime.utcnow() - timedelta(days=2),
            )
            db.session.add(booking)
            db.session.commit()
            booking_id = booking.id
            booking_service.expire_stale_bookings()
            booking_service.expire_stale_bookings()

            expiry_notifications = Notification.query.filter_by(
                booking_id=booking_id,
                message="Yêu cầu thuê đã hết hạn và được tự động đóng.",
            ).all()
            self.assertEqual(len(expiry_notifications), 2)
            self.assertEqual(
                {item.user_id for item in expiry_notifications},
                {self.renter_id, self.lender_id},
            )

    def test_registration_form_describes_supported_email_and_demo_otp(self):
        response = self.client.get("/dang-ky")
        try:
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("ten@gmail.com", body)
            self.assertNotIn(".edu.vn", body)
            self.assertIn("chưa gửi qua SMS", body)
        finally:
            response.close()

    def test_listing_form_exposes_dropzone_and_individual_image_removal(self):
        with app.app_context():
            lender = db.session.get(User, self.lender_id)
            lender.email_verified = True
            lender.phone_verified = True
            lender.kyc_status = "APPROVED"
            db.session.commit()

        self._login_as(self.lender_id)
        response = self.client.get("/dang-tin")
        try:
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("data-listing-dropzone", body)
            self.assertIn("data-listing-image-input", body)
            self.assertIn("Kéo và thả ảnh vào đây", body)
        finally:
            response.close()

    def test_edit_listing_removes_selected_images_and_preserves_shared_files(self):
        with app.app_context():
            listing = Listing(
                owner_id=self.lender_id,
                title="Editable listing",
                description="Before",
                category=CATEGORIES[0],
                district=DISTRICTS[0],
                price_per_day=100,
                deposit_amount=0,
            )
            db.session.add(listing)
            db.session.flush()
            removed_image = ListingImage(
                listing_id=listing.id, image_url="uploads/remove-me.jpg"
            )
            shared_image = ListingImage(
                listing_id=listing.id, image_url="uploads/shared.jpg"
            )
            kept_image = ListingImage(
                listing_id=listing.id, image_url="uploads/keep.jpg"
            )
            db.session.add_all(
                [
                    removed_image,
                    shared_image,
                    kept_image,
                    ListingImage(
                        listing_id=self.listing_id,
                        image_url="uploads/shared.jpg",
                    ),
                ]
            )
            db.session.commit()
            listing_id = listing.id
            removed_id = removed_image.id
            shared_id = shared_image.id

            form = MultiDict(
                [
                    ("title", "Updated listing"),
                    ("description", "After"),
                    ("category", CATEGORIES[0]),
                    ("district", DISTRICTS[0]),
                    ("price_per_day", "200"),
                    ("deposit_amount", "25"),
                    ("remove_image_ids", str(removed_id)),
                    ("remove_image_ids", str(shared_id)),
                ]
            )
            files = FileMultiDict()
            files.add_file(
                "images",
                FileStorage(
                    stream=BytesIO(b"new image"),
                    filename="new.jpg",
                    content_type="image/jpeg",
                ),
            )

            with patch(
                "services.listing_service.save_listing_image",
                return_value="https://images.example/new.jpg",
            ), patch(
                "services.listing_service.delete_listing_image",
                return_value=True,
            ) as delete_image:
                updated, cleanup_complete = listing_service.update_listing(
                    db.session.get(Listing, listing_id),
                    self.lender_id,
                    form,
                    files,
                    str(self.upload_root),
                )

            self.assertTrue(cleanup_complete)
            self.assertEqual(updated.title, "Updated listing")
            self.assertEqual(
                {image.image_url for image in updated.images},
                {"uploads/keep.jpg", "https://images.example/new.jpg"},
            )
            delete_image.assert_called_once_with("uploads/remove-me.jpg")

    def test_admin_dashboard_uses_authorized_evidence_route(self):
        self._login_as(self.admin_id)
        response = self.client.get("/admin")
        try:
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn('href="/"', body)
            self.assertIn('aria-label="UniRent - Về trang chủ"', body)
            self.assertIn(
                f"/don-hang/{self.booking_id}/evidence/{self.evidence_id}",
                body,
            )
            self.assertNotIn("/static/uploads/evidence.jpg", body)
            self.assertIn(f"/admin/kyc/{self.renter_id}", body)
        finally:
            response.close()

    def test_admin_kyc_detail_requires_admin_and_uses_private_image_route(self):
        url = f"/admin/kyc/{self.renter_id}"
        self.assertEqual(self._get_status(url), 302)

        self._login_as(self.outsider_id)
        self.assertEqual(self._get_status(url), 403)

        self._login_as(self.admin_id)
        response = self.client.get(url)
        try:
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(f"/admin/kyc/{self.renter_id}/image", body)
            self.assertNotIn("/static/uploads/kyc.jpg", body)
            self.assertIn('name="decision" value="approve"', body)
            self.assertIn('name="decision" value="reject"', body)
        finally:
            response.close()

    def test_owner_can_delete_listing_without_bookings_and_cleans_local_image(self):
        image_key = "uploads/delete-me.jpg"
        image_path = self._write_upload(self.upload_root, "delete-me.jpg")
        with app.app_context():
            listing = Listing(
                owner_id=self.lender_id,
                title="Listing to delete",
                price_per_day=100,
                status="AVAILABLE",
            )
            db.session.add(listing)
            db.session.flush()
            image = ListingImage(listing_id=listing.id, image_url=image_key)
            db.session.add(image)
            db.session.commit()
            listing_id = listing.id

        self._login_as(self.lender_id)
        page = self.client.get("/tin-cua-toi")
        self.assertIn(f"/san-pham/{listing_id}/xoa", page.get_data(as_text=True))
        page.close()

        response = self.client.post(
            f"/san-pham/{listing_id}/xoa",
            data={"csrf_token": "test-csrf-token"},
            follow_redirects=True,
        )
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("Đã xóa tin đăng.", response.get_data(as_text=True))
        finally:
            response.close()

        with app.app_context():
            self.assertIsNone(db.session.get(Listing, listing_id))
            self.assertIsNone(
                ListingImage.query.filter_by(image_url=image_key).first()
            )
        self.assertFalse(image_path.exists())

    def test_listing_with_booking_cannot_be_deleted(self):
        self._login_as(self.lender_id)
        response = self.client.post(
            f"/san-pham/{self.listing_id}/xoa",
            data={"csrf_token": "test-csrf-token"},
            follow_redirects=True,
        )
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("Không thể xóa tin đã có đơn thuê.", response.get_data(as_text=True))
        finally:
            response.close()

        with app.app_context():
            self.assertIsNotNone(db.session.get(Listing, self.listing_id))

    def test_non_owner_cannot_delete_listing(self):
        self._login_as(self.outsider_id)
        response = self.client.post(
            f"/san-pham/{self.listing_id}/xoa",
            data={"csrf_token": "test-csrf-token"},
        )
        try:
            self.assertEqual(response.status_code, 404)
        finally:
            response.close()

        with app.app_context():
            self.assertIsNotNone(db.session.get(Listing, self.listing_id))

    def test_deleting_listing_removes_its_cloudinary_image(self):
        image_url = (
            "https://res.cloudinary.com/demo/image/upload/v123/"
            "rental-management/listings/example-image.jpg"
        )
        with app.app_context():
            listing = Listing(
                owner_id=self.lender_id,
                title="Cloud image listing",
                price_per_day=100,
                status="AVAILABLE",
            )
            db.session.add(listing)
            db.session.flush()
            db.session.add(
                ListingImage(listing_id=listing.id, image_url=image_url)
            )
            listing_id = listing.id
            db.session.commit()

        with patch(
            "services.upload_service.cloudinary.uploader.destroy",
            return_value={"result": "ok"},
        ) as destroy:
            self._login_as(self.lender_id)
            response = self.client.post(
                f"/san-pham/{listing_id}/xoa",
                data={"csrf_token": "test-csrf-token"},
            )
            try:
                self.assertEqual(response.status_code, 302)
            finally:
                response.close()

        destroy.assert_called_once_with(
            "rental-management/listings/example-image",
            resource_type="image",
            type="upload",
            invalidate=True,
        )

    def test_kyc_upload_uses_private_folder_and_keeps_logical_key(self):
        self._login_as(self.renter_id)
        with self.client.session_transaction() as session:
            session["pending_otp"] = "1234"

        response = self.client.post(
            "/xac-minh",
            data={
                "csrf_token": "test-csrf-token",
                "otp": "1234",
                "kyc_card": (BytesIO(b"synthetic-kyc"), "student-card.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)

        with app.app_context():
            user = db.session.get(User, self.renter_id)
            self.assertTrue(user.kyc_card_image.startswith("uploads/"))
            key = user.kyc_card_image
        filename = key.removeprefix("uploads/")
        self.assertTrue((self.private_root / filename).is_file())
        self.assertFalse((self.upload_root / filename).exists())
        self.assertEqual(self._get_status(f"/static/{key}"), 404)

        self._login_as(self.admin_id)
        response = self.client.get(f"/admin/kyc/{self.renter_id}/image")
        try:
            self.assertEqual(response.status_code, 200)
        finally:
            response.close()

    def test_checkin_uploads_evidence_outside_static_and_keeps_listing_public(self):
        self._login_as(self.renter_id)
        media_files = [
            (BytesIO(f"synthetic-{index}".encode()), f"evidence-{index}.jpg")
            for index in range(4)
        ]
        response = self.client.post(
            f"/don-hang/{self.booking_id}/checkin",
            data={
                "csrf_token": "test-csrf-token",
                "note": "Synthetic handover",
                "media": media_files,
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            new_evidence = HandoverEvidence.query.filter_by(
                booking_id=self.booking_id
            ).all()
            new_rows = [
                row for row in new_evidence if row.id != self.evidence_id
            ]
            self.assertEqual(len(new_rows), 4)
            keys = [row.media_url for row in new_rows]
        for key in keys:
            filename = key.removeprefix("uploads/")
            self.assertTrue((self.private_root / filename).is_file())
            self.assertFalse((self.upload_root / filename).exists())
            self.assertEqual(self._get_status(f"/static/{key}"), 404)

        self._write_upload(self.upload_root, "listing.jpg")
        self.assertEqual(self._get_status("/static/uploads/listing.jpg"), 200)

    def test_checkout_uploads_evidence_outside_static(self):
        with app.app_context():
            booking = db.session.get(Booking, self.booking_id)
            booking.status = "IN_USE"
            db.session.commit()

        self._login_as(self.renter_id)
        media_files = [
            (BytesIO(f"synthetic-checkout-{index}".encode()), f"return-{index}.jpg")
            for index in range(4)
        ]
        response = self.client.post(
            f"/don-hang/{self.booking_id}/checkout",
            data={
                "csrf_token": "test-csrf-token",
                "note": "Synthetic return",
                "media": media_files,
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        response.close()

        with app.app_context():
            rows = HandoverEvidence.query.filter_by(
                booking_id=self.booking_id,
                type="CHECK_OUT",
            ).all()
            self.assertEqual(len(rows), 4)
            keys = [row.media_url for row in rows]
        for key in keys:
            filename = key.removeprefix("uploads/")
            self.assertTrue((self.private_root / filename).is_file())
            self.assertFalse((self.upload_root / filename).exists())
            self.assertEqual(self._get_status(f"/static/{key}"), 404)


if __name__ == "__main__":
    unittest.main()
