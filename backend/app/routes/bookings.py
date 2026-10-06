import re
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from app.decorators import roles_required
from app.extensions import db, limiter
from app.models import Booking, SkillListing, Review, Notification, Message, User, Payment
from app.services.notifications import notify, normalize_phone
from app.services import mpesa
import hmac, math
from flask import current_app

bp = Blueprint("bookings", __name__)

# who may move a booking, and from which status
TRANSITIONS = {"provider": {"pending": {"accepted", "rejected"}, "accepted": {"completed", "cancelled"}},
               "customer": {"pending": {"cancelled"}, "accepted": {"cancelled"}}}
ALLOWED_ACTIONS = {"provider": {"accepted", "rejected", "completed", "cancelled"}, "customer": {"cancelled"}}
MPESA_CODE = re.compile(r"^[A-Z0-9]{10}$")                      # e.g. QGH7K2L9MN
CONTACT_IN_TEXT = re.compile(r"\+?\d(?:[\s\-.]?\d){8,}|[\w.+-]+@[\w-]+\.[\w.]+")   # phone numbers / email addresses
CHAT_STATUSES = {"pending", "accepted", "completed"}


def kes(x): return f"KSh {x:,.0f}"


def _booking_for(bid, allow_admin=True):
    """Load a booking only if the current user is its customer, its provider (or an admin, read-only)."""
    b = db.session.get(Booking, bid) or abort(404)
    if current_user.role == "admin":
        if not allow_admin: abort(403)
    elif current_user.id not in (b.customer_id, b.provider_id):
        abort(403)
    return b


def _link(b): return url_for("bookings.detail", bid=b.id)


@bp.route("/book/<int:listing_id>", methods=["POST"])
@roles_required("customer")
def create(listing_id):
    l = db.session.get(SkillListing, listing_id) or abort(404)
    if not l.is_active or not l.provider.is_active_account: abort(404)
    back = redirect(url_for("main.service_detail", listing_id=l.id))
    f = request.form
    try: when = datetime.strptime(f.get("requested_date", ""), "%Y-%m-%d").date()
    except ValueError: when = None
    if not when or when < date.today():
        flash("Choose a preferred date that is today or later.", "danger"); return back
    place = f.get("work_place", "")
    if place == "shop" and not l.offers_shop or place == "customer" and not l.offers_visit or place not in ("shop", "customer"):
        flash("Choose where the work should be done.", "danger"); return back
    phone = normalize_phone(f.get("customer_phone", ""))
    if not phone:
        flash("Enter a valid phone number (for example 0712 345 678) so the provider can reach you once they accept.", "danger"); return back
    address = f.get("customer_address", "").strip()[:255]
    if place == "customer" and len(address) < 5:
        flash("Enter the address or location where the provider should come (area, street, landmark).", "danger"); return back
    pct = l.deposit_pct
    b = Booking(customer_id=current_user.id, provider_id=l.provider_id, listing_id=l.id, requested_date=when,
                message=f.get("message", "").strip()[:1000], work_place=place, customer_phone=phone,
                customer_address=address if place == "customer" else None, agreed_price=l.price,
                deposit_amount=round(l.price * pct / 100, 2), deposit_status="none", balance_status="none")
    if not current_user.phone: current_user.phone = phone      # so SMS alerts can reach them
    db.session.add(b); db.session.commit()
    notify(l.provider_id, "New booking request", f"{current_user.full_name} requested '{l.title}' for {when:%d %b %Y}. Open it to accept or reject.", _link(b))
    flash("Booking request sent. Your phone number and address are shared with the provider only if they accept.", "success")
    return redirect(_link(b))


@bp.route("/bookings")
@roles_required("customer", "provider")
def mine():
    col = Booking.provider_id if current_user.role == "provider" else Booking.customer_id
    qy = Booking.query.filter(col == current_user.id)
    status = request.args.get("status")
    if status: qy = qy.filter_by(status=status)
    return render_template("bookings.html", bookings=qy.order_by(Booking.created_at.desc()).all(), status=status)


@bp.route("/bookings/<int:bid>")
@login_required
def detail(bid):
    b = _booking_for(bid)
    Notification.query.filter_by(user_id=current_user.id, link=_link(b), is_read=False).update({"is_read": True}); db.session.commit()
    can_chat = current_user.role != "admin" and b.status in CHAT_STATUSES
    return render_template("booking_detail.html", b=b, can_chat=can_chat, kes=kes, mpesa_on=mpesa.enabled())


@bp.route("/bookings/<int:bid>/<new>", methods=["POST"])
@roles_required("customer", "provider")
def set_status(bid, new):
    b = db.session.get(Booking, bid) or abort(404)
    owner = b.provider_id if current_user.role == "provider" else b.customer_id
    if owner != current_user.id: abort(403)
    if new not in ALLOWED_ACTIONS[current_user.role]: abort(403)
    if new not in TRANSITIONS[current_user.role].get(b.status, set()):
        flash(f"A {b.status} booking cannot be changed to {new}.", "danger"); return redirect(_link(b))
    t = b.listing.title
    if new == "completed" and b.deposit_status not in ("confirmed", "none"):
        flash("Confirm the customer's deposit first. Work should only be completed after the deposit is confirmed.", "danger"); return redirect(_link(b))
    if new == "cancelled" and b.status == "accepted" and b.deposit_status in ("claimed", "confirmed"):
        flash("A deposit has already been paid on this booking, so it can't be cancelled here. Use \"Report a problem\" and an administrator will help.", "danger"); return redirect(_link(b))
    b.status = new
    if new == "accepted":
        b.deposit_status = "awaiting" if (b.deposit_amount or 0) > 0 else "none"
    if new == "completed":
        b.balance_status = "unpaid" if b.balance_amount > 0 else "confirmed"
    db.session.commit()
    num = b.provider.payment_number or "the provider's number (ask in chat)"
    msgs = {
        "accepted": ("Booking accepted", f"Your request for '{t}' was accepted. " + ((f"Pay the {kes(b.deposit_amount)} deposit from the booking page: you will get an M-Pesa prompt on your phone. It is held safely until the job is done." if mpesa.enabled() else f"Pay the {kes(b.deposit_amount)} deposit to {num} by M-Pesa, then enter the transaction code on the booking page.") if b.deposit_status == "awaiting" else "No deposit is needed."), b.customer_id),
        "rejected": ("Booking declined", f"Your request for '{t}' was declined.", b.customer_id),
        "completed": ("Service completed", f"'{t}' was marked completed. " + (f"Please pay the balance of {kes(b.balance_amount)} and leave a review." if b.balance_status == "unpaid" else "You can now leave a review."), b.customer_id),
        "cancelled": ("Booking cancelled", f"{(b.customer if current_user.role == 'customer' else b.provider).full_name} cancelled the booking for '{t}'.", b.provider_id if current_user.role == "customer" else b.customer_id)}
    title, msg, to = msgs[new]
    notify(to, title, msg, _link(b)); flash(f"Booking {new}.", "success")
    return redirect(_link(b))


# ---------------- deposit and balance (M-Pesa codes are entered by the customer and confirmed by the provider)
@bp.route("/bookings/<int:bid>/pay/<kind>", methods=["POST"])
@roles_required("customer")
def pay(bid, kind):
    b = db.session.get(Booking, bid) or abort(404)
    if b.customer_id != current_user.id or kind not in ("deposit", "balance"): abort(403)
    ok_state = (b.status == "accepted" and b.deposit_status == "awaiting") if kind == "deposit" else (b.status == "completed" and b.balance_status == "unpaid")
    if not ok_state:
        flash("No payment is due on this booking right now.", "danger"); return redirect(_link(b))
    if mpesa.enabled():
        flash("Payments are made with the M-Pesa prompt on this page. Press the Pay button.", "warning"); return redirect(_link(b))
    code = request.form.get("code", "").strip().upper()
    if not MPESA_CODE.match(code):
        flash("Enter the 10-character M-Pesa transaction code from your confirmation message (for example QGH7K2L9MN).", "danger"); return redirect(_link(b))
    used = Booking.query.filter(db.or_(Booking.deposit_code == code, Booking.balance_code == code)).first()
    if used:
        flash("That transaction code has already been used. Enter the code from your own payment.", "danger"); return redirect(_link(b))
    amount = b.deposit_amount if kind == "deposit" else b.balance_amount
    if kind == "deposit": b.deposit_status, b.deposit_code = "claimed", code
    else: b.balance_status, b.balance_code = "claimed", code
    db.session.commit()
    notify(b.provider_id, f"{kind.capitalize()} payment reported", f"{current_user.full_name} says they paid {kes(amount)} (code {code}) for '{b.listing.title}'. Check your M-Pesa and confirm.", _link(b))
    flash("Thanks. The provider has been asked to confirm they received it.", "success")
    return redirect(_link(b))


# ---------------- M-Pesa STK Push (money is held by the platform; see services/mpesa.py)
def _due(b, kind):
    return (b.status == "accepted" and b.deposit_status == "awaiting") if kind == "deposit" else (b.status == "completed" and b.balance_status == "unpaid")


@bp.route("/bookings/<int:bid>/stk/<kind>", methods=["POST"])
@roles_required("customer")
@limiter.limit("6 per 10 minutes", methods=["POST"])
def stk(bid, kind):
    b = db.session.get(Booking, bid) or abort(404)
    if b.customer_id != current_user.id or kind not in ("deposit", "balance"): abort(403)
    if not mpesa.enabled():
        flash("Online M-Pesa payment is not switched on. Pay the provider and enter the code instead.", "warning"); return redirect(_link(b))
    if not _due(b, kind):
        flash("No payment is due on this booking right now.", "danger"); return redirect(_link(b))
    phone = normalize_phone(request.form.get("phone", "") or b.customer_phone)
    if not phone:
        flash("Enter the M-Pesa phone number to charge (for example 0712 345 678).", "danger"); return redirect(_link(b))
    last = Payment.query.filter_by(booking_id=b.id, kind=kind, status="pending").order_by(Payment.id.desc()).first()
    if last and (datetime.utcnow() - last.created_at).total_seconds() < 90:
        flash("A payment prompt was just sent to your phone. Enter your M-Pesa PIN, then press \"I have paid, check now\".", "info"); return redirect(_link(b))
    amount = math.ceil(b.deposit_amount if kind == "deposit" else b.balance_amount)
    if amount < 1:
        flash("Nothing to pay.", "danger"); return redirect(_link(b))
    try:
        r = mpesa.stk_push(phone, amount, f"BOOKING{b.id}", f"{kind} #{b.id}")
    except Exception as e:
        current_app.logger.warning("STK push failed: %s", e)
        flash("We could not reach M-Pesa just now. Please try again in a minute.", "danger"); return redirect(_link(b))
    if str(r.get("ResponseCode")) != "0" or not r.get("CheckoutRequestID"):
        flash("M-Pesa did not accept the request: " + str(r.get("errorMessage") or r.get("ResponseDescription") or "unknown error"), "danger"); return redirect(_link(b))
    db.session.add(Payment(booking_id=b.id, kind=kind, amount=amount, phone=mpesa.msisdn(phone),
                           checkout_request_id=r["CheckoutRequestID"], merchant_request_id=r.get("MerchantRequestID")))
    db.session.commit()
    flash(f"Check your phone ({phone}) and enter your M-Pesa PIN to pay {kes(amount)}. This page updates by itself, or press \"I have paid, check now\".", "success")
    return redirect(_link(b))


@bp.route("/bookings/<int:bid>/stk-check", methods=["POST"])
@roles_required("customer")
@limiter.limit("20 per 10 minutes", methods=["POST"])
def stk_check(bid):
    b = db.session.get(Booking, bid) or abort(404)
    if b.customer_id != current_user.id: abort(403)
    p = Payment.query.filter_by(booking_id=b.id, status="pending").order_by(Payment.id.desc()).first()
    if not p:
        flash("No payment is waiting.", "info"); return redirect(_link(b))
    try:
        r = mpesa.stk_query(p.checkout_request_id)
    except Exception:
        flash("M-Pesa is still processing. Wait a few seconds and press the button again.", "info"); return redirect(_link(b))
    code = str(r.get("ResultCode", ""))
    if code == "0":
        mpesa.apply_result(p, True, None, r.get("ResultDesc")); flash("Payment received. Thank you!", "success")
    elif code == "":
        flash("M-Pesa is still processing. Wait a few seconds and try again.", "info")
    else:
        mpesa.apply_result(p, False, None, r.get("ResultDesc") or "Cancelled"); flash("The payment was not completed. You can try again.", "warning")
    return redirect(_link(b))


@bp.route("/mpesa/callback/<secret>", methods=["POST"])
@limiter.exempt
def mpesa_callback(secret):
    want = current_app.config.get("MPESA_CALLBACK_SECRET") or ""
    if not want or not hmac.compare_digest(secret, want): abort(404)
    ok_reply = jsonify(ResultCode=0, ResultDesc="Accepted")
    data = (request.get_json(silent=True) or {}).get("Body", {}).get("stkCallback", {})
    p = Payment.query.filter_by(checkout_request_id=data.get("CheckoutRequestID")).first()
    if not p: return ok_reply
    items = {i.get("Name"): i.get("Value") for i in (data.get("CallbackMetadata") or {}).get("Item", [])}
    success = str(data.get("ResultCode")) == "0"
    mpesa.apply_result(p, success, items.get("MpesaReceiptNumber"), data.get("ResultDesc"), items.get("Amount"))
    return ok_reply


@bp.route("/bookings/<int:bid>/confirm/<kind>", methods=["POST"])
@roles_required("provider")
def confirm_payment(bid, kind):
    b = db.session.get(Booking, bid) or abort(404)
    if b.provider_id != current_user.id or kind not in ("deposit", "balance"): abort(403)
    claimed = (b.deposit_status if kind == "deposit" else b.balance_status) == "claimed"
    if not claimed:
        flash("There is no payment waiting for confirmation.", "danger"); return redirect(_link(b))
    reject = request.form.get("decision") == "not_received"
    if kind == "deposit": b.deposit_status, b.deposit_code = ("awaiting", None) if reject else ("confirmed", b.deposit_code)
    else: b.balance_status, b.balance_code = ("unpaid", None) if reject else ("confirmed", b.balance_code)
    db.session.commit()
    t = b.listing.title
    if reject:
        notify(b.customer_id, f"{kind.capitalize()} not received", f"The provider could not find your {kind} payment for '{t}'. Check the code and try again, or message them in the chat.", _link(b))
        flash("Marked as not received. The customer was asked to check the code.", "warning")
    elif kind == "deposit":
        notify(b.customer_id, "Deposit confirmed", f"Your deposit for '{t}' was confirmed. The provider can start the work.", _link(b)); flash("Deposit confirmed. You can start the work.", "success")
    else:
        notify(b.customer_id, "Payment complete", f"Your final payment for '{t}' was confirmed. Thank you! Please leave a review.", _link(b)); flash("Payment confirmed.", "success")
    return redirect(_link(b))


# ---------------- chat (only the booking's customer and provider; admins can read)
@bp.route("/bookings/<int:bid>/messages")
@login_required
def messages(bid):
    b = _booking_for(bid)
    after = request.args.get("after", 0, type=int)
    rows = Message.query.filter(Message.booking_id == b.id, Message.id > after).order_by(Message.id).all()
    return jsonify(messages=[{"id": m.id, "mine": m.sender_id == current_user.id, "sender": m.sender.full_name,
                              "body": m.body, "time": m.created_at.strftime("%d %b %H:%M")} for m in rows])


@bp.route("/bookings/<int:bid>/chat", methods=["POST"])
@roles_required("customer", "provider")
@limiter.limit("40 per minute", methods=["POST"])
def send_message(bid):
    b = _booking_for(bid, allow_admin=False)
    wants_json = request.headers.get("X-Requested-With") == "fetch"

    def fail(msg, code=400):
        if wants_json: return jsonify(error=msg), code
        flash(msg, "danger"); return redirect(_link(b) + "#chat")
    if b.status not in CHAT_STATUSES: return fail("Chat is closed for this booking.")
    body = request.form.get("body", "").strip()
    if not body: return fail("Write a message first.")
    if len(body) > 1000: return fail("Messages can be up to 1000 characters.")
    if b.status == "pending" and CONTACT_IN_TEXT.search(body):
        return fail("For everyone's safety, phone numbers and emails can't be shared until the provider accepts the booking. They are shared automatically after that.")
    m = Message(booking_id=b.id, sender_id=current_user.id, body=body); db.session.add(m); db.session.commit()
    other = b.provider_id if current_user.id == b.customer_id else b.customer_id
    link = _link(b)
    if not Notification.query.filter_by(user_id=other, title="New chat message", link=link, is_read=False).first():   # one alert until they read it
        notify(other, "New chat message", f"{current_user.full_name} sent you a message about '{b.listing.title}'.", link)
    if wants_json:
        return jsonify(ok=True, message={"id": m.id, "mine": True, "sender": current_user.full_name, "body": m.body, "time": m.created_at.strftime("%d %b %H:%M")})
    return redirect(link + "#chat")


@bp.route("/bookings/<int:bid>/report", methods=["POST"])
@roles_required("customer", "provider")
@limiter.limit("5 per hour", methods=["POST"])
def report(bid):
    b = _booking_for(bid, allow_admin=False)
    reason = request.form.get("reason", "").strip()
    if len(reason) < 5:
        flash("Please describe the problem (at least a few words).", "danger"); return redirect(_link(b))
    for a in User.query.filter_by(role="admin").all():
        notify(a.id, "Booking reported", f"{current_user.full_name} ({current_user.role}) reported booking #{b.id} '{b.listing.title}': {reason[:300]}", _link(b))
    flash("Thank you. An administrator has been notified and can read the chat for this booking.", "success")
    return redirect(_link(b))


@bp.route("/bookings/<int:bid>/review", methods=["GET", "POST"])
@roles_required("customer")
def review(bid):
    b = db.session.get(Booking, bid) or abort(404)
    if b.customer_id != current_user.id: abort(403)
    if b.status != "completed": flash("You can only review completed services.", "danger"); return redirect(url_for("bookings.mine"))
    if b.review: flash("You already reviewed this booking.", "warning"); return redirect(url_for("bookings.mine"))
    if request.method == "POST":
        rating, comment = request.form.get("rating", type=int), request.form.get("comment", "").strip()
        if not rating or not 1 <= rating <= 5: flash("Choose a rating from 1 to 5 stars.", "danger")
        elif len(comment) < 3: flash("Write a short comment about the service.", "danger")
        else:
            db.session.add(Review(booking_id=b.id, customer_id=current_user.id, provider_id=b.provider_id, rating=rating, comment=comment[:1000])); db.session.commit()
            notify(b.provider_id, "New review received", f"{current_user.full_name} left a {rating}-star review for '{b.listing.title}'.", url_for("bookings.my_reviews"))
            flash("Thanks! Your review was posted.", "success"); return redirect(url_for("bookings.mine"))
    return render_template("review_form.html", b=b)


@bp.route("/reviews")
@roles_required("customer", "provider")
def my_reviews():
    col = Review.provider_id if current_user.role == "provider" else Review.customer_id
    return render_template("reviews.html", reviews=Review.query.filter(col == current_user.id).order_by(Review.created_at.desc()).all())


@bp.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    if request.method == "POST":
        nid = request.form.get("id", type=int)
        qy = Notification.query.filter_by(user_id=current_user.id, is_read=False)
        (qy.filter_by(id=nid) if nid else qy).update({"is_read": True}); db.session.commit()
        return redirect(url_for("bookings.notifications"))
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    return render_template("notifications.html", items=items)


@bp.route("/notifications/count")
@login_required
def count():
    return jsonify(unread=Notification.query.filter_by(user_id=current_user.id, is_read=False).count())
