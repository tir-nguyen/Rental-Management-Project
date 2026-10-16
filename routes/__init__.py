"""Register route groups while keeping their public endpoint names stable."""
from .admin_routes import register_routes as register_admin_routes
from .auth_routes import register_routes as register_auth_routes
from .booking_routes import register_routes as register_booking_routes
from .listing_routes import register_routes as register_listing_routes


def register_routes(app):
    register_auth_routes(app)
    register_listing_routes(app)
    register_booking_routes(app)
    register_admin_routes(app)
