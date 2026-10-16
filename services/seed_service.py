"""Load local demo fixtures from data/seed_data.json into the database."""
import json
from pathlib import Path

from werkzeug.security import generate_password_hash

from models import Listing, ListingImage, User, db

SEED_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "seed_data.json"


def _load_seed_data():
    with SEED_DATA_PATH.open(encoding="utf-8") as seed_file:
        return json.load(seed_file)


def seed_base_data():
    """Create the starter demo accounts and listing if they are missing."""
    if User.query.filter_by(school_email="admin@neu.edu.vn").first():
        print("Already seeded.")
        return

    seed_data = _load_seed_data()
    users_by_email = {}
    for account in seed_data["initial_accounts"]:
        user = User(
            full_name=account["full_name"],
            school_email=account["school_email"],
            phone_number=account["phone_number"],
            password_hash=generate_password_hash(account["seed_password"]),
            email_verified=account.get("email_verified", True),
            phone_verified=account.get("phone_verified", True),
            kyc_status=account.get("kyc_status", "APPROVED"),
            is_admin=account.get("is_admin", False),
            district=account.get("district"),
        )
        db.session.add(user)
        users_by_email[user.school_email] = user
    db.session.flush()

    for listing_data in seed_data["initial_listings"]:
        listing = Listing(
            owner_id=users_by_email[listing_data["owner_email"]].id,
            title=listing_data["title"],
            description=listing_data["description"],
            category=listing_data["category"],
            district=listing_data["district"],
            price_per_day=listing_data["price_per_day"],
            deposit_amount=listing_data["deposit_amount"],
        )
        db.session.add(listing)

    db.session.commit()
    print("Seeded the initial demo accounts and listing.")


def seed_demo_data():
    """Add repeatable demo accounts and listings without replacing user data."""
    seed_data = _load_seed_data()
    owners = []

    for account in seed_data["demo_accounts"]:
        owner = User.query.filter_by(school_email=account["school_email"]).first()
        if owner is None:
            owner = User.query.filter_by(phone_number=account["phone_number"]).first()
        if owner is None:
            owner = User(
                full_name=account["full_name"],
                school_email=account["school_email"],
                phone_number=account["phone_number"],
                password_hash=generate_password_hash(account["seed_password"]),
                email_verified=True,
                phone_verified=True,
                kyc_status="APPROVED",
                trust_score=100,
                district=account["district"],
            )
            db.session.add(owner)
            db.session.flush()
        owners.append(owner)

    added = 0
    for index, listing_data in enumerate(seed_data["demo_listings"]):
        if Listing.query.filter_by(title=listing_data["title"]).first():
            continue

        listing = Listing(
            owner_id=owners[index % len(owners)].id,
            title=listing_data["title"],
            description=listing_data["description"],
            category=listing_data["category"],
            district=listing_data["district"],
            price_per_day=listing_data["price_per_day"],
            deposit_amount=listing_data["deposit_amount"],
            status="AVAILABLE",
        )
        db.session.add(listing)
        db.session.flush()
        db.session.add(ListingImage(
            listing_id=listing.id,
            image_url=f"demo/{listing_data['image_key']}.svg",
        ))
        added += 1

    db.session.commit()
    print(f"Added {added} sample listing(s); existing listings and accounts were kept.")
