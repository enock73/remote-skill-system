from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import current_user
from app.decorators import roles_required
from app.extensions import db
from app.models import SkillListing, Category
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
