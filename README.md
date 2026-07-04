# Inventory Management System — Flask + MySQL

## Project Structure
```
ims_flask/
├── run.py                    # Application entry point
├── config/
│   ├── __init__.py
│   └── settings.py           # All configuration (DB, mail, secrets)
├── app/
│   ├── __init__.py           # Flask app factory
│   ├── extensions.py         # db, mail, login_manager instances
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py           # User, Employee models
│   │   ├── supplier.py       # Supplier, PurchaseOrder, SupplierPayment
│   │   ├── product.py        # Product, CategoryGST
│   │   ├── customer.py       # Customer
│   │   ├── sales.py          # SalesMaster, SalesItem, Return
│   │   └── stock.py          # StockLog, AuditLog
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth.py           # Login, logout, OTP reset
│   │   ├── dashboard.py      # Home KPIs
│   │   ├── employees.py      # CRUD employees
│   │   ├── suppliers.py      # CRUD suppliers + payments
│   │   ├── products.py       # CRUD products + GST manager
│   │   ├── sales.py          # Cart, checkout, invoice PDF, returns
│   │   ├── customers.py      # CRUD customers + bulk mail
│   │   ├── reports.py        # Sales history, charts, profit, GST, forecast
│   │   └── stock.py          # Stock logs
│   ├── templates/            # Jinja2 HTML templates
│   └── static/               # CSS / JS / images
├── migrations/               # Flask-Migrate SQL migrations
└── requirements.txt
```

## Setup
```bash
pip install -r requirements.txt
flask db init
flask db migrate -m "initial"
flask db upgrade
flask run
```

## Default Login
- Username: `admin`  Password: `admin123`
