from datetime import date, timedelta
from flask import Blueprint, render_template, jsonify, make_response
from flask_login import login_required, current_user
from sqlalchemy import func, text

from ..extensions import db
from ..models.user     import User, Employee
from ..models.product  import Product
from ..models.supplier import Supplier
from ..models.sales    import SalesMaster
from ..models.stock    import AuditLog

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@dashboard_bp.route("/dashboard")
@login_required
def home():
    return render_template("dashboard/home.html")


@dashboard_bp.route("/api/kpis")
@login_required
def api_kpis():
    try:
        today = date.today().isoformat()

        total_employees = Employee.query.count()
        total_products  = Product.query.count()
        total_suppliers = Supplier.query.count()

        todays_sales = db.session.execute(text(
            "SELECT IFNULL(SUM(grand_total),0) FROM sales_master "
            "WHERE DATE(date) = :today"
        ), {"today": today}).scalar() or 0.0

        low_stock = Product.query.filter(
            Product.quantity < Product.reorder_level
        ).count()

        inventory_value = db.session.execute(text(
            "SELECT IFNULL(SUM(quantity * cost_price),0) FROM products"
        )).scalar() or 0.0

        return jsonify(
            success=True,
            total_employees=total_employees,
            total_products=total_products,
            total_suppliers=total_suppliers,
            todays_sales=round(float(todays_sales), 2),
            low_stock_count=low_stock,
            inventory_value=round(float(inventory_value), 2),
        )
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@dashboard_bp.route("/api/sales-chart")
@login_required
def api_sales_chart():
    try:
        start = (date.today() - timedelta(days=13)).isoformat()
        rows  = db.session.execute(text("""
            SELECT DATE(date) AS day,
                   IFNULL(SUM(grand_total),0) AS total
            FROM sales_master
            WHERE DATE(date) >= :start
            GROUP BY DATE(date)
            ORDER BY DATE(date)
        """), {"start": start}).fetchall()

        data   = {str(r[0]): float(r[1]) for r in rows}
        dates  = [(date.today() - timedelta(days=13-i)).isoformat()
                  for i in range(14)]
        totals = [data.get(d, 0.0) for d in dates]
        return jsonify(success=True, dates=dates, totals=totals)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@dashboard_bp.route("/api/online-users")
@login_required
def api_online_users():
    if current_user.role != "Admin":
        return jsonify(success=False, message="Admin only"), 403
    try:
        users = User.query.order_by(User.role.desc(), User.username).all()
        return jsonify(success=True, users=[{
            "username":   u.username,
            "role":       u.role,
            "is_online":  u.is_online,
            "last_login": u.last_login.isoformat() if u.last_login else "",
        } for u in users])
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@dashboard_bp.route("/api/low-stock-alerts")
@login_required
def api_low_stock():
    try:
        items = Product.query.filter(
            Product.quantity < Product.reorder_level
        ).all()
        return jsonify(success=True, items=[{
            "name":          p.name,
            "quantity":      p.quantity,
            "reorder_level": p.reorder_level,
        } for p in items])
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@dashboard_bp.route("/offline")
def offline():
    """Offline fallback page served by the service worker."""
    resp = make_response(render_template("offline.html"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@dashboard_bp.route("/manifest.json")
def manifest():
    """Serve manifest with correct MIME type (some servers miss this)."""
    from flask import send_from_directory, current_app
    resp = make_response(
        send_from_directory(current_app.static_folder, "manifest.json")
    )
    resp.headers["Content-Type"] = "application/manifest+json"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
