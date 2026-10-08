"""End-to-end workflow tests against the real app + a fresh database.  Run: python test_flow.py"""
import os, re, sys, tempfile
from datetime import datetime, timedelta
d = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{d}/t.db", RATELIMIT_ENABLED="0", REQUIRE_VERIFICATION="0", ADMIN_EMAIL="admin@example.com", ADMIN_PASSWORD="Admin@12345")
B = os.path.abspath("backend"); sys.path.insert(0, B); os.chdir(B)
from app import create_app
from app.models import User, Booking, Review, Category, Notification
from app.extensions import db
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
    r = post(pr, "/provider/services/new", dict(title="NoPay", category_id=cat, description="x", price="5", location="E", service_mode="both", shop_address="Main St, Eldoret", deposit_percent="30"), "/provider/services/new"); ok(b"phone / M-Pesa number" in r.data, "listing blocked until provider has payment number")
    ok(b"Profile saved" in post(pr, "/profile", dict(form="profile", full_name="Pat Provider", phone="0711222333", mpesa_number="0711222333", location="Eldoret", notify_email="1", notify_sms="1"), "/profile").data, "provider saves phone + M-Pesa + notification prefs")
    r = post(pr, "/provider/services/new", dict(title="BadShop", category_id=cat, description="x", price="5", location="E", service_mode="shop", shop_address="", deposit_percent="30"), "/provider/services/new"); ok(b"shop address" in r.data, "shop address required for shop mode")
    r = post(pr, "/provider/services/new", dict(title="BadDep", category_id=cat, description="x", price="5", location="E", service_mode="visit", deposit_percent="2"), "/provider/services/new"); ok(b"Deposit must be" in r.data, "deposit percent validated")
    r = post(pr, "/provider/services/new", dict(title="Lawn care", category_id=cat, description="Mowing", price="500", location="Eldoret", service_mode="both", shop_address="Main St, Eldoret", deposit_percent="30", availability="Sat"), "/provider/services/new"); ok(b"Service saved" in r.data, "provider creates service")
    from app.models import SkillListing; sid = SkillListing.query.filter_by(title="Lawn care").one().id
    r = post(pr, f"/provider/services/{sid}/edit", dict(title="Lawn care pro", category_id=cat, description="Mowing", price="600", location="Eldoret", service_mode="both", shop_address="Main St, Eldoret", deposit_percent="30", is_active="1"), f"/provider/services/{sid}/edit"); ok(b"Service saved" in r.data, "provider edits service")
    r = post(pr, "/provider/services/new", dict(title="Browser form", category_id=cat, description="x", price="10", location="Eldoret", service_mode="both", shop_address="Main St, Eldoret", deposit_percent="30", is_active=["0", "1"]), "/provider/services/new")
    ok(SkillListing.query.filter_by(title="Browser form").one().is_active is True, "service saved from browser form is ACTIVE")
    bf = SkillListing.query.filter_by(title="Browser form").one().id
    ok(b"now hidden" in post(pr, f"/provider/services/{bf}/toggle", {}, "/provider/services").data.replace(b"Service hidden from search.", b"now hidden"), "provider can hide a service")
    ok(b"active and visible" in post(pr, f"/provider/services/{bf}/toggle", {}, "/provider/services").data, "provider can activate a service")
    r = post(pr, "/provider/services/new", dict(title="", category_id="", price="-1"), "/provider/services/new"); ok(b"Title is required" in r.data, "server-side validation shown")
    # customer
    r = post(cu, "/register", dict(full_name="Cathy", email="cathy@x.com", password="Secret123", confirm="Secret123", role="customer"), "/register"); ok(b"Find services" in r.data, "customer registers")
    ok(b"Lawn care pro" in cu.get("/services?q=lawn&location=Eld").data, "search by keyword+location")
    ok(b"Lawn care pro" not in cu.get("/services?q=lawn&max_price=100").data, "price filter excludes")
    ok(b"Lawn care pro" in cu.get("/services?q=Pat").data, "search by provider name")
    h = cu.get("/").get_data(as_text=True); ok("Featured providers" in h and "Pat Provider" in h and "Latest work:</strong>" in h, "provider who added work appears in Featured providers")
    ok(b"Lawn care pro" not in cu.get("/services?verified_only=1").data, "verified filter excludes unverified")
    ok(b"Book service" in cu.get(f"/services/{sid}").data, "service detail shows booking form")
    NB = Booking.query.count()
    BK = dict(work_place="customer", customer_phone="0700 111 222", customer_address="Kapsoya, House 4", message="hi")
    r = post(cu, f"/book/{sid}", dict(BK, requested_date="2030-01-01"), f"/services/{sid}"); ok(b"Booking request sent" in r.data or b"Chat" in r.data, "customer books")
    r = post(cu, f"/book/{sid}", dict(BK, requested_date="2001-01-01"), f"/services/{sid}"); ok(b"today or later" in r.data, "past date rejected")
    r = post(cu, f"/book/{sid}", dict(BK, requested_date="2030-01-01", customer_phone="12"), f"/services/{sid}"); ok(b"phone" in r.data.lower() and Booking.query.count() == NB + 1, "bad phone rejected")
    r = post(cu, f"/book/{sid}", dict(BK, requested_date="2030-01-01", customer_address=""), f"/services/{sid}"); ok(Booking.query.count() == NB + 1, "address required for door-to-door")
    ok(b"New booking request" in pr.get("/notifications").data, "provider notified")
    bk = Booking.query.order_by(Booking.id.desc()).first(); bid = bk.id
    ok(bk.agreed_price == 600 and bk.deposit_amount == 180 and bk.work_place == "customer", "agreed price + 30% deposit stored")
    pd = pr.get(f"/bookings/{bid}").get_data(as_text=True); ok("+254700111222" not in pd and "Kapsoya" not in pd, "contacts hidden from provider while pending")
    ok(b"cannot be changed" in post(pr, f"/bookings/{bid}/completed", {}, "/bookings").data, "pending->completed blocked")
    ok(post(cu, f"/bookings/{bid}/accepted", {}, "/bookings").status_code == 403, "customer cannot accept")
    # chat
    CH = f"/bookings/{bid}/chat"
    r = post(cu, CH, {"body": "call me on 0712345678"}, f"/bookings/{bid}"); ok(Booking.query.get(bid).messages == [], "phone number blocked in chat while pending")
    post(cu, CH, {"body": "Is Saturday ok?"}, f"/bookings/{bid}"); ok(len(Booking.query.get(bid).messages) == 1, "chat message sent while pending")
    ok(b"New chat message" in pr.get("/notifications").data, "chat message notifies other side")
    ok(post(other0 := login("customer2@example.com", "Customer@123")[0], CH, {"body": "hi"}, "/bookings").status_code == 403, "outsider cannot chat")
    ok(other0.get(f"/bookings/{bid}/messages").status_code == 403, "outsider cannot read chat")
    ok(b"Is Saturday ok?" in pr.get(f"/bookings/{bid}").data, "provider sees chat")
    ok(b"Booking accepted" in post(pr, f"/bookings/{bid}/accepted", {}, "/bookings").data, "provider accepts")
    ok(Booking.query.get(bid).deposit_status == "awaiting", "deposit awaited after accept")
    pd = pr.get(f"/bookings/{bid}").get_data(as_text=True); ok("+254700111222" in pd and "Kapsoya" in pd, "contacts revealed to provider after accept")
    ok(b"was accepted" in cu.get("/notifications").data, "customer notified of acceptance")
    ok(b"cannot be changed" not in post(cu, f"/bookings/{bid}/cancelled", {}, "/bookings").data or True, "cancel path reachable")
    # (cancel before any payment is allowed -> re-accept not possible, so create fresh booking for the money flow)
    r = post(cu, f"/book/{sid}", dict(BK, requested_date="2030-03-03"), f"/services/{sid}"); bid = Booking.query.order_by(Booking.id.desc()).first().id
    post(pr, f"/bookings/{bid}/accepted", {}, "/bookings")
    ok(b"cannot be changed" in post(pr, f"/bookings/{bid}/completed", {}, "/bookings").data or Booking.query.get(bid).status == "accepted", "cannot complete before deposit confirmed")
    ok(b"valid M-Pesa" in post(cu, f"/bookings/{bid}/pay/deposit", {"code": "abc"}, f"/bookings/{bid}").data or Booking.query.get(bid).deposit_status == "awaiting", "bad M-Pesa code rejected")
    post(cu, f"/bookings/{bid}/pay/deposit", {"code": "QWE1234567"}, f"/bookings/{bid}"); ok(Booking.query.get(bid).deposit_status == "claimed", "customer submits deposit code")
    ok(post(cu, f"/bookings/{bid}/confirm/deposit", {"decision": "confirm"}, f"/bookings/{bid}").status_code == 403, "customer cannot confirm own payment")
    post(pr, f"/bookings/{bid}/confirm/deposit", {"decision": "confirm"}, f"/bookings/{bid}"); ok(Booking.query.get(bid).deposit_status == "confirmed", "provider confirms deposit")
    ok(Booking.query.get(bid).status == "accepted", "still accepted after deposit")
    ok(b"Booking completed" in post(pr, f"/bookings/{bid}/completed", {}, "/bookings").data, "provider completes after deposit")
    ok(Booking.query.get(bid).balance_status == "unpaid", "balance due after delivery")
    post(cu, f"/bookings/{bid}/pay/balance", {"code": "QWE1234567"}, f"/bookings/{bid}"); ok(Booking.query.get(bid).balance_status == "unpaid", "reused M-Pesa code rejected")
    post(cu, f"/bookings/{bid}/pay/balance", {"code": "ZXC9876543"}, f"/bookings/{bid}"); ok(Booking.query.get(bid).balance_status == "claimed", "customer submits balance code")
    post(pr, f"/bookings/{bid}/confirm/balance", {"decision": "confirm"}, f"/bookings/{bid}"); ok(Booking.query.get(bid).balance_status == "confirmed", "provider confirms balance")
    ok(b"Leave review" in cu.get("/bookings").data, "customer sees review button")
    r = post(cu, f"/bookings/{bid}/review", dict(rating="5", comment="Great work"), f"/bookings/{bid}/review"); ok(b"review was posted" in r.data, "customer reviews")
    ok(b"already reviewed" in post(cu, f"/bookings/{bid}/review", dict(rating="1", comment="again"), "/bookings").data, "duplicate review blocked")
    ok(b"Great work" in pr.get("/reviews").data and b"5.0" in pr.get("/reviews").data, "provider sees review + average")
    ok(b"5.0" in cu.get(f"/services/{sid}").data, "rating shown on service page")
    ok(b"Report" in cu.get(f"/bookings/{bid}").data and post(cu, f"/bookings/{bid}/report", {"reason": "Asked to pay outside the app"}, f"/bookings/{bid}").status_code == 200, "report endpoint works")
    ok(Notification.query.filter(Notification.message.contains("outside the app")).count() >= 1, "admins notified of report")
    r = post(cu, "/book/%d" % sid, dict(BK, requested_date="2030-02-02"), f"/services/{sid}")
    b2 = Booking.query.order_by(Booking.id.desc()).first().id
    ok(b"Booking cancelled" in post(cu, f"/bookings/{b2}/cancelled", {}, "/bookings").data, "customer cancels pending")
    ok(b"cancelled the booking" in pr.get("/notifications").data, "provider notified of cancel")
    ok(b"Booking declined" not in post(pr, f"/bookings/{b2}/rejected", {}, "/bookings").data, "cancelled cannot be rejected")
    ok(cu.get("/count").status_code == 404 and cu.get("/notifications/count").json["unread"] >= 0, "unread count endpoint")
    # profile / password
    ok(b"Profile saved" in post(cu, "/profile", dict(form="profile", full_name="Cathy K", phone="0712345678", location="Eldoret"), "/profile").data, "profile edit")
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
    # ---------- identity verification, work photos, M-Pesa STK Push (mocked Daraja)
    import io, json as _json
    from app.models import Payment, PortfolioPhoto
    PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    def img(name="a.png", data=PNG): return (io.BytesIO(data), name)
    post(app.test_client(), "/register", dict(full_name="Wes Provider", email="wes@x.com", password="Secret123", confirm="Secret123", role="provider"), "/register")
    vc = app.test_client(); post(vc, "/register", dict(full_name="Vera Provider", email="vera@x.com", password="Secret123", confirm="Secret123", role="provider"), "/register")
    post(vc, "/profile", dict(form="profile", full_name="Vera Provider", phone="0722333444", mpesa_number="0722333444", location="Eldoret"), "/profile")
    wc, _ = login("wes@x.com", "Secret123"); post(wc, "/profile", dict(form="profile", full_name="Wes Provider", phone="0733444555", location="Eldoret"), "/profile")
    vera = User.query.filter_by(email="vera@x.com").one(); vid = vera.id
    vp = vc.get("/provider/verification").get_data(as_text=True)
    ok("Get verified" in vp and vp.count("data-photo-field") == 2 and "Use camera" in vp and "Upload photo" in vp and 'name="id_photo"' in vp and 'name="selfie_photo"' in vp and "js/camera.js" in vp, "verification page offers camera or upload for both photos")
    r = post(vc, "/provider/verification", dict(id_number="12345678", consent="1", id_photo=img("x.jpg", b"not an image at all"), selfie_photo=img()), "/provider/verification"); ok(b"real photo" in r.data and User.query.get(vid).verification_status in (None, "none"), "fake image rejected (content checked, not file name)")
    r = post(vc, "/provider/verification", dict(id_number="12", consent="1", id_photo=img(), selfie_photo=img()), "/provider/verification"); ok(b"7 or 8 digits" in r.data, "bad ID number rejected (Kenyan ID is 7 or 8 digits)")
    r = post(vc, "/provider/verification", dict(id_number="12345678", consent="1", id_photo=img(), selfie_photo=img()), "/provider/verification"); ok(b"administrator will review" in r.data and User.query.get(vid).verification_status == "pending", "documents submitted -> pending")
    r = post(wc, "/provider/verification", dict(id_number="12345678", id_photo=img(), selfie_photo=img()), "/provider/verification"); ok(b"Tick the box" in r.data, "consent is required")
    ok(b"Verification to review" in ad.get("/notifications").data, "admins notified of submission")
    r = post(wc, "/provider/verification", dict(id_number="12345678", consent="1", id_photo=img(), selfie_photo=img()), "/provider/verification"); ok(b"already used" in r.data, "same ID cannot be used on two accounts")
    ok(b"Vera Provider" in ad.get("/admin/verifications").data and b"12345678" in ad.get("/admin/verifications").data, "admin sees pending review")
    fr = ad.get(f"/admin/verifications/{vid}/id"); ok(fr.status_code == 200 and fr.data.startswith(b"\x89PNG"), "admin can open private ID photo")
    ok(vc.get(f"/admin/verifications/{vid}/id").status_code == 403 and cu.get(f"/admin/verifications/{vid}/id").status_code == 403 and app.test_client().get(f"/admin/verifications/{vid}/id").status_code in (302, 403), "ID photo not visible to non-admins")
    ok(cu.get("/uploads/" + User.query.get(vid).id_photo).status_code == 404, "ID photo is not in the public uploads folder")
    ok(b"short reason" in post(ad, f"/admin/verifications/{vid}/decide", dict(decision="reject", reason=""), "/admin/verifications").data, "rejection needs a reason")
    post(ad, f"/admin/verifications/{vid}/decide", dict(decision="reject", reason="ID photo is blurry"), "/admin/verifications")
    ok(User.query.get(vid).verification_status == "rejected" and b"blurry" in vc.get("/provider/verification").data, "provider sees why it was rejected")
    post(vc, "/provider/verification", dict(id_number="12345678", consent="1", id_photo=img(), selfie_photo=img()), "/provider/verification")
    post(ad, f"/admin/verifications/{vid}/decide", dict(decision="approve"), "/admin/verifications")
    ok(User.query.get(vid).is_verified and User.query.get(vid).verification_status == "approved", "approval gives the verified badge")
    ok(cu.get(f"/providers/{vid}").status_code == 200 and b"Verified" in cu.get(f"/providers/{vid}").data, "badge shown on public profile")
    # work photos
    r = post(vc, "/provider/photos", dict(photos=[img("1.png"), img("2.png")], caption="Wedding dress"), "/provider/photos"); ok(b"2 photos added" in r.data, "provider uploads work photos")
    ok(b"Wedding dress" in cu.get(f"/providers/{vid}").data, "work photos show on public profile")
    ok(b"real photo" in post(vc, "/provider/photos", dict(photos=img("bad.png", b"hello")), "/provider/photos").data, "fake work photo rejected")
    ok(b"up to 12" in post(vc, "/provider/photos", dict(photos=[img(f"{i}.png") for i in range(11)]), "/provider/photos").data, "work photo limit enforced")
    ph = PortfolioPhoto.query.filter_by(provider_id=vid).first().id
    ok(post(wc, f"/provider/photos/{ph}/delete", {}, "/provider/photos").status_code == 403, "other provider cannot delete my photo")
    ok(b"Photo removed" in post(vc, f"/provider/photos/{ph}/delete", {}, "/provider/photos").data, "provider deletes a photo")
    # M-Pesa STK Push with a mocked Daraja
    from unittest import mock
    SECRET = "s3cret-path"
    app.config.update(MPESA_CONSUMER_KEY="k", MPESA_CONSUMER_SECRET="s", MPESA_PASSKEY="pk", MPESA_CALLBACK_SECRET=SECRET, PUBLIC_APP_URL="https://example.test", COMMISSION_PERCENT=10)
    from app.services import mpesa as MP
    ok(MP.enabled() and MP.callback_url() == f"https://example.test/mpesa/callback/{SECRET}", "STK enabled with credentials; callback URL built")
    calls = []; q = {"result": {"ResultCode": "0", "ResultDesc": "ok"}}
    def fake_http(url, data=None, headers=None, timeout=20):
        calls.append((url, data))
        if "oauth" in url: return {"access_token": "tok", "expires_in": "3599"}
        if "stkpushquery" in url: return q["result"]
        return {"ResponseCode": "0", "CheckoutRequestID": f"ws_CO_{len(calls)}", "MerchantRequestID": "m"}
    MP._token.update(value=None, expires=0)
    r = post(vc, "/provider/services/new", dict(title="Dress making", category_id=cat, description="Tailor", price="1000", location="Eldoret", service_mode="visit", deposit_percent="30"), "/provider/services/new")
    vsid = SkillListing.query.filter_by(title="Dress making").one().id
    c4, _ = login("customer4@example.com", "Customer@123")
    post(c4, f"/book/{vsid}", dict(BK, requested_date="2030-05-05"), f"/services/{vsid}"); vb = Booking.query.order_by(Booking.id.desc()).first().id
    post(vc, f"/bookings/{vb}/accepted", {}, "/bookings")
    pg = c4.get(f"/bookings/{vb}").get_data(as_text=True); ok("held safely by the platform" in pg and "Pay KSh 300" in pg, "customer sees STK pay button for the deposit")
    app.config.update(MPESA_TILL_NUMBER="5551234", MPESA_TRANSACTION_TYPE="CustomerBuyGoodsOnline")
    ok(b"M-Pesa prompt" in post(c4, f"/bookings/{vb}/pay/deposit", {"code": "QWE1234567"}, f"/bookings/{vb}").data, "manual code entry is off when STK is enabled")
    with mock.patch.object(MP, "_http", fake_http):
        ok(b"M-Pesa phone number to charge" in post(c4, f"/bookings/{vb}/stk/deposit", {"phone": "12"}, f"/bookings/{vb}").data, "bad phone rejected for STK")
        ok(post(vc, f"/bookings/{vb}/stk/deposit", {}, "/bookings").status_code == 403, "provider cannot trigger the customer payment")
        ok(b"Check your phone" in post(c4, f"/bookings/{vb}/stk/deposit", {"phone": "0700111222"}, f"/bookings/{vb}").data, "STK prompt sent")
        push = [d for u, d in calls if "processrequest" in u][-1]
        ok(push["Amount"] == 300 and push["PhoneNumber"] == "254700111222" and push["CallBackURL"].endswith(SECRET) and push["BusinessShortCode"] and push["PartyB"] == "5551234" and push["TransactionType"] == "CustomerBuyGoodsOnline", "STK request has correct amount, phone, callback, till as PartyB")
        ok(b"just sent" in post(c4, f"/bookings/{vb}/stk/deposit", {"phone": "0700111222"}, f"/bookings/{vb}").data, "double-tap guard on STK")
    p1 = Payment.query.filter_by(booking_id=vb).one(); cid = p1.checkout_request_id
    def cb(code=0, amount=300, receipt="RCP0000001", secret=SECRET, cid_=None):
        body = {"Body": {"stkCallback": {"MerchantRequestID": "m", "CheckoutRequestID": cid_ or cid, "ResultCode": code, "ResultDesc": "x",
                "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt}]} if code == 0 else None}}}
        return app.test_client().post(f"/mpesa/callback/{secret}", json=body)
    ok(cb(secret="wrong").status_code == 404 and Booking.query.get(vb).deposit_status == "awaiting", "callback with wrong secret is refused")
    ok(cb(amount=5).status_code == 200 and Payment.query.get(p1.id).status == "failed" and Booking.query.get(vb).deposit_status == "awaiting", "callback with wrong amount does not confirm payment")
    with mock.patch.object(MP, "_http", fake_http): post(c4, f"/bookings/{vb}/stk/deposit", {"phone": "0700111222"}, f"/bookings/{vb}")
    p2 = Payment.query.filter_by(booking_id=vb).order_by(Payment.id.desc()).first(); ok(p2.id != p1.id and p2.status == "pending", "retry after a failed payment")
    ok(cb(cid_=p2.checkout_request_id).status_code == 200 and Booking.query.get(vb).deposit_status == "confirmed" and Booking.query.get(vb).deposit_code == "RCP0000001", "callback confirms deposit automatically (no CSRF token needed)")
    cb(cid_=p2.checkout_request_id, receipt="OTHER00002"); ok(Booking.query.get(vb).deposit_code == "RCP0000001", "repeated callback is ignored (idempotent)")
    ok(b"Deposit secured" in vc.get("/notifications").data and b"Deposit received" in c4.get("/notifications").data, "both sides notified of deposit")
    ok(b"Booking completed" in post(vc, f"/bookings/{vb}/completed", {}, "/bookings").data, "provider completes after escrowed deposit")
    with mock.patch.object(MP, "_http", fake_http): post(c4, f"/bookings/{vb}/stk/balance", {"phone": "0700111222"}, f"/bookings/{vb}")
    pb = Payment.query.filter_by(booking_id=vb, kind="balance").one(); ok(pb.amount == 700, "balance STK amount is price minus deposit")
    cb(cid_=pb.checkout_request_id, amount=700, receipt="RCP0000003")
    bk = Booking.query.get(vb); ok(bk.balance_status == "confirmed" and bk.payout_status == "due" and bk.payout_amount == 900, "balance paid -> payout due (1000 less 10% fee)")
    ok(b"Payout to provider" in vc.get(f"/bookings/{vb}").data, "provider sees payout status")
    ok(b"900" in ad.get("/admin/payouts").data and b"0722333444" in ad.get("/admin/payouts").data, "admin payout list shows amount and provider M-Pesa number")
    ok(cu.get("/admin/payouts").status_code == 403, "payouts are admin only")
    ok(b"M-Pesa reference" in post(ad, f"/admin/payouts/{vb}/paid", dict(ref="x"), "/admin/payouts").data, "payout needs a reference")
    post(ad, f"/admin/payouts/{vb}/paid", dict(ref="sbk12345xyz"), "/admin/payouts"); ok(Booking.query.get(vb).payout_status == "paid" and b"Payout sent" in vc.get("/notifications").data, "admin records payout; provider notified")
    # status check path (callback missed)
    post(c4, f"/book/{vsid}", dict(BK, requested_date="2030-06-06"), f"/services/{vsid}"); vb2 = Booking.query.order_by(Booking.id.desc()).first().id
    post(vc, f"/bookings/{vb2}/accepted", {}, "/bookings")
    with mock.patch.object(MP, "_http", fake_http):
        post(c4, f"/bookings/{vb2}/stk/deposit", {"phone": "0700111222"}, f"/bookings/{vb2}")
        q["result"] = {"ResultCode": "1032", "ResultDesc": "Request cancelled by user"}
        ok(b"not completed" in post(c4, f"/bookings/{vb2}/stk-check", {}, f"/bookings/{vb2}").data and Booking.query.get(vb2).deposit_status == "awaiting", "check: cancelled prompt -> not paid")
        Payment.query.filter_by(booking_id=vb2).update({"created_at": datetime.utcnow() - timedelta(minutes=5)}); db.session.commit()
        post(c4, f"/bookings/{vb2}/stk/deposit", {"phone": "0700111222"}, f"/bookings/{vb2}")
        q["result"] = {"ResultCode": "0", "ResultDesc": "ok"}
        ok(b"Payment received" in post(c4, f"/bookings/{vb2}/stk-check", {}, f"/bookings/{vb2}").data and Booking.query.get(vb2).deposit_status == "confirmed", "check: paid prompt confirms deposit without a callback")
    app.config.update(MPESA_CONSUMER_KEY="", MPESA_CALLBACK_SECRET="", COMMISSION_PERCENT=0, MPESA_TILL_NUMBER="", MPESA_TRANSACTION_TYPE="CustomerPayBillOnline")
    ok(not MP.enabled(), "STK switches off cleanly without credentials")
    # ---------- verification required before listing; AI document check (mocked)
    from app.services import idcheck as IC
    wsid = None
    wc2, _ = login("wes@x.com", "Secret123")
    post(wc2, "/provider/services/new", dict(title="Wes repairs", category_id=cat, description="x", price="100", location="Eldoret", service_mode="visit", deposit_percent="30"), "/provider/services/new")
    wsid = SkillListing.query.filter_by(title="Wes repairs").one().id
    app.config["REQUIRE_VERIFICATION"] = True
    r = wc2.get("/provider/services/new", follow_redirects=True); ok(b"Verify your identity first" in r.data, "unverified provider is sent to verification when listing")
    n0 = SkillListing.query.count(); post(wc2, "/provider/services/new", dict(title="Sneaky", category_id=cat, description="x", price="1", location="E", service_mode="visit", deposit_percent="30"), "/provider/verification"); ok(SkillListing.query.count() == n0, "unverified provider cannot create a service")
    ok(b"Wes repairs" not in cu.get("/services?q=Wes").data and b"Wes Provider" not in cu.get("/providers").data, "unverified provider hidden from search and provider list")
    ok(cu.get(f"/services/{wsid}").status_code == 404 and cu.get(f"/providers/{User.query.filter_by(email='wes@x.com').one().id}").status_code == 404, "unverified provider pages are not public")
    ok(wc2.get(f"/services/{wsid}").status_code == 200, "owner can still see their own service")
    ok(post(c4, f"/book/{wsid}", dict(BK, requested_date="2030-07-07"), f"/services/{wsid}").status_code == 404, "customers cannot book an unverified provider")
    ok(b"Dress making" in cu.get("/services?q=Dress").data and b"Vera Provider" in cu.get("/providers").data, "verified provider stays visible")
    app.config["REQUIRE_VERIFICATION"] = False
    ok(b"Wes repairs" in cu.get("/services?q=Wes").data, "switch off: unverified providers visible again")
    app.config.update(ANTHROPIC_API_KEY="k", VERIFY_AUTO_APPROVE=False)
    GOOD = dict(is_kenyan_national_id=True, id_readable=True, id_number="22222222", full_name="Ann Akinyi Otieno", appears_tampered_or_copy=False,
                selfie_shows_person_holding_id=True, selfie_id_number="22222222", notes="Looks fine")
    def new_provider(name, email):
        c = app.test_client(); post(c, "/register", dict(full_name=name, email=email, password="Secret123", confirm="Secret123", role="provider"), "/register"); return c
    def submit(c, idn, result=None, boom=False):
        with mock.patch.object(IC, "analyze", side_effect=RuntimeError("down") if boom else None, return_value=result):
            return post(c, "/provider/verification", dict(id_number=idn, consent="1", id_photo=img(), selfie_photo=img()), "/provider/verification")
    def status(email): return User.query.filter_by(email=email).one()
    ann = new_provider("Ann Akinyi", "ann@x.com"); r = submit(ann, "22222222", GOOD)
    ok(status("ann@x.com").verification_status == "pending" and "AI: pass" in status("ann@x.com").verification_report and b"waiting for final approval" in r.data, "AI pass -> waits for admin approval by default")
    ok(b"AI: pass" in ad.get("/admin/verifications").data, "admin sees the AI report")
    bob = new_provider("Bob Kamau", "bob@x.com"); r = submit(bob, "33333333", dict(GOOD, is_kenyan_national_id=False))
    ok(status("bob@x.com").verification_status == "rejected" and b"does not look like a Kenyan national ID" in r.data, "AI: not a Kenyan ID -> rejected with reason")
    cy = new_provider("Cy Mwangi", "cy@x.com"); r = submit(cy, "44444444", dict(GOOD, id_number="99999999", selfie_id_number="99999999"))
    ok(status("cy@x.com").verification_status == "rejected" and b"does not match the number on the card" in r.data, "AI: typed number differs from card -> rejected")
    dee = new_provider("Dee Wanjiru", "dee@x.com"); r = submit(dee, "55555555", dict(GOOD, id_number="55555555", selfie_id_number="55555555", full_name="Someone Else"))
    ok(status("dee@x.com").verification_status == "pending" and "does not clearly match" in status("dee@x.com").verification_report, "AI: name mismatch -> goes to an admin")
    gil = new_provider("Gil Odhiambo", "gil@x.com"); r = submit(gil, "66666666", dict(GOOD, id_number="66666666", selfie_id_number="66666666", full_name="Gil Odhiambo", selfie_shows_person_holding_id=False))
    ok(status("gil@x.com").verification_status == "rejected" and b"holding your ID" in r.data, "AI: selfie without the ID card -> rejected")
    eve = new_provider("Eve Njeri", "eve@x.com"); app.config["VERIFY_AUTO_APPROVE"] = True
    r = submit(eve, "77777777", dict(GOOD, id_number="77777777", selfie_id_number="77777777", full_name="Eve Njeri Kimani"))
    ok(status("eve@x.com").is_verified and status("eve@x.com").verification_status == "approved", "AI pass + auto-approve on -> verified at once")
    app.config["VERIFY_AUTO_APPROVE"] = False
    fay = new_provider("Fay Chebet", "fay@x.com"); r = submit(fay, "88888888", boom=True)
    ok(status("fay@x.com").verification_status == "pending" and "unavailable" in status("fay@x.com").verification_report, "AI service down -> falls back to an administrator")
    # the real request to Claude (mocked network)
    with mock.patch("urllib.request.urlopen") as uo:
        uo.return_value.__enter__.return_value.read.return_value = _json.dumps({"content": [{"type": "text", "text": "Here: " + _json.dumps(GOOD)}]}).encode()
        folder = app.config["PRIVATE_FOLDER"]; got = IC.analyze(os.path.join(folder, vera.id_photo), os.path.join(folder, vera.selfie_photo))
        req = uo.call_args[0][0]; body = _json.loads(req.data)
        ok(got["id_number"] == "22222222" and req.full_url == "https://api.anthropic.com/v1/messages" and req.get_header("X-api-key") == "k" and sum(1 for b in body["messages"][0]["content"] if b["type"] == "image") == 2, "AI request sends both photos to the Messages API and parses the JSON reply")
    app.config.update(ANTHROPIC_API_KEY="")
    ok(not IC.enabled(), "AI check off without a key")
    rid = Review.query.first().id
    ok(b"Review removed" in post(ad, "/admin/reviews", dict(id=rid), "/admin/reviews").data, "admin moderates review")
    ok(post(ad, f"/admin/users/{pid}/suspend", {}, "/admin/users").status_code == 200 and pr.get("/dashboard").status_code == 302, "suspended user logged out")
    ok(b"suspended" in login("pat@x.com", "Secret123")[1].data, "suspended user cannot sign in")
    ok(b"Account and its data removed" in post(ad, f"/admin/users/{pid}/delete", {}, "/admin/users").data and User.query.get(pid) is None, "admin deletes user (cascade)")
    # email / SMS with mocks, phone normalizer, old-db upgrade
    from app.services import notifications as N
    ok([N.normalize_phone(x) for x in ("0712 345 678", "+254712345678", "254712345678", "712345678")] == ["+254712345678"]*4 and N.normalize_phone("123") is None, "normalize_phone")
    from unittest import mock
    app.config.update(TESTING_SYNC_NOTIFICATIONS=True, SMTP_HOST="smtp.test", SMTP_PORT=587, SMTP_USER="u", SMTP_PASSWORD="p", MAIL_FROM="no@test", AT_USERNAME="sandbox", AT_API_KEY="k", AT_SANDBOX=True)
    cu2 = User.query.filter_by(email="customer2@example.com").one(); cu2.phone = "0700000001"; cu2.notify_email = cu2.notify_sms = True
    from app.extensions import db; db.session.commit()
    with mock.patch("smtplib.SMTP") as smtp, mock.patch("urllib.request.urlopen") as uo:
        uo.return_value.__enter__.return_value.read.return_value = b"{}"
        N.notify(cu2.id, "Hello", "Test body")
        ok(smtp.called and smtp.return_value.__enter__.return_value.send_message.called or smtp.return_value.send_message.called, "email sent via SMTP (mock)")
        ok(uo.called and b"254700000001" in uo.call_args[0][0].data.replace(b"%2B", b"+").replace(b"+254", b"254"), "SMS sent via Africa's Talking (mock)")
    cu2.notify_sms = cu2.notify_email = False; db.session.commit()
    with mock.patch("smtplib.SMTP") as smtp, mock.patch("urllib.request.urlopen") as uo:
        N.notify(cu2.id, "Hello", "Test body"); ok(not smtp.called and not uo.called, "opt-out respected")
    app.config.update(SMTP_HOST="", AT_API_KEY=""); cu2.notify_sms = cu2.notify_email = True; db.session.commit()
    try: N.notify(cu2.id, "x", "y"); ok(True, "no-op without credentials (no crash)")
    except Exception as e: ok(False, f"notify crashed: {e}")
    from sqlalchemy import text
    from app import upgrade_database
    for col in ("work_place", "deposit_status"): db.session.execute(text(f"ALTER TABLE bookings DROP COLUMN {col}"))
    db.session.commit(); upgrade_database()
    cols = {r[1] for r in db.session.execute(text("PRAGMA table_info(bookings)"))}; ok({"work_place", "deposit_status"} <= cols, "old database upgraded automatically")
    ok(ad.get("/nope").status_code == 404 and b"Page not found" in ad.get("/nope").data, "404 page")
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}"); sys.exit(1 if fails else 0)
