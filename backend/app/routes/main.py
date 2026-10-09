from flask import Blueprint, render_template, request, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models import User, Category, SkillListing, Booking, Review

bp = Blueprint("main", __name__)

PAGES = {
    "about": ("About us", "Remote Skills Exchange connects customers with trusted local service providers who offer practical and professional skills. Providers list what they do, customers book, and reviews build reputation."),
    "contact": ("Contact us", "Questions or problems with a booking? Send a message from your account notifications, or reach the platform administrator at the support address configured for this deployment."),
    "help": ("Help Center", "Customers: search for a service, send a booking request, and leave a review once the job is completed. Providers: create your services, then accept or reject incoming requests and mark accepted jobs completed."),
    "terms": ("Terms of Service", "Use the platform honestly. Providers are responsible for the services they offer and customers for the information they submit. Administrators may suspend accounts that break these rules."),
    "privacy": ("Privacy Policy", "We store only what is needed to run your account and bookings. Passwords are stored as salted hashes and are never visible to staff."),
}


def _active_listings():
    qy = (db.session.query(SkillListing).join(User, SkillListing.provider_id == User.id)
          .filter(SkillListing.is_active.is_(True), User.is_active_account.is_(True)))
    if current_app.config["REQUIRE_VERIFICATION"]: qy = qy.filter(User.is_verified.is_(True))   # only verified providers are public
    return qy


@bp.route("/")
def home():
    cats = db.session.query(Category, func.count(SkillListing.id)).outerjoin(SkillListing, (SkillListing.category_id == Category.id) & SkillListing.is_active.is_(True)) \
        .group_by(Category.id).order_by(func.count(SkillListing.id).desc(), Category.name).limit(12).all()
    featured = _active_listings().order_by(SkillListing.created_at.desc()).limit(6).all()
    # Featured providers: anyone with an active service. Verified first, then most recent work.
    providers = (User.query.join(SkillListing, SkillListing.provider_id == User.id)
                 .filter(User.role == "provider", User.is_active_account.is_(True), SkillListing.is_active.is_(True),
                         User.is_verified.is_(True) if current_app.config["REQUIRE_VERIFICATION"] else True)
                 .group_by(User.id).order_by(User.is_verified.desc(), func.max(SkillListing.created_at).desc()).limit(4).all())
    latest = {p.id: SkillListing.query.filter_by(provider_id=p.id, is_active=True).order_by(SkillListing.created_at.desc()).first() for p in providers}
    counts = {p.id: SkillListing.query.filter_by(provider_id=p.id, is_active=True).count() for p in providers}
    return render_template("home.html", cats=cats, featured=featured, providers=providers, latest=latest, counts=counts)


@bp.route("/services")
def services():
    a = request.args
    avg = db.session.query(Review.provider_id.label("pid"), func.avg(Review.rating).label("avg")).group_by(Review.provider_id).subquery()
    qy = _active_listings().join(Category, SkillListing.category_id == Category.id).outerjoin(avg, avg.c.pid == User.id)
    q = (a.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        qy = qy.filter(db.or_(SkillListing.title.ilike(like), SkillListing.description.ilike(like), User.full_name.ilike(like), Category.name.ilike(like)))
    if a.get("category_id", type=int): qy = qy.filter(SkillListing.category_id == a.get("category_id", type=int))
    if (a.get("location") or "").strip(): qy = qy.filter(SkillListing.location.ilike(f"%{a['location'].strip()}%"))
    if a.get("min_price", type=float) is not None: qy = qy.filter(SkillListing.price >= a.get("min_price", type=float))
    if a.get("max_price", type=float) is not None: qy = qy.filter(SkillListing.price <= a.get("max_price", type=float))
    if a.get("min_rating", type=float): qy = qy.filter(avg.c.avg >= a.get("min_rating", type=float))
    if a.get("verified_only") == "1": qy = qy.filter(User.is_verified.is_(True))
    sort = a.get("sort", "new")
    qy = qy.order_by({"price_asc": SkillListing.price.asc(), "price_desc": SkillListing.price.desc(),
                      "rating": func.coalesce(avg.c.avg, 0).desc()}.get(sort, SkillListing.created_at.desc()))
    page, per = max(a.get("page", 1, type=int), 1), current_app.config["PAGE_SIZE"]
    total = qy.count()
    items = qy.offset((page - 1) * per).limit(per).all()
    args = {k: v for k, v in a.items() if k != "page" and v}
    return render_template("services.html", items=items, page=page, pages=max((total + per - 1) // per, 1), total=total,
                           cats=Category.query.order_by(Category.name).all(), args=args)


@bp.route("/services/<int:listing_id>")
def service_detail(listing_id):
    l = db.session.get(SkillListing, listing_id) or abort(404)
    if not l.is_active and not (current_user.is_authenticated and (current_user.id == l.provider_id or current_user.role == "admin")):
        abort(404)
    if current_app.config["REQUIRE_VERIFICATION"] and not l.provider.is_verified and not (current_user.is_authenticated and (current_user.id == l.provider_id or current_user.role == "admin")):
        abort(404)
    reviews = Review.query.join(Booking, Review.booking_id == Booking.id).filter(Booking.listing_id == l.id).order_by(Review.created_at.desc()).all()
    return render_template("service_detail.html", l=l, reviews=reviews)


@bp.route("/providers")
def providers():
    q = (request.args.get("q") or "").strip()
    qy = User.query.filter_by(role="provider", is_active_account=True)
    if current_app.config["REQUIRE_VERIFICATION"]: qy = qy.filter(User.is_verified.is_(True))
    if q: qy = qy.filter(User.full_name.ilike(f"%{q}%") | User.location.ilike(f"%{q}%"))
    return render_template("providers.html", providers=qy.order_by(User.is_verified.desc(), User.full_name).all(), q=q)


@bp.route("/providers/<int:pid>")
def provider_profile(pid):
    p = User.query.filter_by(id=pid, role="provider", is_active_account=True).first_or_404()
    if current_app.config["REQUIRE_VERIFICATION"] and not p.is_verified and not (current_user.is_authenticated and (current_user.id == p.id or current_user.role == "admin")):
        abort(404)
    listings = SkillListing.query.filter_by(provider_id=pid, is_active=True).order_by(SkillListing.created_at.desc()).all()
    reviews = Review.query.filter_by(provider_id=pid).order_by(Review.created_at.desc()).all()
    return render_template("provider_profile.html", p=p, listings=listings, reviews=reviews)


@bp.route("/page/<name>")
def page(name):
    t = PAGES.get(name) or abort(404)
    return render_template("page.html", title=t[0], text=t[1])


@bp.route("/about")
def about(): return page("about")


@bp.route("/contact")
def contact(): return page("contact")


@bp.route("/dashboard")
@login_required
def dashboard():
    u, n = current_user, lambda m, **f: m.query.filter_by(**f).count()
    if u.role == "admin":
        stats = [("Total users", User.query.filter(User.role != "admin").count(), "people"), ("Providers", n(User, role="provider"), "tools"),
                 ("Customers", n(User, role="customer"), "person"), ("Services", n(SkillListing), "briefcase"), ("Bookings", n(Booking), "calendar-check"),
                 ("Pending bookings", n(Booking, status="pending"), "hourglass-split"), ("Completed bookings", n(Booking, status="completed"), "check2-circle"),
                 ("Reviews", n(Review), "star"), ("Verified providers", n(User, role="provider", is_verified=True), "patch-check")]
        recent = Booking.query.order_by(Booking.created_at.desc()).limit(6).all()
    elif u.role == "provider":
        stats = [("Services", n(SkillListing, provider_id=u.id), "briefcase"), ("Pending requests", n(Booking, provider_id=u.id, status="pending"), "hourglass-split"),
                 ("Completed jobs", n(Booking, provider_id=u.id, status="completed"), "check2-circle"), ("Average rating", u.average_rating or "—", "star")]
        recent = Booking.query.filter_by(provider_id=u.id).order_by(Booking.created_at.desc()).limit(6).all()
    else:
        stats = [("Active bookings", Booking.query.filter(Booking.customer_id == u.id, Booking.status.in_(["pending", "accepted"])).count(), "calendar-check"),
                 ("Completed", n(Booking, customer_id=u.id, status="completed"), "check2-circle"), ("Reviews given", n(Review, customer_id=u.id), "star")]
        recent = Booking.query.filter_by(customer_id=u.id).order_by(Booking.created_at.desc()).limit(6).all()
    return render_template("dashboard.html", stats=stats, recent=recent)
