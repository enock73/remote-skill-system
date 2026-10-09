"""M-Pesa STK Push through Safaricom Daraja.

Customer pays with a prompt on their phone; the money goes to the platform's shortcode (escrow) and the
booking is updated automatically from Safaricom's callback (or from a status query if the callback is missed).
Without credentials in .env, enabled() is False and the app keeps the manual "enter the code" flow.
"""
import base64, json, time, urllib.request, urllib.parse
from datetime import datetime
from flask import current_app, url_for
from app.extensions import db

_token = {"value": None, "expires": 0}


def enabled():
    c = current_app.config
    return all(c.get(k) for k in ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_PASSKEY", "MPESA_CALLBACK_SECRET", "PUBLIC_APP_URL"))


def _base():
    return "https://api.safaricom.co.ke" if current_app.config["MPESA_ENV"] == "production" else "https://sandbox.safaricom.co.ke"


def _http(url, data=None, headers=None, timeout=20):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _access_token():
    if _token["value"] and _token["expires"] > time.time():
        return _token["value"]
    c = current_app.config
    cred = base64.b64encode(f"{c['MPESA_CONSUMER_KEY']}:{c['MPESA_CONSUMER_SECRET']}".encode()).decode()
    d = _http(_base() + "/oauth/v1/generate?grant_type=client_credentials", headers={"Authorization": "Basic " + cred})
    _token.update(value=d["access_token"], expires=time.time() + int(d.get("expires_in", 3599)) - 60)
    return _token["value"]


def _password(ts):
    c = current_app.config
    return base64.b64encode(f"{c['MPESA_SHORTCODE']}{c['MPESA_PASSKEY']}{ts}".encode()).decode()


def msisdn(phone):
    """+254712345678 -> 254712345678 (the format Daraja wants)."""
    return (phone or "").lstrip("+")


def callback_url():
    c = current_app.config
    return c["PUBLIC_APP_URL"].rstrip("/") + "/mpesa/callback/" + c["MPESA_CALLBACK_SECRET"]


def stk_push(phone, amount, reference, description):
    """Ask Safaricom to show a payment prompt on the phone. Returns the Daraja response dict."""
    c = current_app.config
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    payload = {"BusinessShortCode": c["MPESA_SHORTCODE"], "Password": _password(ts), "Timestamp": ts,
               "TransactionType": c["MPESA_TRANSACTION_TYPE"], "Amount": int(amount), "PartyA": msisdn(phone),
               "PartyB": c.get("MPESA_TILL_NUMBER") or c["MPESA_SHORTCODE"], "PhoneNumber": msisdn(phone), "CallBackURL": callback_url(),
               "AccountReference": reference[:12], "TransactionDesc": description[:13]}
    return _http(_base() + "/mpesa/stkpush/v1/processrequest", payload,
                 {"Authorization": "Bearer " + _access_token(), "Content-Type": "application/json"})


def stk_query(checkout_request_id):
    c = current_app.config
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    payload = {"BusinessShortCode": c["MPESA_SHORTCODE"], "Password": _password(ts), "Timestamp": ts, "CheckoutRequestID": checkout_request_id}
    return _http(_base() + "/mpesa/stkpushquery/v1/query", payload,
                 {"Authorization": "Bearer " + _access_token(), "Content-Type": "application/json"})


def apply_result(payment, ok, receipt=None, desc=None, paid_amount=None):
    """Record the outcome once. Safe to call twice (callback + status check). Returns True if state changed."""
    from app.models import Payment, Booking
    from app.services.notifications import notify
    if payment.status != "pending":
        return False
    if ok and paid_amount is not None and int(round(float(paid_amount))) != payment.amount:
        ok, desc = False, f"Amount mismatch (expected {payment.amount}, got {paid_amount})"
    if ok and receipt and Payment.query.filter(Payment.mpesa_receipt == receipt, Payment.id != payment.id).first():
        ok, desc = False, "Duplicate receipt"
    payment.status = "success" if ok else "failed"
    payment.mpesa_receipt = receipt if ok else None
    payment.result_desc = (desc or "")[:255]
    b = payment.booking
    title = b.listing.title
    link = url_for("bookings.detail", bid=b.id)
    if ok:
        if payment.kind == "deposit":
            receipt = receipt or f"STK{payment.id}"
            b.deposit_status, b.deposit_code = "confirmed", receipt
            notify(b.customer_id, "Deposit received", f"We received your KSh {payment.amount:,} deposit for '{title}' (receipt {receipt}). It is held safely until the job is done.", link)
            if b.status == "pending":
                notify(b.provider_id, "New booking request", f"{b.customer.full_name} requested '{title}' and already paid the KSh {payment.amount:,} deposit (held by the platform). Open it to accept or reject.", link)
            else:
                notify(b.provider_id, "Deposit secured", f"The customer paid the KSh {payment.amount:,} deposit for '{title}'. It is held by the platform. You can start the work.", link)
        else:
            receipt = receipt or f"STK{payment.id}"
            b.balance_status, b.balance_code = "confirmed", receipt
            total = sum(p.amount for p in b.payments if p.status == "success" or p.id == payment.id)
            fee = round(total * (current_app.config["COMMISSION_PERCENT"] or 0) / 100, 2)
            b.payout_status, b.payout_amount = "due", round(total - fee, 2)
            notify(b.customer_id, "Payment complete", f"Your final payment for '{title}' (receipt {receipt}) was received. Thank you! Please leave a review.", link)
            notify(b.provider_id, "Customer paid in full", f"'{title}' is fully paid. Your payout of KSh {b.payout_amount:,.0f} will be sent to your M-Pesa number by the platform.", link)
            from app.models import User
            for a in User.query.filter_by(role="admin").all():
                notify(a.id, "Payout due", f"Booking #{b.id} '{title}' is fully paid. Send KSh {b.payout_amount:,.0f} to {b.provider.payment_number}.", url_for("admin.payouts"), sms=False)
    else:
        notify(b.customer_id, "Payment not completed", f"Your {payment.kind} payment for '{title}' did not go through ({desc or 'cancelled'}). You can try again from the booking page.", link, sms=False)
    db.session.commit()
    return True
