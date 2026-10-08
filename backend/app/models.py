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
    mpesa_number = db.Column(db.String(20))             # where customers send deposits (providers); falls back to phone
    notify_email = db.Column(db.Boolean, default=True)  # send email alerts
    notify_sms = db.Column(db.Boolean, default=True)    # send SMS alerts
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")
    location = db.Column(db.String(120))
    profile_image = db.Column(db.String(255), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)   # provider verification (the badge customers see)
    verification_status = db.Column(db.String(10), default="none")   # none -> pending -> approved / rejected
    verification_note = db.Column(db.String(255))                    # reason shown to the provider when rejected
    verification_report = db.Column(db.Text)                         # what the AI check found (shown to admins only)
    verification_submitted_at = db.Column(db.DateTime)
    id_number = db.Column(db.String(20))                 # national ID / passport number (private: admin only)
    id_photo = db.Column(db.String(255))                 # private file, never served from /uploads
    selfie_photo = db.Column(db.String(255))             # private file
    is_active_account = db.Column(db.Boolean, default=True)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    listings = db.relationship("SkillListing", backref="provider", lazy=True,
                                foreign_keys="SkillListing.provider_id",
                                cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="user", lazy=True,
                                     cascade="all, delete-orphan")
    portfolio = db.relationship("PortfolioPhoto", backref="provider", lazy=True,
                                 cascade="all, delete-orphan", order_by="PortfolioPhoto.id.desc()")

    @property
    def verified_jobs(self):
        """Jobs finished with photo proof, confirmed by the customer and paid in full through the app."""
        return Booking.query.filter(Booking.provider_id == self.id, Booking.status == "completed", Booking.balance_status == "confirmed",
                                    Booking.customer_confirmed_at.isnot(None), Booking.photos.any()).count()

    @property
    def payment_number(self):
        return self.mpesa_number or self.phone

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
    service_mode = db.Column(db.String(10), default="both")   # shop = customer comes to provider, visit = provider goes to customer, both
    shop_address = db.Column(db.String(255))                  # required when service_mode is shop or both
    deposit_percent = db.Column(db.Integer, default=30)       # paid before work starts; the rest is paid after delivery
    image = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bookings = db.relationship("Booking", backref="listing", lazy=True,
                                cascade="all, delete-orphan")

    @property
    def offers_shop(self):    # customer comes to the provider's shop
        return self.service_mode in ("shop", "both") and bool(self.shop_address)

    @property
    def offers_visit(self):   # provider goes to the customer (door to door)
        return self.service_mode in ("visit", "both")

    @property
    def deposit_pct(self):
        return self.deposit_percent if self.deposit_percent is not None else 30

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
            "service_mode": self.service_mode,
            "deposit_percent": self.deposit_percent,
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
    work_place = db.Column(db.String(10), default="customer")   # shop = at provider's shop, customer = at customer's place
    customer_phone = db.Column(db.String(20))
    customer_address = db.Column(db.String(255))                # where to come (only when work_place == customer)
    agreed_price = db.Column(db.Float)                          # price copied from the listing when booked
    deposit_amount = db.Column(db.Float, default=0.0)
    deposit_status = db.Column(db.String(10), default="none")   # none -> awaiting -> claimed -> confirmed
    deposit_code = db.Column(db.String(20))                     # M-Pesa transaction code entered by the customer
    balance_status = db.Column(db.String(10), default="none")   # none -> unpaid -> claimed -> confirmed
    balance_code = db.Column(db.String(20))
    proof_note = db.Column(db.String(255))                      # provider's note with the finished-work photos
    completed_at = db.Column(db.DateTime)                       # when the provider marked the work done
    customer_confirmed_at = db.Column(db.DateTime)              # when the customer confirmed (button, or by paying the balance)
    payout_status = db.Column(db.String(10), default="none")    # none -> due -> paid (only for money held by the platform via STK Push)
    payout_amount = db.Column(db.Float, default=0.0)
    payout_ref = db.Column(db.String(40))                       # M-Pesa reference of the payout to the provider
    payout_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship("Message", backref="booking", lazy=True, cascade="all, delete-orphan", order_by="Message.id")
    customer = db.relationship("User", foreign_keys=[customer_id])
    provider = db.relationship("User", foreign_keys=[provider_id])
    review = db.relationship("Review", backref="booking", uselist=False,
                              cascade="all, delete-orphan")
    payments = db.relationship("Payment", backref="booking", lazy=True, cascade="all, delete-orphan", order_by="Payment.id")
    photos = db.relationship("BookingPhoto", backref="booking", lazy=True, cascade="all, delete-orphan", order_by="BookingPhoto.id")

    @property
    def balance_amount(self):
        return round((self.agreed_price or 0) - (self.deposit_amount or 0), 2)

    @property
    def contacts_visible(self):
        """Phone numbers and addresses are shared only once the provider has accepted."""
        return self.status in ("accepted", "completed")

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
    link = db.Column(db.String(200))
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


class Message(db.Model):
    """One chat message inside a booking. Kept permanently so admins can review disputes."""
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id])


class Payment(db.Model):
    """One M-Pesa STK Push request (deposit or balance). Money lands on the platform's shortcode and is held until payout."""
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)             # deposit / balance
    amount = db.Column(db.Integer, nullable=False)              # whole shillings
    phone = db.Column(db.String(15), nullable=False)            # 2547XXXXXXXX
    checkout_request_id = db.Column(db.String(80), unique=True, index=True)
    merchant_request_id = db.Column(db.String(80))
    status = db.Column(db.String(10), default="pending")        # pending -> success / failed
    mpesa_receipt = db.Column(db.String(20), unique=True)       # e.g. QGH7K2L9MN, set on success
    result_desc = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PortfolioPhoto(db.Model):
    """Photos of finished work shown on a provider's public profile."""
    __tablename__ = "portfolio_photos"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BookingPhoto(db.Model):
    """Photo of the finished work, uploaded by the provider when marking a booking completed."""
    __tablename__ = "booking_photos"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
