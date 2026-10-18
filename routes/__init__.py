"""Application route blueprints."""
from .admin_routes import admin_bp
from .auth_routes import auth_bp
from .booking_routes import bookings_bp
from .listing_routes import listings_bp
from .payment_routes import payments_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)
