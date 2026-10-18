import os
import tempfile
import unittest
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from flask import Flask
from flask_login import LoginManager

from models import Booking, Listing, PaymentAttempt, Transaction, User, db
from routes import register_blueprints
from services import payment_service


class PaymentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates"))
        self.app = Flask(__name__, template_folder=template_dir)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(self.temp_dir.name, 'test.db')}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            VNPAY_TMN_CODE="TESTCODE",
            VNPAY_HASH_SECRET="test-hash-secret",
            VNPAY_PAYMENT_URL="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        )
        db.init_app(self.app)
        self.login_manager = LoginManager()
        self.login_manager.init_app(self.app)
        self.login_manager.user_loader(lambda user_id: db.session.get(User, int(user_id)))
        register_blueprints(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()

        renter = User(
            full_name="Test Renter",
            school_email="renter@example.test",
            phone_number="0900000001",
            password_hash="unused",
        )
        lender = User(
            full_name="Test Lender",
            school_email="lender@example.test",
            phone_number="0900000002",
            password_hash="unused",
        )
        db.session.add_all([renter, lender])
        db.session.flush()
        listing = Listing(
            owner_id=lender.id,
            title="Test listing",
            price_per_day=10000,
            deposit_amount=50000,
        )
        db.session.add(listing)
        db.session.flush()
        self.booking = Booking(
            listing_id=listing.id,
            renter_id=renter.id,
            lender_id=lender.id,
            start_date=datetime.utcnow().date(),
            end_date=datetime.utcnow().date(),
            status="APPROVED",
            total_rent_amount=30000,
            deposit_amount=50000,
            approved_at=datetime.utcnow(),
        )
        db.session.add(self.booking)
        db.session.commit()
        self.renter = renter
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(renter.id)
            session["_fresh"] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        self.temp_dir.cleanup()

    def _create_payment(self):
        url = payment_service.create_payment_url(
            self.booking, self.renter, "127.0.0.1",
            "http://127.0.0.1:5000/thanh-toan/vnpay/return",
        )
        return url, PaymentAttempt.query.filter_by(booking_id=self.booking.id).one()

    def _callback(self, attempt, **overrides):
        params = {
            "vnp_TmnCode": "TESTCODE",
            "vnp_TxnRef": attempt.txn_ref,
            "vnp_Amount": str(attempt.amount * 100),
            "vnp_ResponseCode": "00",
            "vnp_TransactionStatus": "00",
            "vnp_TransactionNo": "12345678",
        }
        params.update(overrides)
        params["vnp_SecureHash"] = payment_service.sign_vnpay_params(
            params, self.app.config["VNPAY_HASH_SECRET"]
        )
        return params

    def test_payment_url_uses_vnd_minor_units_and_signed_parameters(self):
        url, attempt = self._create_payment()
        params = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}

        self.assertEqual(urlparse(url).scheme, "https")
        self.assertEqual(params["vnp_Amount"], "8000000")
        self.assertEqual(params["vnp_TxnRef"], attempt.txn_ref)
        self.assertEqual(
            params["vnp_SecureHash"],
            payment_service.sign_vnpay_params(params, self.app.config["VNPAY_HASH_SECRET"]),
        )
        self.assertEqual(attempt.status, "PENDING")

    def test_verified_return_does_not_mark_payment_success(self):
        _, attempt = self._create_payment()
        result = payment_service.get_verified_return(self._callback(attempt))

        self.assertEqual(result.id, attempt.id)
        self.assertEqual(attempt.status, "PENDING")
        self.assertEqual(self.booking.status, "APPROVED")
        self.assertEqual(Transaction.query.count(), 0)

    def test_valid_ipn_confirms_payment_once(self):
        _, attempt = self._create_payment()
        params = self._callback(attempt)

        self.assertEqual(payment_service.process_ipn(params), ("00", "Confirm Success"))
        db.session.refresh(attempt)
        db.session.refresh(self.booking)
        self.assertEqual(attempt.status, "SUCCESS")
        self.assertEqual(self.booking.status, "READY_FOR_PICKUP")
        self.assertEqual(Transaction.query.filter_by(type="VNPAY_PAYMENT").count(), 1)
        self.assertEqual(payment_service.process_ipn(params), ("02", "Order already confirmed"))
        self.assertEqual(Transaction.query.filter_by(type="VNPAY_PAYMENT").count(), 1)

    def test_invalid_signature_does_not_change_booking(self):
        _, attempt = self._create_payment()
        params = self._callback(attempt)
        params["vnp_Amount"] = "1"

        self.assertEqual(payment_service.process_ipn(params)[0], "97")
        db.session.refresh(attempt)
        self.assertEqual(attempt.status, "PENDING")
        self.assertEqual(self.booking.status, "APPROVED")
        self.assertEqual(Transaction.query.count(), 0)

    def test_signed_amount_mismatch_is_rejected(self):
        _, attempt = self._create_payment()
        params = self._callback(attempt, vnp_Amount="1")

        self.assertEqual(payment_service.process_ipn(params), ("04", "Invalid amount"))
        db.session.refresh(attempt)
        self.assertEqual(attempt.status, "PENDING")
        self.assertEqual(Transaction.query.count(), 0)

    def test_signed_failed_payment_does_not_unlock_booking(self):
        _, attempt = self._create_payment()
        params = self._callback(
            attempt, vnp_ResponseCode="24", vnp_TransactionStatus="02"
        )

        self.assertEqual(payment_service.process_ipn(params), ("00", "Confirm Success"))
        db.session.refresh(attempt)
        self.assertEqual(attempt.status, "FAILED")
        self.assertEqual(self.booking.status, "APPROVED")
        self.assertEqual(Transaction.query.count(), 0)

    def test_late_success_is_recorded_for_manual_review(self):
        _, attempt = self._create_payment()
        self.booking.status = "CANCELLED"
        db.session.commit()

        self.assertEqual(
            payment_service.process_ipn(self._callback(attempt)),
            ("00", "Confirm Success"),
        )
        db.session.refresh(attempt)
        self.assertEqual(attempt.status, "PAID_REVIEW")
        self.assertEqual(self.booking.status, "CANCELLED")
        self.assertEqual(Transaction.query.filter_by(type="VNPAY_PAYMENT").count(), 1)

    def test_duplicate_query_parameters_are_rejected(self):
        _, attempt = self._create_payment()

        self.assertEqual(payment_service.process_ipn(self._callback(attempt), True)[0], "97")
        db.session.refresh(attempt)
        self.assertEqual(attempt.status, "PENDING")

    def test_payment_route_redirects_to_vnpay_without_confirming_booking(self):
        response = self.client.post(f"/don-hang/{self.booking.id}/dat-coc")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.startswith(
            "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html?"
        ))
        self.assertEqual(self.booking.status, "APPROVED")
        self.assertEqual(PaymentAttempt.query.count(), 1)

    def test_booking_detail_renders_pending_payment_state(self):
        self._create_payment()

        response = self.client.get(f"/don-hang/{self.booking.id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Đang chờ VNPay xác nhận", response.get_data(as_text=True))

    def test_ipn_route_returns_acknowledgement_and_updates_booking(self):
        _, attempt = self._create_payment()
        with self.client.session_transaction() as session:
            session.clear()
        response = self.client.get(
            "/thanh-toan/vnpay/ipn", query_string=self._callback(attempt)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "RspCode": "00", "Message": "Confirm Success"
        })
        self.assertIn("payments.vnpay_ipn", self.app.view_functions)
        db.session.refresh(self.booking)
        self.assertEqual(self.booking.status, "READY_FOR_PICKUP")


if __name__ == "__main__":
    unittest.main()
