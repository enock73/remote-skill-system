from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from app.decorators import roles_required
from app.extensions import db
from app.models import Booking, SkillListing, Review, Notification
from app.services.notifications import notify

bp = Blueprint("bookings", __name__)
# who may move a booking, and from which status
TRANSITIONS = {"provider": {"pending": {"accepted", "rejected"}, "accepted": {"completed"}}, "customer": {"pending": {"cancelled"}}}


@bp.route("/book/<int:listing_id>", methods=["POST"])
@roles_required("customer")
def create(listing_id):
    l = db.session.get(SkillListing, listing_id) or abort(404)
    if not l.is_active or not l.provider.is_active_account: abort(404)
    try: when = datetime.strptime(request.form.get("requested_date", ""), "%Y-%m-%d").date()
    except ValueError: when = None
    if not when or when < date.today():
        flash("Choose a preferred date that is today or later.", "danger"); return redirect(url_for("main.service_detail", listing_id=l.id))
    b = Booking(customer_id=current_user.id, provider_id=l.provider_id, listing_id=l.id, requested_date=when, message=request.form.get("message", "").strip()[:1000])
    db.session.add(b); db.session.commit()
    notify(l.provider_id, "New booking request", f"{current_user.full_name} requested '{l.title}'.")
    flash("Booking request sent. You will be notified when the provider responds.", "success")
    return redirect(url_for("bookings.mine"))


@bp.route("/bookings")
@roles_required("customer", "provider")
def mine():
    col = Booking.provider_id if current_user.role == "provider" else Booking.customer_id
    qy = Booking.query.filter(col == current_user.id)
    status = request.args.get("status")
    if status: qy = qy.filter_by(status=status)
    return render_template("bookings.html", bookings=qy.order_by(Booking.created_at.desc()).all(), status=status)


@bp.route("/bookings/<int:bid>/<new>", methods=["POST"])
@roles_required("customer", "provider")
def set_status(bid, new):
    b = db.session.get(Booking, bid) or abort(404)
    owner = b.provider_id if current_user.role == "provider" else b.customer_id
    if owner != current_user.id: abort(403)
    if new not in {"provider": {"accepted", "rejected", "completed"}, "customer": {"cancelled"}}[current_user.role]: abort(403)
    if new not in TRANSITIONS[current_user.role].get(b.status, set()):
        flash(f"A {b.status} booking cannot be changed to {new}.", "danger"); return redirect(url_for("bookings.mine"))
    b.status = new; db.session.commit()
    t = b.listing.title
    title, msg, to = {
        "accepted": ("Booking accepted", f"Your request for '{t}' was accepted.", b.customer_id),
        "rejected": ("Booking declined", f"Your request for '{t}' was declined.", b.customer_id),
        "completed": ("Service completed", f"'{t}' was marked completed. You can now leave a review.", b.customer_id),
        "cancelled": ("Booking cancelled", f"{b.customer.full_name} cancelled their request for '{t}'.", b.provider_id)}[new]
    notify(to, title, msg); flash(f"Booking {new}.", "success")
    return redirect(url_for("bookings.mine"))


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
            notify(b.provider_id, "New review received", f"{current_user.full_name} left a {rating}-star review for '{b.listing.title}'.")
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
