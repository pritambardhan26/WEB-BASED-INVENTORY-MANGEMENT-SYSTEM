from datetime import date
from flask import (Blueprint, render_template, request,
                   jsonify, flash, redirect, url_for, current_app)
from flask_login import login_required, current_user
from flask_mail import Message

from ..extensions import db, mail
from ..models.user import User, Employee
import bcrypt
import re

employees_bp = Blueprint("employees", __name__, url_prefix="/employees")


def _admin_required():
    if current_user.role != "Admin":
        return jsonify(error="Admin access required"), 403


def _next_emp_id() -> str:
    last = (Employee.query.order_by(
        Employee.emp_id.cast(db.Integer).desc()).first())
    if last:
        try:
            return str(int(last.emp_id) + 1).zfill(3)
        except Exception:
            pass
    return "001"


@employees_bp.route("/")
@login_required
def index():
    if current_user.role != "Admin":
        flash("Employees section is Admin only.", "warning")
        return redirect(url_for("dashboard.home"))
    return render_template("employees/index.html")


# ── List / Search ─────────────────────────────────────────────
@employees_bp.route("/api/list")
@login_required
def api_list():
    err = _admin_required()
    if err: return err

    q = f"%{request.args.get('q', '').strip()}%"
    rows = Employee.query.filter(
        db.or_(
            Employee.emp_id.like(q),
            Employee.name.like(q),
            Employee.phone.like(q),
            Employee.email.like(q),
        )
    ).order_by(Employee.emp_id.cast(db.Integer)).all()
    return jsonify(employees=[e.to_dict() for e in rows])


# ── Auto ID ───────────────────────────────────────────────────
@employees_bp.route("/api/next-id")
@login_required
def api_next_id():
    return jsonify(emp_id=_next_emp_id())


# ── Save (Create / Update) ────────────────────────────────────
@employees_bp.route("/api/save", methods=["POST"])
@login_required
def api_save():
    err = _admin_required()
    if err: return err

    data      = request.get_json(force=True)
    emp_id    = data.get("emp_id",    "").strip()
    name      = data.get("name",      "").strip()
    phone     = data.get("phone",     "").strip()
    email     = data.get("email",     "").strip()
    role      = data.get("role",      "Employee").strip()
    join_date = data.get("join_date", date.today().isoformat()).strip()

    # Validation
    if not all([emp_id, name, phone, email]):
        return jsonify(success=False, message="All fields are required.")
    if not re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', email):
        return jsonify(success=False, message="Invalid email format.")
    if not re.fullmatch(r"^[6-9]\d{9}$", phone):
        return jsonify(success=False, message="Phone must be 10 digits starting 6-9.")

    # Join date validation — must not be in the future
    try:
        parsed_join_date = date.fromisoformat(join_date)
    except ValueError:
        return jsonify(success=False, message="Invalid join date format.")
    if parsed_join_date > date.today():
        return jsonify(success=False, message="Join date cannot be a future date.")

    # Duplicate phone check (excluding self)
    dup_phone = Employee.query.filter(
        Employee.phone == phone, Employee.emp_id != emp_id).first()
    if dup_phone:
        return jsonify(success=False, message="Phone number already exists.")

    dup_email = Employee.query.filter(
        Employee.email == email, Employee.emp_id != emp_id).first()
    if dup_email:
        return jsonify(success=False, message="Email already exists.")

    emp = Employee.query.get(emp_id)
    if emp:
        emp.name      = name
        emp.phone     = phone
        emp.email     = email
        emp.role      = role
        emp.join_date = parsed_join_date
    else:
        emp = Employee(emp_id=emp_id, name=name, phone=phone,
                       email=email, role=role,
                       join_date=parsed_join_date)
        db.session.add(emp)

    db.session.commit()
    return jsonify(success=True, message="Employee saved successfully.")


# ── Delete ────────────────────────────────────────────────────
@employees_bp.route("/api/delete/<emp_id>", methods=["DELETE"])
@login_required
def api_delete(emp_id):
    err = _admin_required()
    if err: return err

    emp = Employee.query.get_or_404(emp_id)
    username = f"emp{emp_id}"
    user = User.query.get(username)
    if user:
        db.session.delete(user)
    db.session.delete(emp)
    db.session.commit()
    return jsonify(success=True, message="Employee deleted.")


# ── Create login for employee ─────────────────────────────────
@employees_bp.route("/api/create-login", methods=["POST"])
@login_required
def api_create_login():
    err = _admin_required()
    if err: return err

    data   = request.get_json(force=True)
    emp_id = data.get("emp_id", "").strip()
    emp    = Employee.query.get(emp_id)
    if not emp:
        return jsonify(success=False, message="Employee not found.")

    username = f"emp{emp_id}"
    password = f"Emp@{emp_id}"
    hashed   = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    existing = User.query.get(username)
    if existing:
        existing.set_password(password)
        existing.role  = emp.role
        existing.email = emp.email
    else:
        db.session.add(User(
            username=username, password=hashed,
            role=emp.role, email=emp.email, emp_id=emp_id))
    db.session.commit()

    try:
        msg = Message(
            subject="Your IMS Login Credentials",
            recipients=[emp.email],
            body=(f"Welcome to Company IMS\n\n"
                  f"Username: {username}\nPassword: {password}\n\n"
                  f"Please change your password after login."),
        )
        mail.send(msg)
    except Exception:
        pass  # Don't fail if mail is not configured

    return jsonify(success=True,
                   message=f"Login created. Username: {username}")