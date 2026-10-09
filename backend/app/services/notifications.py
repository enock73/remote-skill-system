"""In-app notifications plus optional email and SMS.

Email and SMS are sent in a background thread so a slow mail server never slows a page down.
Both are safe no-ops until you set the SMTP_* / AT_* environment variables, and a failure
here never breaks the request that triggered it."""
import json, re, smtplib, threading, urllib.parse, urllib.request
from email.message import EmailMessage
from flask import current_app
from app.extensions import db
from app.models import Notification, User


def normalize_phone(raw):
    """Turn 0712 345 678 / 712345678 / +254712345678 into +254712345678. Returns None if it doesn't look like a phone number."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+"):
        n = digits[1:]
    elif digits.startswith("254"):
        n = digits
    elif digits.startswith("0"):
        n = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        n = "254" + digits
    else:
        return None
    return "+" + n if re.fullmatch(r"\d{11,14}", n) else None


def _send_email(cfg, to, subject, body):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg["MAIL_FROM"], to
    msg.set_content(body)
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as s:
        if cfg["SMTP_USE_TLS"]:
            s.starttls()
        if cfg["SMTP_USER"]:
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
        s.send_message(msg)


def _send_sms(cfg, to, text):
    base = "https://api.sandbox.africastalking.com" if cfg["AT_SANDBOX"] else "https://api.africastalking.com"
    fields = {"username": cfg["AT_USERNAME"], "to": to, "message": text}
    if cfg["AT_SENDER_ID"]:
        fields["from"] = cfg["AT_SENDER_ID"]
    req = urllib.request.Request(base + "/version1/messaging", data=urllib.parse.urlencode(fields).encode(),
                                 headers={"apiKey": cfg["AT_API_KEY"], "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode() or "{}")


def _run_in_background(app, fn, *args):
    def job():
        try:
            fn(*args)
        except Exception as e:   # never let a mail/SMS problem surface to the user
            app.logger.warning("Notification delivery failed: %s", e)
    if app.config.get("TESTING_SYNC_NOTIFICATIONS"):
        job()
    else:
        threading.Thread(target=job, daemon=True).start()


def email_enabled(cfg): return bool(cfg.get("SMTP_HOST") and cfg.get("MAIL_FROM"))
def sms_enabled(cfg): return bool(cfg.get("AT_API_KEY") and cfg.get("AT_USERNAME"))


def send_email(to, subject, body):
    """Send one email (used for password resets too). Returns True if it was handed to the mail thread."""
    app = current_app._get_current_object()
    if not to or not email_enabled(app.config):
        return False
    cfg = {k: app.config[k] for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_USE_TLS", "MAIL_FROM")}
    _run_in_background(app, _send_email, cfg, to, subject, body)
    return True


def notify(user_id, title, message, link=None, sms=True, email=True):
    """Create the in-app notification, then also email/text the user if configured and they haven't opted out."""
    try:
        db.session.add(Notification(user_id=user_id, title=title, message=message[:500], link=link))
        db.session.commit()
    except Exception:
        db.session.rollback()
        return
    try:
        app = current_app._get_current_object()
        cfg, user = app.config, db.session.get(User, user_id)
        if not user:
            return
        site = cfg.get("PUBLIC_APP_URL", "").rstrip("/")
        if email and user.notify_email and email_enabled(cfg):
            url = f"\n\nOpen: {site}{link}" if (site and link) else ""
            send_email(user.email, f"{cfg.get('APP_NAME', 'Skills Exchange')}: {title}",
                       f"Hello {user.full_name},\n\n{message}{url}\n\n-- {cfg.get('APP_NAME', 'Skills Exchange')}\n"
                       f"(You can turn email alerts off on your Profile page.)")
        phone = normalize_phone(user.phone)
        if sms and phone and user.notify_sms and sms_enabled(cfg):
            sms_cfg = {k: cfg[k] for k in ("AT_USERNAME", "AT_API_KEY", "AT_SENDER_ID", "AT_SANDBOX")}
            _run_in_background(app, _send_sms, sms_cfg, phone, f"{cfg.get('APP_NAME', 'Skills Exchange')}: {message}"[:300])
    except Exception as e:
        current_app.logger.warning("Could not queue email/SMS: %s", e)