import os
from datetime import timedelta
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-CHANGE-ME")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + os.path.join(basedir, "instance", "app.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", 120))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    SESSION_COOKIE_HTTPONLY = True
    # 'Lax' still allows same-site fetches (including cross-port localhost
    # during development, since SameSite ignores port) while blocking the
    # cookie from being sent on genuine cross-site requests — this is the
    # primary CSRF defence for this session-cookie API. Set to True when
    # served over HTTPS in production.
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    if SECRET_KEY == "dev-key-CHANGE-ME" and os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Set SECRET_KEY in production.")

    MAX_LOGIN_ATTEMPTS = int(os.environ.get("MAX_LOGIN_ATTEMPTS", 5))
    LOCKOUT_MINUTES = int(os.environ.get("LOCKOUT_MINUTES", 15))

    UPLOAD_FOLDER = os.path.join(basedir, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

    PAGE_SIZE = 12
    APP_NAME = os.environ.get('APP_NAME', 'Campus Skills Exchange')
    RATELIMIT_ENABLED = os.environ.get('RATELIMIT_ENABLED', '1') == '1'
    PUBLIC_APP_URL = os.environ.get('PUBLIC_APP_URL', '')
    SOCIAL = {k: os.environ.get('SOCIAL_' + k.upper(), '') for k in ('facebook', 'x', 'linkedin', 'instagram')}

    # ---- Email (any SMTP server, e.g. Gmail with an app password). Leave SMTP_HOST empty to disable email.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1") == "1"
    MAIL_FROM = os.environ.get("MAIL_FROM", "") or os.environ.get("SMTP_USER", "")

    # ---- SMS via Africa's Talking. Leave AT_API_KEY empty to disable SMS. Use AT_USERNAME=sandbox and AT_SANDBOX=1 to test.
    AT_USERNAME = os.environ.get("AT_USERNAME", "")
    AT_API_KEY = os.environ.get("AT_API_KEY", "")
    AT_SENDER_ID = os.environ.get("AT_SENDER_ID", "")
    AT_SANDBOX = os.environ.get("AT_SANDBOX", "0") == "1"

    # Deposit rules
    MIN_DEPOSIT_PERCENT = int(os.environ.get("MIN_DEPOSIT_PERCENT", 10))
    DEFAULT_DEPOSIT_PERCENT = int(os.environ.get("DEFAULT_DEPOSIT_PERCENT", 30))

    # ---- M-Pesa STK Push (Safaricom Daraja). Leave MPESA_CONSUMER_KEY empty to keep the manual "enter the M-Pesa code" flow.
    # Money is paid to YOUR shortcode (the platform) and held until the provider is paid out.
    MPESA_ENV = os.environ.get("MPESA_ENV", "sandbox")                 # sandbox or production
    MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "")
    MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "")
    MPESA_SHORTCODE = os.environ.get("MPESA_SHORTCODE", "174379")      # sandbox default
    MPESA_PASSKEY = os.environ.get("MPESA_PASSKEY", "")
    MPESA_TILL_NUMBER = os.environ.get("MPESA_TILL_NUMBER", "")        # Buy Goods only: the till that receives the money (MPESA_SHORTCODE is then the Store number)
    MPESA_TRANSACTION_TYPE = os.environ.get("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline")   # CustomerBuyGoodsOnline for a till
    MPESA_CALLBACK_SECRET = os.environ.get("MPESA_CALLBACK_SECRET", "")   # random text; part of the callback URL so strangers cannot fake payments
    COMMISSION_PERCENT = float(os.environ.get("COMMISSION_PERCENT", 0))   # platform fee kept from each payout

    # ---- Provider verification
    # Providers must be verified before they can list services and before customers can see or book them.
    REQUIRE_VERIFICATION = os.environ.get("REQUIRE_VERIFICATION", "1") == "1"
    # AI document check (Claude reads the ID photo). Leave ANTHROPIC_API_KEY empty to send every submission to an administrator instead.
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    # 1 = a submission that passes every AI check is approved at once. 0 = it waits for one-click admin approval (safer).
    VERIFY_AUTO_APPROVE = os.environ.get("VERIFY_AUTO_APPROVE", "0") == "1"
