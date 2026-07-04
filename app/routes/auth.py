import random
import hashlib
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify)
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message

from ..extensions import db, mail
from ..models.user import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ── Login ─────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    usernames = [u.username for u in User.query.order_by(User.username).all()]

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("auth/login.html", usernames=usernames)

        user = User.query.get(username)

        if not user or not user.check_password(password):
            flash("Invalid credentials.", "danger")
            return render_template("auth/login.html", usernames=usernames)

        # Update login info
        user.is_online = True
        user.last_login = datetime.utcnow()
        db.session.commit()

        login_user(user)
        next_page = request.args.get("next") or url_for("dashboard.home")
        return redirect(next_page)

    return render_template("auth/login.html", usernames=usernames)


# ── Logout ────────────────────────────────────────────────────
@auth_bp.route("/logout")
@login_required
def logout():
    current_user.is_online = False
    db.session.commit()
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))


# ── Forgot password — step 1: send OTP ───────────────────────
@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip()

        if not username:
            return jsonify(success=False, message="Username required")

        user = User.query.get(username)

        if not user:
            return jsonify(success=False, message="User not found")

        # 🔒 Rate limit (30 sec cooldown — must wait 30s before re-requesting)
        if user.otp_expiry and (user.otp_expiry - datetime.utcnow()).total_seconds() > (5 * 60 - 30):
            return jsonify(success=False, message="Wait before requesting OTP again")

        # Generate OTP
        otp = str(random.randint(100000, 999999))

        # 🔒 Hash OTP before storing
        hashed_otp = hashlib.sha256(otp.encode()).hexdigest()

        user.otp = hashed_otp
        user.otp_expiry = datetime.utcnow() + timedelta(minutes=5)

        try:
            db.session.commit()

            msg = Message(
                subject="IMS Password Reset OTP",
                recipients=[user.email],
                body=f"Your OTP is: {otp}\nValid for 5 minutes."
            )
            mail.send(msg)

            return jsonify(success=True, message="OTP sent successfully")

        except Exception:
            db.session.rollback()
            return jsonify(success=False, message="Failed to send OTP")

    return render_template("auth/forgot_password.html")


# ── Forgot password — step 2: verify OTP ─────────────────────
@auth_bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    username = request.form.get("username", "").strip()
    otp = request.form.get("otp", "").strip()

    if not username or not otp:
        return jsonify(success=False, message="Missing data")

    user = User.query.get(username)

    if not user or not user.otp:
        return jsonify(success=False, message="Invalid request")

    # 🔒 Hash input OTP
    hashed_otp = hashlib.sha256(otp.encode()).hexdigest()

    if user.otp != hashed_otp:
        return jsonify(success=False, message="Invalid OTP")

    if datetime.utcnow() > user.otp_expiry:
        return jsonify(success=False, message="OTP expired")

    return jsonify(success=True, message="OTP verified")


# ── Forgot password — step 3: reset password ───────────────
@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    username = request.form.get("username", "").strip()
    otp = request.form.get("otp", "").strip()
    new_password = request.form.get("new_password", "").strip()

    if not username or not otp or not new_password:
        return jsonify(success=False, message="Missing data")

    if len(new_password) < 6:
        return jsonify(success=False, message="Password must be at least 6 characters")

    user = User.query.get(username)

    if not user or not user.otp:
        return jsonify(success=False, message="Invalid request")

    hashed_otp = hashlib.sha256(otp.encode()).hexdigest()

    if user.otp != hashed_otp:
        return jsonify(success=False, message="Invalid OTP")

    if datetime.utcnow() > user.otp_expiry:
        return jsonify(success=False, message="OTP expired")

    try:
        user.set_password(new_password)

        # 🔒 Clear OTP after success
        user.otp = None
        user.otp_expiry = None

        db.session.commit()

        return jsonify(success=True, message="Password updated successfully")

    except Exception:
        db.session.rollback()
        return jsonify(success=False, message="Server error")