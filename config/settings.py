import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

_user = os.getenv("MYSQL_USER",     "root")
_pw   = os.getenv("MYSQL_PASSWORD", "Pb@pritam#PB")
_host = os.getenv("MYSQL_HOST",     "localhost")
_port = os.getenv("MYSQL_PORT",     "3306")
_db   = os.getenv("MYSQL_DB",       "ims_db")


class Config:
    SECRET_KEY       = os.getenv("SECRET_KEY", "ims-lalbagh-secret-2024-xyz")
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

    MAIL_SERVER         = os.getenv("MAIL_SERVER",  "smtp.gmail.com")
    MAIL_PORT           = int(os.getenv("MAIL_PORT", "465"))
    MAIL_USE_TLS        = False
    MAIL_USE_SSL        = True
    MAIL_USERNAME       = os.getenv("MAIL_USERNAME", "lalbaghenterprises@gmail.com")
    MAIL_PASSWORD       = os.getenv("MAIL_PASSWORD", "lojn yuaa tcfn rqxa")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_USERNAME", "lalbaghenterprises@gmail.com")

    APP_TITLE     = "Inventory Management System"
    COMPANY_NAME  = "LALBAGH ENTERPRISE"
    COMPANY_ADDR  = "77, Omrahgang, Lalbagh, Murshidabad, West Bengal - 742149"
    COMPANY_GSTIN = "19AAAAA0000A1ZA"
    COMPANY_PHONE = "+91 99999 00000"
    COMPANY_UPI_ID = os.getenv("COMPANY_UPI_ID", "8927770267@okbizaxis")
    INVOICE_DIR   = os.getenv("INVOICE_DIR",   os.path.join(os.getcwd(), "invoices"))
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