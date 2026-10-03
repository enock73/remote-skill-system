"""End-to-end workflow tests against the real app + a fresh database.  Run: python test_flow.py"""
import os, re, sys, tempfile
d = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{d}/t.db", RATELIMIT_ENABLED="0", ADMIN_EMAIL="admin@example.com", ADMIN_PASSWORD="Admin@12345")
B = os.path.abspath("backend"); sys.path.insert(0, B); os.chdir(B)
from app import create_app
from app.models import User, Booking, Review, Category, Notification
app = create_app(); import seed; seed.app = app; seed.run()
from flask import g
@app.before_request
def _isolate():  # the test holds one app context open; don't let g leak the logged-in user between clients
    g.pop('_login_user', None)
fails = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m); (c or fails.append(m))
def tok(c, url="/login"):
    r = c.get(url); t = r.get_data(as_text=True); m = re.search(r'name="csrf_token" value="(\w+)"', t)
    if not m: print("NO TOKEN", url, r.status_code, r.headers.get("Location"))
    return m.group(1)
def post(c, url, data=None, form="/login", **kw):
    data = dict(data or {}); data["csrf_token"] = tok(c, form); return c.post(url, data=data, follow_redirects=True, **kw)
def login(email, pw):
    c = app.test_client(); r = post(c, "/login", dict(email=email, password=pw)); return c, r
with app.app_context():
    cu, pr, ad = app.test_client(), app.test_client(), app.test_client()
    for u in ("/", "/services", "/providers", "/about", "/contact", "/page/terms", "/page/help", "/page/privacy", "/login", "/register", "/forgot-password"):
        ok(cu.get(u).status_code == 200, f"public page {u}")
    r = cu.get("/"); ok(all(f"/images/student-tech-{i}.jpg".encode() in r.data for i in (1,2,3)) and b"Learn. Build. Innovate." in r.data and b"Explore Skills" in r.data and b"Get Started" in r.data, "hero slider markup + fixed text + buttons")
    for i in (1,2,3): ok(cu.get(f"/images/student-tech-{i}.jpg").status_code == 200 and cu.get(f"/images/student-tech-{i}.jpg").mimetype == "image/jpeg", f"hero photo {i} served")
    ok(cu.get("/images/../app.py").status_code == 404, "images route blocks path traversal")
    ok(b"2026 Campus Skills Exchange. All rights reserved." in r.data, "home hero + footer")
    # provider
    r = post(pr, "/register", dict(full_name="Pat Provider", email="pat@x.com", password="Secret123", confirm="Secret123", role="provider"), "/register"); ok(b"Create a service" in r.data, "provider registers")
    cat = Category.query.first().id
    r = post(pr, "/provider/services/new", dict(title="Lawn care", category_id=cat, description="Mowing", price="500", location="Eldoret", availability="Sat"), "/provider/services/new"); ok(b"Service saved" in r.data, "provider creates service")
    from app.models import SkillListing; sid = SkillListing.query.filter_by(title="Lawn care").one().id
    r = post(pr, f"/provider/services/{sid}/edit", dict(title="Lawn care pro", category_id=cat, description="Mowing", price="600", location="Eldoret", is_active="1"), f"/provider/services/{sid}/edit"); ok(b"Service saved" in r.data, "provider edits service")
    r = post(pr, "/provider/services/new", dict(title="", category_id="", price="-1"), "/provider/services/new"); ok(b"Title is required" in r.data, "server-side validation shown")
    # customer
    r = post(cu, "/register", dict(full_name="Cathy", email="cathy@x.com", password="Secret123", confirm="Secret123", role="customer"), "/register"); ok(b"Find services" in r.data, "customer registers")
    ok(b"Lawn care pro" in cu.get("/services?q=lawn&location=Eld").data, "search by keyword+location")
    ok(b"Lawn care pro" not in cu.get("/services?q=lawn&max_price=100").data, "price filter excludes")
    ok(b"Lawn care pro" in cu.get("/services?q=Pat").data, "search by provider name")
    ok(b"Lawn care pro" not in cu.get("/services?verified_only=1").data, "verified filter excludes unverified")
    ok(b"Book service" in cu.get(f"/services/{sid}").data, "service detail shows booking form")
    r = post(cu, f"/book/{sid}", dict(requested_date="2030-01-01", message="hi"), f"/services/{sid}"); ok(b"Booking request sent" in r.data, "customer books")
    r = post(cu, f"/book/{sid}", dict(requested_date="2001-01-01"), f"/services/{sid}"); ok(b"today or later" in r.data, "past date rejected")
    ok(b"New booking request" in pr.get("/notifications").data, "provider notified")
    bid = Booking.query.order_by(Booking.id.desc()).first().id
    ok(b"cannot be changed" in post(pr, f"/bookings/{bid}/completed", {}, "/bookings").data, "pending->completed blocked")
    ok(post(cu, f"/bookings/{bid}/accepted", {}, "/bookings").status_code == 403, "customer cannot accept")
    ok(b"Booking accepted" in post(pr, f"/bookings/{bid}/accepted", {}, "/bookings").data, "provider accepts")
    ok(b"was accepted" in cu.get("/notifications").data, "customer notified of acceptance")
    ok(b"cannot be changed" in post(cu, f"/bookings/{bid}/cancelled", {}, "/bookings").data, "accepted booking not customer-cancellable")
    ok(b"Booking completed" in post(pr, f"/bookings/{bid}/completed", {}, "/bookings").data, "provider completes")
    ok(b"Leave review" in cu.get("/bookings").data, "customer sees review button")
    r = post(cu, f"/bookings/{bid}/review", dict(rating="5", comment="Great work"), f"/bookings/{bid}/review"); ok(b"review was posted" in r.data, "customer reviews")
    ok(b"already reviewed" in post(cu, f"/bookings/{bid}/review", dict(rating="1", comment="again"), "/bookings").data, "duplicate review blocked")
    ok(b"Great work" in pr.get("/reviews").data and b"5.0" in pr.get("/reviews").data, "provider sees review + average")
    ok(b"5.0" in cu.get(f"/services/{sid}").data, "rating shown on service page")
    r = post(cu, "/book/%d" % sid, dict(requested_date="2030-02-02"), f"/services/{sid}")
    b2 = Booking.query.order_by(Booking.id.desc()).first().id
    ok(b"Booking cancelled" in post(cu, f"/bookings/{b2}/cancelled", {}, "/bookings").data, "customer cancels pending")
    ok(b"cancelled their request" in pr.get("/notifications").data, "provider notified of cancel")
    ok(b"Booking declined" not in post(pr, f"/bookings/{b2}/rejected", {}, "/bookings").data, "cancelled cannot be rejected")
    ok(cu.get("/count").status_code == 404 and cu.get("/notifications/count").json["unread"] >= 1, "unread count endpoint")
    # profile / password
    ok(b"Profile saved" in post(cu, "/profile", dict(form="profile", full_name="Cathy K", phone="1", location="Eldoret"), "/profile").data, "profile edit")
    ok(b"Password changed" in post(cu, "/profile", dict(form="password", current_password="Secret123", new_password="Newpass123"), "/profile").data, "change password")
    ok(login("cathy@x.com", "Newpass123")[1].status_code == 200 and b"Sign out" in login("cathy@x.com", "Newpass123")[1].data, "login with new password")
    # forgot / reset
    from itsdangerous import URLSafeTimedSerializer
    post(cu, "/forgot-password", dict(email="cathy@x.com"), "/forgot-password")
    u = User.query.filter_by(email="cathy@x.com").one(); t = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="pw-reset").dumps({"id": u.id, "h": u.password_hash[-10:]})
    anon = app.test_client(); ok(b"Password updated" in post(anon, f"/reset-password/{t}", dict(password="Reset1234", confirm="Reset1234"), f"/reset-password/{t}").data, "password reset")
    ok(b"invalid or has expired" in post(anon, f"/reset-password/{t}", dict(password="Again12345", confirm="Again12345"), "/login").data, "reset link single-use")
    # access control / security
    ok(cu.get("/admin/users").status_code == 403, "customer blocked from admin")
    ok(pr.get("/admin/users").status_code == 403 and cu.get("/provider/services").status_code == 403, "role separation")
    ok(app.test_client().get("/bookings").status_code == 302, "anon redirected from bookings")
    other, _ = login("customer2@example.com", "Customer@123")
    ok(post(other, f"/bookings/{bid}/cancelled", {}, "/bookings").status_code == 403, "other user cannot touch booking")
    ok(app.test_client().post("/login", data={"email": "a@b.c", "password": "x"}).status_code == 400, "CSRF enforced")
    r = post(app.test_client(), "/register", dict(full_name="Hack", email="h@x.com", password="Secret123", confirm="Secret123", role="admin"), "/register"); ok(User.query.filter_by(email="h@x.com").count() == 0, "cannot self-register admin")
    ok(b"Evil" not in app.test_client().get("/login?next=//evil.com").data and post(app.test_client(), "/login?next=//evil.com", dict(email="customer2@example.com", password="Customer@123")).request.path == "/dashboard", "open-redirect blocked")
    c3 = app.test_client()
    for _ in range(5): post(c3, "/login", dict(email="customer3@example.com", password="bad"))
    ok(b"temporarily locked" in post(c3, "/login", dict(email="customer3@example.com", password="Customer@123")).data, "account lockout")
    # admin
    ad, r = login("admin@example.com", "Admin@12345"); ok(b"Verified providers" in r.data and b"Pending bookings" in r.data, "admin dashboard stats")
    for p in ("/admin/users", "/admin/providers", "/admin/services", "/admin/categories", "/admin/bookings", "/admin/reviews", "/admin/settings", "/notifications"): ok(ad.get(p, follow_redirects=True).status_code == 200, f"admin page {p}")
    ok(b"Pat Provider" in ad.get("/admin/users?q=pat").data, "admin searches users")
    pid = User.query.filter_by(email="pat@x.com").one().id
    ok(b"Verification granted" in post(ad, f"/admin/users/{pid}/verify", {}, "/admin/users").data, "admin verifies provider")
    ok(b"Verified Skill" in cu.get(f"/services/{sid}").data and b"Verified Skill" in pr.get("/notifications").data or b"verified your profile" in pr.get("/notifications").data, "badge + notification")
    ok(b"Lawn care pro" in cu.get("/services?verified_only=1").data, "verified filter includes provider")
    ok(b"Category saved" in post(ad, "/admin/categories", dict(name="Gardening", description="Lawns"), "/admin/categories").data, "admin adds category")
    ok(b"already exists" in post(ad, "/admin/categories", dict(name="gardening"), "/admin/categories").data, "duplicate category blocked")
    gid = Category.query.filter_by(name="Gardening").one().id
    ok(b"Category deleted" in post(ad, "/admin/categories", {"id": gid, "delete": "1"}, "/admin/categories").data, "admin deletes category")
    ok(b"Service updated" in post(ad, f"/admin/services/{sid}/toggle", {}, "/admin/services").data and b"Lawn care pro" not in cu.get("/services").data, "admin hides service")
    post(ad, f"/admin/services/{sid}/toggle", {}, "/admin/services")
    ok(b"Notification sent" in post(ad, "/admin/settings", dict(message="Maintenance tonight", user_id=""), "/admin/settings").data and b"Maintenance tonight" in pr.get("/notifications").data, "admin announcement")
    rid = Review.query.first().id
    ok(b"Review removed" in post(ad, "/admin/reviews", dict(id=rid), "/admin/reviews").data, "admin moderates review")
    ok(post(ad, f"/admin/users/{pid}/suspend", {}, "/admin/users").status_code == 200 and pr.get("/dashboard").status_code == 302, "suspended user logged out")
    ok(b"suspended" in login("pat@x.com", "Secret123")[1].data, "suspended user cannot sign in")
    ok(b"Account and its data removed" in post(ad, f"/admin/users/{pid}/delete", {}, "/admin/users").data and User.query.get(pid) is None, "admin deletes user (cascade)")
    ok(ad.get("/nope").status_code == 404 and b"Page not found" in ad.get("/nope").data, "404 page")
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}"); sys.exit(1 if fails else 0)
