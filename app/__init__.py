import os
from flask import Flask
from config.settings import config
from .extensions import db, migrate, login_manager, mail, csrf


def create_app(env: str = "default") -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config[env])

    # ── Create required directories ───────────────────────────
    for d in [app.config["INVOICE_DIR"], app.config["UPLOAD_FOLDER"]]:
        os.makedirs(d, exist_ok=True)

    # ── Init extensions ───────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)

    # ── Register models (so Flask-Migrate sees them) ──────────
    with app.app_context():
        from .models import user, supplier, product, customer, sales, stock  # noqa

    # ── Register blueprints ───────────────────────────────────
    from .routes.auth       import auth_bp
    from .routes.dashboard  import dashboard_bp
    from .routes.employees  import employees_bp
    from .routes.suppliers  import suppliers_bp
    from .routes.products   import products_bp
    from .routes.sales      import sales_bp
    from .routes.customers  import customers_bp
    from .routes.reports    import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(reports_bp)

    # ── Seed default data ─────────────────────────────────────
    with app.app_context():
        _seed_defaults()

    return app


def _seed_defaults():
    """Seed admin user and default GST categories if missing."""
    from .models.user import User, Employee
    from .models.product import CategoryGST
    import bcrypt

    db.create_all()

    # Admin user
    if not User.query.filter_by(username="admin").first():
        hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        admin  = User(
            username="admin",
            password=hashed,
            email="admin@gmail.com",
            role="Admin",
        )
        db.session.add(admin)

    # Default GST categories
    defaults = {
        "Grocery": 5, "Electronics": 18, "Stationery": 5,
        "Medicine": 0, "Clothing": 18, "Luxury": 40,
    }
    for cat, gst in defaults.items():
        if not CategoryGST.query.filter_by(category=cat).first():
            db.session.add(CategoryGST(category=cat, gst=gst))

    db.session.commit()
