"""
Database initialisation for Remote Skills Exchange.

Creates the schema and loads starting data: skill categories, an
administrator account, sample provider and customer accounts, sample
skill listings, and a couple of bookings taken through to completion
with a review — so the full workflow has something to look at
immediately after setup.

Run once before starting the application for the first time:
    python seed.py
Re-running is safe — initialisation is skipped if data already exists.

DEVELOPMENT-ONLY CREDENTIALS. Do not use these in any real deployment;
change every password after first sign-in.
"""
import os
from datetime import date, timedelta
from app import create_app
from app.extensions import db
from app.models import Message, User, Category, SkillListing, Booking, Review

app = create_app()


def run():
    with app.app_context():
        db.create_all()

        ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
        ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or ("Admin@12345" if os.environ.get("FLASK_ENV") != "production" else None)
        if not ADMIN_PASSWORD:
            raise SystemExit("Set ADMIN_PASSWORD to create the administrator in production.")
        if User.query.filter_by(email=ADMIN_EMAIL).first():
            print("Database already initialised — no changes made.")
            return

        print("Initialising database...")

        # --- Categories ---
        category_names = [
            "Electrical", "Tailoring", "Phone Repair", "Laptop Repair",
            "Plumbing", "Tutoring", "Hairdressing", "Graphic Design",
            "Web Design", "Photography", "Computer Networking", "Other",
        ]
        categories = {}
        for name in category_names:
            c = Category(name=name, description=f"{name} services")
            db.session.add(c)
            categories[name] = c
        db.session.flush()

        # --- Admin ---
        admin = User(full_name="Platform Administrator", email=ADMIN_EMAIL,
                     phone="0700000001", role="admin", location="Nairobi")
        admin.set_password(ADMIN_PASSWORD)
        db.session.add(admin)

        if os.environ.get("SEED_DEMO", "1") == "0":
            db.session.commit()
            print("Categories and administrator created (no demo data).")
            return

        # --- Providers ---
        provider_defs = [
            ("James Otieno", "provider1@example.com", "Nairobi", True),
            ("Susan Wambui", "provider2@example.com", "Nakuru", True),
            ("David Kiprotich", "provider3@example.com", "Eldoret", False),
        ]
        providers = []
        for name, email, loc, verified in provider_defs:
            p = User(full_name=name, email=email, phone="0711000000", role="provider",
                     location=loc, is_verified=verified or os.environ.get("REQUIRE_VERIFICATION", "1") == "1",
                     verification_status="approved" if (verified or os.environ.get("REQUIRE_VERIFICATION", "1") == "1") else "none")
            p.set_password("Provider@123")
            db.session.add(p)
            providers.append(p)
        db.session.flush()

        # --- Customers ---
        customer_defs = [
            ("Alice Njoki", "customer1@example.com", "Nairobi"),
            ("Brian Mwangi", "customer2@example.com", "Nakuru"),
            ("Cynthia Achieng", "customer3@example.com", "Kisumu"),
            ("Dennis Kiptoo", "customer4@example.com", "Eldoret"),
            ("Esther Wanjiru", "customer5@example.com", "Nairobi"),
        ]
        customers = []
        for name, email, loc in customer_defs:
            cu = User(full_name=name, email=email, phone="0722000000", role="customer", location=loc)
            cu.set_password("Customer@123")
            db.session.add(cu)
            customers.append(cu)
        db.session.flush()

        # --- Listings ---
        listing_defs = [
            (providers[0], "Electrical", "Home & Office Electrical Wiring", 2500,
             "Nairobi", "Weekdays, 8am - 5pm"),
            (providers[0], "Computer Networking", "LAN Setup & Wi-Fi Troubleshooting", 3000,
             "Nairobi", "By appointment"),
            (providers[1], "Tailoring", "Custom Dress & Suit Tailoring", 1800,
             "Nakuru", "Mon - Sat"),
            (providers[1], "Hairdressing", "Braiding, Weaving & Styling", 1200,
             "Nakuru", "Tue - Sun"),
            (providers[2], "Phone Repair", "Screen & Battery Replacement (All Brands)", 1500,
             "Eldoret", "Daily, 9am - 6pm"),
            (providers[2], "Laptop Repair", "Laptop Hardware & Software Repair", 2000,
             "Eldoret", "Daily, 9am - 6pm"),
            (providers[0], "Plumbing", "Pipe Fitting & Leak Repairs", 2200,
             "Nairobi", "Weekends"),
            (providers[1], "Graphic Design", "Logo, Poster & Branding Design", 3500,
             "Nakuru", "Remote, flexible"),
        ]
        listings = []
        for provider, cat_name, title, price, loc, avail in listing_defs:
            listing = SkillListing(
                provider_id=provider.id, category_id=categories[cat_name].id,
                title=title, description=f"Professional {title.lower()} service. "
                                          f"Reliable, affordable, and available {avail.lower()}.",
                location=loc, price=price, availability=avail,
                service_mode=("both" if cat_name in ("Tailoring", "Phone Repair", "Laptop Repair") else "visit"),
                shop_address=(f"{loc} town centre, Shop 12" if cat_name in ("Tailoring", "Phone Repair", "Laptop Repair") else None),
                deposit_percent=30,
                price_unit={"Tailoring": "per item", "Phone Repair": "per repair", "Laptop Repair": "per repair", "Hairdressing": "per style"}.get(cat_name, "per job"),
            )
            db.session.add(listing)
            listings.append(listing)
        db.session.flush()

        # --- Sample booking workflow, taken through to completion + review ---
        completed_booking = Booking(
            customer_id=customers[0].id, provider_id=providers[0].id, listing_id=listings[0].id,
            message="Need rewiring for a 3-bedroom house.",
            requested_date=date.today() - timedelta(days=10), status="completed",
            work_place="customer", customer_phone="+254700000001", customer_address="Milimani Estate, House 14, Nairobi",
            agreed_price=listings[0].price, deposit_amount=round(listings[0].price * 0.3, 2), deposit_status="confirmed", deposit_code="DEMOCODE01",
            balance_status="confirmed", balance_code="DEMOCODE02",
        )
        db.session.add(completed_booking)
        db.session.flush()

        db.session.add(Review(
            booking_id=completed_booking.id, customer_id=customers[0].id,
            provider_id=providers[0].id, rating=5,
            comment="Excellent work, arrived on time and cleaned up afterwards.",
        ))

        db.session.add(Booking(
            customer_id=customers[1].id, provider_id=providers[1].id, listing_id=listings[2].id,
            message="I need a suit tailored for a wedding.",
            requested_date=date.today() + timedelta(days=5), status="pending",
            work_place="shop", customer_phone="+254700000002", agreed_price=listings[2].price, deposit_amount=round(listings[2].price * 0.3, 2),
        ))
        db.session.add(Booking(
            customer_id=customers[2].id, provider_id=providers[2].id, listing_id=listings[4].id,
            message="Cracked screen on an iPhone 12.",
            requested_date=date.today() + timedelta(days=2), status="accepted",
            work_place="shop", customer_phone="+254700000003", agreed_price=listings[4].price, deposit_amount=round(listings[4].price * 0.3, 2),
            deposit_status="awaiting",
        ))

        db.session.commit()

        print("Database initialised successfully.\n")
        print("DEVELOPMENT-ONLY credentials — change these before any real use:")
        print(f"  Admin       {ADMIN_EMAIL}   (password from ADMIN_PASSWORD or the dev default)")
        print("  Provider    provider1@example.com   Provider@123  (verified)")
        print("  Provider    provider2@example.com   Provider@123  (verified)")
        print("  Provider    provider3@example.com   Provider@123  (not yet verified)")
        print("  Customer    customer1@example.com   Customer@123")
        print("  Customer    customer2@example.com   Customer@123")
        print("  Customer    customer3@example.com   Customer@123")
        print("  Customer    customer4@example.com   Customer@123")
        print("  Customer    customer5@example.com   Customer@123")


if __name__ == "__main__":
    run()
