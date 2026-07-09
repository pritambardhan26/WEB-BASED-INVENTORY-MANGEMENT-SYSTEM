import os
import secrets
import warnings
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

_user = os.getenv("MYSQL_USER", "root")
_pw   = os.getenv("MYSQL_PASSWORD")
_host = os.getenv("MYSQL_HOST", "localhost")
_port = os.getenv("MYSQL_PORT", "3306")
_db   = os.getenv("MYSQL_DB",   "ims_db")

if not _pw:
    raise RuntimeError(
        "MYSQL_PASSWORD is not set. Add it to your .env file "
        "(see .env.example) — no default credential is provided."
    )

_secret_key = os.getenv("SECRET_KEY")
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    warnings.warn(
        "SECRET_KEY is not set in the environment — using a randomly "
        "generated key for this process only. Set SECRET_KEY in your "
        ".env file for persistent sessions and in production.",
        RuntimeWarning,
    )


class Config:
    SECRET_KEY       = _secret_key
    WTF_CSRF_ENABLED = True

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{_user}:{quote_plus(_pw)}"
        f"@{_host}:{_port}/{_db}?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle":  300,
    }

    # ── Mailjet (API-based mail sending, replaces SMTP) ────────
    MAILJET_API_KEY      = os.getenv("MAILJET_API_KEY", "")
    MAILJET_API_SECRET   = os.getenv("MAILJET_API_SECRET", "")
    MAILJET_SENDER_EMAIL = os.getenv("MAILJET_SENDER_EMAIL", "lalbaghenterprises@gmail.com")
    MAILJET_SENDER_NAME  = os.getenv("MAILJET_SENDER_NAME", "LALBAGH ENTERPRISE")

    APP_TITLE     = "Inventory Management System"
    COMPANY_NAME  = "LALBAGH ENTERPRISE"
    COMPANY_ADDR  = "77, Omrahgang, Lalbagh, Murshidabad, West Bengal - 742149"
    COMPANY_GSTIN = "19AAAAA0000A1ZA"
    COMPANY_PHONE = "+91 99999 00000"
    COMPANY_UPI_ID = os.getenv("COMPANY_UPI_ID", "8927770267@okbizaxis")
    INVOICE_DIR   =  os.getenv("INVOICE_DIR", "/data/invoices")
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))


class DevelopmentConfig(Config):
    DEBUG           = True
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    DEBUG = False


config = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig,
}
ADMIN_REPORT_EMAIL = os.getenv("ADMIN_REPORT_EMAIL", "pritamardhan99@gmail.com")