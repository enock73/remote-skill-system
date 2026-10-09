from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import current_user
from app.decorators import roles_required
from app.extensions import db
from app.models import SkillListing, Category, User, PortfolioPhoto, Notification
from app.extensions import limiter
from app.services import idcheck
from app.services.files import save_private_image, save_public_image, delete_file
from app.services.notifications import notify
from datetime import datetime
import os, re
from app.routes.auth import save_image

bp = Blueprint("provider", __name__, url_prefix="/provider")


def _own(lid):
    l = db.session.get(SkillListing, lid) or abort(404)
    if l.provider_id != current_user.id: abort(403)
    return l


@bp.route("/services")
@roles_required("provider")
def listings():
    return render_template("provider/listings.html", items=SkillListing.query.filter_by(provider_id=current_user.id).order_by(SkillListing.created_at.desc()).all())


def _form(l=None):
    if current_app.config["REQUIRE_VERIFICATION"] and not current_user.is_verified:
        flash("Verify your identity first. Only verified providers can list services.", "warning")
        return redirect(url_for("provider.verification"))
    errors, f = {}, request.form
    if request.method == "POST":
        title, desc = f.get("title", "").strip(), f.get("description", "").strip()
        cat = db.session.get(Category, f.get("category_id", type=int)) if f.get("category_id") else None
        try: price = float(f.get("price", "")); assert price >= 0
        except (ValueError, AssertionError): price = None; errors["price"] = "Enter a valid, non-negative price."
        if not title: errors["title"] = "Title is required."
        if not desc: errors["description"] = "Description is required."
        if not cat: errors["category_id"] = "Select a category."
        if not f.get("location", "").strip(): errors["location"] = "Location is required."
        mode = f.get("service_mode", "both")
        shop = f.get("shop_address", "").strip()
        if mode not in ("shop", "visit", "both"): mode = "both"
        if mode in ("shop", "both") and len(shop) < 5: errors["shop_address"] = "Enter your shop address (area, street, building) so customers can find you."
        try:
            deposit = int(f.get("deposit_percent", ""))
            lo = current_app.config["MIN_DEPOSIT_PERCENT"]
            assert lo <= deposit <= 100
        except (ValueError, AssertionError):
            deposit = None; errors["deposit_percent"] = f"Deposit must be a whole number from {current_app.config['MIN_DEPOSIT_PERCENT']} to 100."
        if not current_user.payment_number:
            errors["payment"] = "Add your phone / M-Pesa number on your Profile first, so customers know where to send the deposit."
        if not errors:
            l = l or SkillListing(provider_id=current_user.id)
            l.title, l.description, l.category_id, l.price = title[:150], desc[:3000], cat.id, price
            l.price_unit = (f.get("price_unit", "").strip() or "per job")[:30]
            l.service_mode, l.shop_address, l.deposit_percent = mode, (shop[:255] if mode in ("shop", "both") else None), deposit
            l.location, l.availability = f["location"].strip()[:120], f.get("availability", "").strip()[:120]
            vals = f.getlist("is_active")
            l.is_active = True if not vals else ("1" in vals)
            img = save_image(request.files.get("image"))
            if img: l.image = img
            db.session.add(l); db.session.commit(); flash("Service saved.", "success")
            return redirect(url_for("provider.listings"))
    return render_template("provider/listing_form.html", l=l, errors=errors, f=f if request.method == "POST" else {}, cats=Category.query.order_by(Category.name).all())


@bp.route("/services/new", methods=["GET", "POST"])
@roles_required("provider")
def listing_new(): return _form()


@bp.route("/services/<int:lid>/edit", methods=["GET", "POST"])
@roles_required("provider")
def listing_edit(lid): return _form(_own(lid))


@bp.route("/services/<int:lid>/delete", methods=["POST"])
@roles_required("provider")
def listing_delete(lid):
    db.session.delete(_own(lid)); db.session.commit(); flash("Service deleted.", "success")
    return redirect(url_for("provider.listings"))


@bp.route("/services/<int:lid>/toggle", methods=["POST"])
@roles_required("provider")
def listing_toggle(lid):
    l = _own(lid); l.is_active = not l.is_active; db.session.commit()
    flash("Service is now active and visible." if l.is_active else "Service hidden from search.", "success")
    return redirect(url_for("provider.listings"))


# ---------------- identity verification (private documents, reviewed by an admin)
ID_RE = re.compile(r"^\d{7,8}$")   # Kenyan national ID numbers are 7 or 8 digits
MAX_PHOTOS = 12


@bp.route("/verification", methods=["GET", "POST"])
@roles_required("provider")
@limiter.limit("5 per day", methods=["POST"])
def verification():
    u = current_user
    if request.method == "POST":
        if u.verification_status in ("pending", "approved"):
            flash("Your verification is already " + ("being checked." if u.verification_status == "pending" else "approved."), "info"); return redirect(url_for("provider.verification"))
        if request.form.get("consent") != "1":
            flash("Tick the box to allow us to check your ID.", "danger"); return redirect(url_for("provider.verification"))
        idn = request.form.get("id_number", "").replace(" ", "")
        if not ID_RE.match(idn):
            flash("Enter your Kenyan national ID number (7 or 8 digits).", "danger"); return redirect(url_for("provider.verification"))
        if User.query.filter(User.id_number == idn, User.id != u.id, User.verification_status.in_(("pending", "approved"))).first():
            flash("That ID number is already used on another account. If this is a mistake, contact the administrator.", "danger"); return redirect(url_for("provider.verification"))
        idp, e1 = save_private_image(request.files.get("id_photo")); selfie, e2 = save_private_image(request.files.get("selfie_photo"))
        if e1 or e2:
            delete_file("PRIVATE_FOLDER", idp); delete_file("PRIVATE_FOLDER", selfie)
            flash("ID photo: " + e1 if e1 else "Selfie: " + e2, "danger"); return redirect(url_for("provider.verification"))
        for old in (u.id_photo, u.selfie_photo): delete_file("PRIVATE_FOLDER", old)
        u.id_number, u.id_photo, u.selfie_photo = idn, idp, selfie
        u.verification_submitted_at, u.verification_note, u.verification_report = datetime.utcnow(), None, None
        verdict, note = "review", "AI check is not switched on."
        if idcheck.enabled():
            try:
                folder = current_app.config["PRIVATE_FOLDER"]
                verdict, note = idcheck.evaluate(idcheck.analyze(os.path.join(folder, idp), os.path.join(folder, selfie)), idn, u.full_name)
            except Exception as e:
                current_app.logger.warning("ID AI check failed: %s", e)
                verdict, note = "review", "AI check was unavailable, so an administrator will check it."
        u.verification_report = f"AI: {verdict}. {note}"[:1000]
        if verdict == "fail":
            u.verification_status, u.verification_note, u.is_verified = "rejected", note, False
            db.session.commit(); flash("Not approved: " + note, "danger"); return redirect(url_for("provider.verification"))
        if verdict == "pass" and current_app.config["VERIFY_AUTO_APPROVE"]:
            u.verification_status, u.is_verified = "approved", True
            db.session.commit(); notify(u.id, "You're verified!", "Your ID checks passed. You can now list services.", url_for("provider.listing_new"))
            flash("You are verified. You can now list your services.", "success"); return redirect(url_for("provider.listing_new"))
        u.verification_status = "pending"; db.session.commit()
        for a in User.query.filter_by(role="admin").all():
            notify(a.id, "Verification to review", f"{u.full_name} submitted ID documents. {u.verification_report}", url_for("admin.verifications"), sms=False)
        flash("Submitted. Your documents passed the first checks and are waiting for final approval." if verdict == "pass" else "Submitted. An administrator will review your documents.", "success")
        return redirect(url_for("provider.verification"))
    return render_template("provider/verification.html")


# ---------------- work photos (public portfolio)
@bp.route("/photos", methods=["GET", "POST"])
@roles_required("provider")
def photos():
    if request.method == "POST":
        files = [f for f in request.files.getlist("photos") if f and f.filename]
        room = MAX_PHOTOS - PortfolioPhoto.query.filter_by(provider_id=current_user.id).count()
        if not files: flash("Choose at least one photo.", "danger")
        elif len(files) > room: flash(f"You can have up to {MAX_PHOTOS} work photos. You can add {max(room, 0)} more; delete older ones first.", "danger")
        else:
            caption, added = request.form.get("caption", "").strip()[:120], 0
            for f in files:
                name, err = save_public_image(f)
                if err: flash(f"{f.filename}: {err}", "danger"); continue
                db.session.add(PortfolioPhoto(provider_id=current_user.id, filename=name, caption=caption or None)); added += 1
            db.session.commit()
            if added: flash(f"{added} photo{'s' if added != 1 else ''} added to your profile.", "success")
        return redirect(url_for("provider.photos"))
    return render_template("provider/photos.html", photos=PortfolioPhoto.query.filter_by(provider_id=current_user.id).order_by(PortfolioPhoto.id.desc()).all(), max_photos=MAX_PHOTOS)


@bp.route("/photos/<int:pid>/delete", methods=["POST"])
@roles_required("provider")
def photo_delete(pid):
    p = db.session.get(PortfolioPhoto, pid) or abort(404)
    if p.provider_id != current_user.id: abort(403)
    delete_file("UPLOAD_FOLDER", p.filename); db.session.delete(p); db.session.commit()
    flash("Photo removed.", "success")
    return redirect(url_for("provider.photos"))
