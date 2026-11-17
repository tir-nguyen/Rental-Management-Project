import os
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite://"

from app import app
from models import (
    Booking, Dispute, HandoverEvidence, Listing, ListingImage, Message, User, db,
)


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

    def test_admin_dashboard_uses_authorized_evidence_route(self):
        self._login_as(self.admin_id)
        response = self.client.get("/admin")
        try:
            body = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
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
