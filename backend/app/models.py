from datetime import datetime, timedelta
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

ROLES = ["customer", "provider", "admin"]
BOOKING_STATUSES = ["pending", "accepted", "rejected", "completed", "cancelled"]


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")
    location = db.Column(db.String(120))
    profile_image = db.Column(db.String(255), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)   # provider verification
    is_active_account = db.Column(db.Boolean, default=True)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    listings = db.relationship("SkillListing", backref="provider", lazy=True,
                                foreign_keys="SkillListing.provider_id",
                                cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="user", lazy=True,
                                     cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_locked(self):
        return self.locked_until is not None and self.locked_until > datetime.utcnow()

    def register_failed_login(self, max_attempts, lockout_minutes):
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.utcnow() + timedelta(minutes=lockout_minutes)

    def register_successful_login(self):
        self.failed_login_attempts = 0
        self.locked_until = None

    @property
    def is_active(self):
        return self.is_active_account

    @property
    def average_rating(self):
        reviews = Review.query.filter_by(provider_id=self.id).all()
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    @property
    def review_count(self):
        return Review.query.filter_by(provider_id=self.id).count()

    def to_public_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "role": self.role,
            "location": self.location,
            "profile_image": self.profile_image,
            "is_verified": self.is_verified,
            "average_rating": self.average_rating,
            "review_count": self.review_count,
            "created_at": self.created_at.isoformat(),
        }

    def to_private_dict(self):
        d = self.to_public_dict()
        d.update({"email": self.email, "phone": self.phone, "is_active": self.is_active_account})
        return d


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    listings = db.relationship("SkillListing", backref="category", lazy=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "description": self.description}


class SkillListing(db.Model):
    __tablename__ = "skill_listings"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(120))
    price = db.Column(db.Float, nullable=False, default=0.0)
    price_unit = db.Column(db.String(30), default="per job")   # e.g. per job, per item, per hour
    availability = db.Column(db.String(120))   # free-text, e.g. "Weekdays, 8am-5pm"
    image = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bookings = db.relationship("Booking", backref="listing", lazy=True,
                                cascade="all, delete-orphan")

    def to_dict(self, include_provider=True):
        d = {
            "id": self.id,
            "provider_id": self.provider_id,
            "category_id": self.category_id,
            "category": self.category.name if self.category else None,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "price": self.price,
            "price_unit": self.price_unit,
            "availability": self.availability,
            "image": self.image,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }
        if include_provider and self.provider:
            d["provider"] = {
                "id": self.provider.id,
                "full_name": self.provider.full_name,
                "is_verified": self.provider.is_verified,
                "average_rating": self.provider.average_rating,
                "profile_image": self.provider.profile_image,
            }
        return d


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey("skill_listings.id"), nullable=False)
    message = db.Column(db.Text)
    requested_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship("User", foreign_keys=[customer_id])
    provider = db.relationship("User", foreign_keys=[provider_id])
    review = db.relationship("Review", backref="booking", uselist=False,
                              cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "customer_name": self.customer.full_name if self.customer else None,
            "provider_id": self.provider_id,
            "provider_name": self.provider.full_name if self.provider else None,
            "listing_id": self.listing_id,
            "listing_title": self.listing.title if self.listing else None,
            "message": self.message,
            "requested_date": self.requested_date.isoformat() if self.requested_date else None,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "has_review": self.review is not None,
        }


class Review(db.Model):
    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship("User", foreign_keys=[customer_id])

    __table_args__ = (
        db.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "booking_id": self.booking_id,
            "customer_id": self.customer_id,
            "customer_name": self.customer.full_name if self.customer else None,
            "provider_id": self.provider_id,
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at.isoformat(),
        }


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat(),
        }
