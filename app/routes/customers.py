import re
import statistics
from collections import Counter
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from ..extensions import db
from ..services.mailer import send_personalized_bulk_mail
from ..models.customer import Customer
from ..models.sales import SalesMaster, SalesItem

customers_bp = Blueprint("customers", __name__, url_prefix="/customers")


# ================= HELPERS =================
def _segment(total):
    if total >= 50000:
        return "VIP"
    if total >= 10000:
        return "Regular"
    return "New"


# ================= PAGE =================
@customers_bp.route("/")
@login_required
def index():
    return render_template("customers/index.html")


# ================= LIST =================
@customers_bp.route("/api/list")
@login_required
def api_list():
    q = f"%{request.args.get('q', '').strip()}%"
    customers = Customer.query.filter(
        db.or_(
            Customer.name.ilike(q),
            Customer.phone.ilike(q),
            Customer.email.ilike(q)
        )
    ).order_by(Customer.name).all()

    return jsonify(success=True, customers=[c.to_dict() for c in customers])


# ================= CREATE / UPDATE =================
@customers_bp.route("/api/save", methods=["POST"])
@login_required
def api_save():
    try:
        data = request.get_json(silent=True) or {}

        cid   = str(data.get("customer_id", "")).strip()
        name  = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        email = str(data.get("email", "")).strip()

        if not cid or not name:
            return jsonify(success=False, message="ID & Name required")

        # ===== VALIDATION =====
        if phone and not re.fullmatch(r"^[6-9]\d{9}$", phone):
            return jsonify(success=False, message="Invalid phone")

        if email and not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            return jsonify(success=False, message="Invalid email")

        # ===== DUPLICATE CHECK =====
        if phone:
            dup = Customer.query.filter(
                Customer.phone == phone,
                Customer.customer_id != cid
            ).first()
            if dup:
                return jsonify(success=False, message="Phone already exists")

        if email:
            dup = Customer.query.filter(
                Customer.email == email,
                Customer.customer_id != cid
            ).first()
            if dup:
                return jsonify(success=False, message="Email already exists")

        existing = Customer.query.get(cid)

        if existing:
            existing.name  = name
            existing.phone = phone or None
            existing.email = email or None
            msg = "Updated"
        else:
            db.session.add(Customer(
                customer_id=cid,
                name=name,
                phone=phone or None,
                email=email or None
            ))
            msg = "Created"

        db.session.commit()
        return jsonify(success=True, message=msg)

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


# ================= DELETE =================
@customers_bp.route("/api/delete/<cid>", methods=["DELETE"])
@login_required
def api_delete(cid):
    try:
        cust = Customer.query.get(cid)
        if not cust:
            return jsonify(success=False, message="Not found")

        db.session.delete(cust)
        db.session.commit()

        return jsonify(success=True, message="Deleted")

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


# ================= DROPDOWN =================
@customers_bp.route("/api/for-select")
@login_required
def api_for_select():
    rows = Customer.query.order_by(Customer.name).limit(200).all()

    return jsonify(success=True, customers=[{
        "customer_id": c.customer_id,
        "label": f"{c.name} ({c.phone or 'No Phone'})",
        "phone": c.phone or "",
        "email": c.email or ""
    } for c in rows])


# ================= PURCHASE HISTORY =================
@customers_bp.route("/api/history/<cid>")
@login_required
def api_history(cid):
    try:
        cust = Customer.query.get(cid)
        if not cust:
            return jsonify(success=False, message="Customer not found")

        sales = SalesMaster.query.filter(
            db.or_(
                SalesMaster.customer_phone == cust.phone,
                SalesMaster.customer_name == cust.name
            )
        ).order_by(SalesMaster.date.desc()).all()

        result = []
        product_ctr = Counter()
        category_ctr = Counter()

        for s in sales:
            items = SalesItem.query.filter_by(sale_id=s.sale_id).all()

            for i in items:
                product_ctr[i.product_name] += i.quantity
                category_ctr[i.category or "Other"] += 1

            result.append({
                "sale_id": s.sale_id,
                "date": s.date.strftime("%Y-%m-%d %H:%M"),
                "total": float(s.grand_total)
            })

        total_spent = sum(float(s.grand_total) for s in sales)

        return jsonify(
            success=True,
            customer=cust.to_dict(),
            total_spent=round(total_spent, 2),
            visits=len(sales),
            segment=_segment(total_spent),
            top_product=product_ctr.most_common(1)[0][0] if product_ctr else None,
            top_category=category_ctr.most_common(1)[0][0] if category_ctr else None,
            history=result
        )

    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ================= ANALYTICS =================
@customers_bp.route("/api/analytics/<cid>")
@login_required
def api_analytics(cid):
    try:
        cust = Customer.query.get(cid)
        if not cust:
            return jsonify(success=False, message="Not found")

        sales = SalesMaster.query.filter(
            db.or_(
                SalesMaster.customer_phone == cust.phone,
                SalesMaster.customer_name == cust.name
            )
        ).all()

        total = sum(float(s.grand_total) for s in sales)
        avg = round(total / len(sales), 2) if sales else 0

        return jsonify(
            success=True,
            total_spent=round(total, 2),
            avg_order=avg,
            visits=len(sales),
            segment=_segment(total)
        )

    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ================= BULK MAIL (Mailjet API) =================
@customers_bp.route("/api/bulk-mail", methods=["POST"])
@login_required
def api_bulk_mail():
    if current_user.role != "Admin":
        return jsonify(success=False, message="Admin only")

    try:
        data = request.get_json(silent=True) or {}
        subject = data.get("subject", "IMS Notification")
        body = data.get("body", "")

        customers = Customer.query.filter(Customer.email.isnot(None)).all()

        entries = [
            (c.email, c.name, f"Dear {c.name},\n\n{body}\n\nIMS Team")
            for c in customers
        ]
        send_personalized_bulk_mail(subject, entries)

        return jsonify(success=True, message="Emails sent")

    except Exception as e:
        return jsonify(success=False, message=str(e)), 500