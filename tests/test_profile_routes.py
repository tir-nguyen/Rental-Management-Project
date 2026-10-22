import os
import tempfile
import unittest
from datetime import datetime, timedelta

from flask import Flask, abort, request, session
from flask_login import LoginManager

from models import Booking, Listing, Review, User, db
from routes import register_blueprints


class ProfileRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates"))
        self.app = Flask(__name__, template_folder=template_dir)
        self.app.config.update(
            TESTING=True,
            PROFILE_TEST_CSRF=True,
            SECRET_KEY="profile-test-secret",
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(self.temp_dir.name, 'profile.db')}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        login_manager = LoginManager()
        login_manager.login_view = "auth.login"
        login_manager.init_app(self.app)
        login_manager.user_loader(lambda user_id: db.session.get(User, int(user_id)))
        register_blueprints(self.app)

        @self.app.before_request
        def protect_profile_posts():
            if self.app.testing and self.app.config.get("PROFILE_TEST_CSRF"):
                if request.method == "POST":
                    token = session.get("_csrf_token")
                    submitted = request.form.get("csrf_token")
                    if not token or token != submitted:
                        abort(400)

        @self.app.context_processor
        def profile_shell_context():
            return {
                "csrf_token": "profile-test-csrf",
                "unread_notification_count": 0,
                "notification_preview": [],
            }

        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.owner = User(
            full_name="Profile Owner",
            school_email="owner@example.test",
            phone_number="0900000001",
            password_hash="unused",
            email_verified=True,
            phone_verified=True,
            kyc_status="APPROVED",
            kyc_card_image="uploads/private-card.jpg",
            district="Gia Lâm",
        )
        self.other_user = User(
            full_name="Other User",
            school_email="other@example.test",
            phone_number="0900000002",
            password_hash="unused",
        )
        db.session.add_all([self.owner, self.other_user])
        db.session.flush()
        self.public_listing = self._listing("Public camera", self.owner.id, "AVAILABLE")
        self.hidden_listing = self._listing("Private draft", self.owner.id, "HIDDEN")
        self.rented_listing = self._listing("Currently rented", self.owner.id, "RENTED")
        db.session.add_all([
            self.public_listing,
            self.hidden_listing,
            self.rented_listing,
        ])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        self.temp_dir.cleanup()

    def _listing(self, title, owner_id, status):
        return Listing(
            owner_id=owner_id,
            title=title,
            category="Máy ảnh & Thiết bị",
            district="Cầu Giấy",
            price_per_day=25000,
            deposit_amount=100000,
            status=status,
        )

    def _login_as(self, user):
        with self.client.session_transaction() as current_session:
            current_session["_user_id"] = str(user.id)
            current_session["_fresh"] = True
            current_session["_csrf_token"] = "profile-test-csrf"

    def test_public_profile_only_exposes_public_fields_and_listings(self):
        completed_booking = Booking(
            listing_id=self.public_listing.id,
            renter_id=self.other_user.id,
            lender_id=self.owner.id,
            start_date=datetime.utcnow().date(),
            end_date=(datetime.utcnow() + timedelta(days=1)).date(),
            status="COMPLETED",
            total_rent_amount=50000,
            deposit_amount=100000,
            approved_at=datetime.utcnow(),
        )
        db.session.add(completed_booking)
        db.session.flush()
        db.session.add(Review(
            booking_id=completed_booking.id,
            reviewer_id=self.other_user.id,
            reviewee_id=self.owner.id,
            rating=5,
            comment="Private review text is not part of profile statistics.",
        ))
        db.session.commit()

        response = self.client.get(f"/nguoi-dung/{self.owner.id}")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Profile Owner", body)
        self.assertIn("Đã xác minh", body)
        self.assertIn("5.0", body)
        self.assertIn("1 lượt", body)
        self.assertIn("Giao dịch hoàn tất", body)
        self.assertIn("Public camera", body)
        self.assertNotIn("Private draft", body)
        self.assertNotIn("Currently rented", body)
        self.assertNotIn(self.owner.school_email, body)
        self.assertNotIn(self.owner.phone_number, body)
        self.assertNotIn("private-card.jpg", body)
        self.assertNotIn("Gia Lâm", body)
        self.assertNotIn("Private review text", body)

    def test_missing_public_profile_returns_404(self):
        response = self.client.get("/nguoi-dung/99999")
        self.assertEqual(response.status_code, 404)

    def test_public_profile_with_no_listings_shows_empty_state(self):
        response = self.client.get(f"/nguoi-dung/{self.other_user.id}")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Other User", body)
        self.assertIn("Hiện chưa có món đồ nào đang được cho thuê.", body)

    def test_public_profile_paginates_available_listings(self):
        for number in range(13):
            db.session.add(self._listing(f"Public item {number}", self.owner.id, "AVAILABLE"))
        db.session.commit()

        first_page = self.client.get(f"/nguoi-dung/{self.owner.id}")
        second_page = self.client.get(f"/nguoi-dung/{self.owner.id}?page=2")
        first_page_body = first_page.get_data(as_text=True)
        second_page_body = second_page.get_data(as_text=True)

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(first_page_body.count('<a class="card"'), 12)
        self.assertEqual(second_page_body.count('<a class="card"'), 2)

    def test_self_profile_requires_login(self):
        response = self.client.get("/ho-so")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dang-nhap", response.location)

    def test_owner_can_view_private_contact_details(self):
        self._login_as(self.owner)
        response = self.client.get("/ho-so")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.owner.school_email, body)
        self.assertIn(self.owner.phone_number, body)
        self.assertIn("Đã xác minh", body)

    def test_owner_can_update_only_allowlisted_own_fields(self):
        self._login_as(self.owner)
        response = self.client.post(
            "/ho-so",
            data={
                "csrf_token": "profile-test-csrf",
                "full_name": "Updated Owner",
                "district": "Đống Đa",
                "user_id": str(self.other_user.id),
                "is_admin": "true",
                "trust_score": "9999",
                "kyc_status": "APPROVED",
            },
            follow_redirects=True,
        )

        db.session.refresh(self.owner)
        db.session.refresh(self.other_user)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Đã cập nhật hồ sơ của bạn.", response.get_data(as_text=True))
        self.assertEqual(self.owner.full_name, "Updated Owner")
        self.assertEqual(self.owner.district, "Đống Đa")
        self.assertEqual(self.owner.school_email, "owner@example.test")
        self.assertEqual(self.owner.phone_number, "0900000001")
        self.assertEqual(self.owner.trust_score, 100)
        self.assertEqual(self.owner.kyc_status, "APPROVED")
        self.assertFalse(self.owner.is_admin)
        self.assertEqual(self.other_user.full_name, "Other User")
        self.assertEqual(
            self.client.post(
                f"/ho-so/{self.other_user.id}",
                data={"csrf_token": "profile-test-csrf", "full_name": "Tampered"},
            ).status_code,
            404,
        )

    def test_update_requires_valid_csrf_token(self):
        self._login_as(self.owner)
        response = self.client.post(
            "/ho-so",
            data={"full_name": "No CSRF", "district": "Đống Đa"},
        )
        db.session.refresh(self.owner)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.owner.full_name, "Profile Owner")

    def test_invalid_update_keeps_submitted_values_and_does_not_change_user(self):
        self._login_as(self.owner)
        response = self.client.post(
            "/ho-so",
            data={
                "csrf_token": "profile-test-csrf",
                "full_name": "Name to keep visible",
                "district": "Not a supported district",
            },
        )
        body = response.get_data(as_text=True)

        db.session.refresh(self.owner)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Name to keep visible", body)
        self.assertIn("Khu vực hoạt động không hợp lệ.", body)
        self.assertEqual(self.owner.full_name, "Profile Owner")
        self.assertEqual(self.owner.district, "Gia Lâm")

    def test_listing_detail_links_to_public_owner_profile(self):
        response = self.client.get(f"/san-pham/{self.public_listing.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/nguoi-dung/{self.owner.id}", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
