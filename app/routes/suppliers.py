from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required, current_user
import re
import io

from ..extensions import db
from ..models.supplier import Supplier

suppliers_bp = Blueprint("suppliers", __name__, url_prefix="/suppliers")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _admin_required():
    if current_user.role != "Admin":
        return jsonify(error="Admin access required"), 403
    return None


def _next_id() -> str:
    last = Supplier.query.order_by(
        Supplier.supplier_id.cast(db.Integer).desc()
    ).first()
    if last:
        try:
            return str(int(last.supplier_id) + 1).zfill(3)
        except Exception:
            pass
    return "001"


# ── Pages ─────────────────────────────────────────────────────────────────────

@suppliers_bp.route("/")
@login_required
def index():
    if current_user.role != "Admin":
        from flask import flash, redirect, url_for
        flash("Suppliers section is Admin only.", "warning")
        return redirect(url_for("dashboard.home"))
    return render_template("suppliers/index.html")


# ── API: list / search ────────────────────────────────────────────────────────

@suppliers_bp.route("/api/list")
@login_required
def api_list():
    q = f"%{request.args.get('q', '').strip()}%"
    rows = Supplier.query.filter(
        db.or_(
            Supplier.name.like(q),
            Supplier.phone.like(q),
            Supplier.company.like(q),
        )
    ).order_by(Supplier.supplier_id.cast(db.Integer)).all()
    return jsonify(suppliers=[s.to_dict() for s in rows])


@suppliers_bp.route("/api/next-id")
@login_required
def api_next_id():
    return jsonify(supplier_id=_next_id())


@suppliers_bp.route("/api/all-for-select")
@login_required
def api_all_for_select():
    rows = Supplier.query.order_by(Supplier.company).all()
    return jsonify(suppliers=[
        {"supplier_id": s.supplier_id, "label": f"{s.supplier_id} - {s.company}"}
        for s in rows
    ])


# ── API: save (add / edit) ────────────────────────────────────────────────────

@suppliers_bp.route("/api/save", methods=["POST"])
@login_required
def api_save():
    err = _admin_required()
    if err:
        return err

    data    = request.get_json(force=True)
    sid     = data.get("supplier_id", "").strip()
    name    = data.get("name",    "").strip()
    company = data.get("company", "").strip()
    phone   = data.get("phone",   "").strip()
    email   = data.get("email",   "").strip()
    address = data.get("address", "").strip()

    if not all([sid, name, phone]):
        return jsonify(success=False, message="supplier_id, name, and phone are required.")

    if email and not re.match(
        r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', email
    ):
        return jsonify(success=False, message="Invalid email format.")

    existing = Supplier.query.get(sid)
    if existing:
        existing.name    = name
        existing.company = company or None
        existing.phone   = phone
        existing.email   = email or None
        existing.address = address or None
    else:
        db.session.add(Supplier(
            supplier_id=sid,
            name=name,
            company=company or None,
            phone=phone,
            email=email or None,
            address=address or None,
        ))

    db.session.commit()
    return jsonify(success=True, message="Supplier saved successfully.")


# ── API: delete ───────────────────────────────────────────────────────────────

@suppliers_bp.route("/api/delete/<sid>", methods=["DELETE"])
@login_required
def api_delete(sid):
    err = _admin_required()
    if err:
        return err

    supplier = Supplier.query.get_or_404(sid)
    db.session.delete(supplier)
    db.session.commit()
    return jsonify(success=True, message="Supplier deleted.")


# ── API: bulk import ──────────────────────────────────────────────────────────

@suppliers_bp.route("/api/bulk-import-template")
@login_required
def api_bulk_import_template():
    err = _admin_required()
    if err:
        return err

    try:
        import pandas as pd

        df = pd.DataFrame(columns=[
            "supplier_id", "name", "company", "phone", "email", "address"
        ])
        df.loc[0] = [
            "001", "Ravi Kumar", "Ravi Traders",
            "9876543210", "ravi@example.com", "123 Market Street, Kolkata"
        ]

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Suppliers")
        buf.seek(0)

        return send_file(
            buf,
            as_attachment=True,
            download_name="supplier_import_template.xlsx",
            mimetype=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        )
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@suppliers_bp.route("/api/bulk-import", methods=["POST"])
@login_required
def api_bulk_import():
    err = _admin_required()
    if err:
        return err

    try:
        import pandas as pd

        if "file" not in request.files:
            return jsonify(success=False, message="No file uploaded.")

        file = request.files["file"]
        if not file.filename.endswith((".xlsx", ".xls")):
            return jsonify(success=False, message="Only .xlsx or .xls files are allowed.")

        df = pd.read_excel(file)

        required_cols = ["supplier_id", "name", "phone"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            return jsonify(
                success=False,
                message=f"Missing required columns: {', '.join(missing)}"
            )

        added = updated = errors = 0
        error_list = []

        for i, row in df.iterrows():
            try:
                sid     = str(row["supplier_id"]).strip()
                name    = str(row["name"]).strip()
                phone   = str(row["phone"]).strip()
                company = str(row.get("company", "") or "").strip() or None
                email   = str(row.get("email",   "") or "").strip() or None
                address = str(row.get("address", "") or "").strip() or None

                if not sid or not name or not phone:
                    error_list.append(f"Row {i + 2}: supplier_id, name, and phone are required.")
                    errors += 1
                    continue

                if email and not re.match(
                    r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', email
                ):
                    error_list.append(f"Row {i + 2}: Invalid email — {email}")
                    errors += 1
                    continue

                existing = Supplier.query.get(sid)
                if existing:
                    existing.name    = name
                    existing.company = company
                    existing.phone   = phone
                    existing.email   = email
                    existing.address = address
                    updated += 1
                else:
                    db.session.add(Supplier(
                        supplier_id=sid,
                        name=name,
                        company=company,
                        phone=phone,
                        email=email,
                        address=address,
                    ))
                    added += 1

            except Exception as row_err:
                error_list.append(f"Row {i + 2}: {row_err}")
                errors += 1

        db.session.commit()
        return jsonify(
            success=True,
            message=f"Import complete: {added} added, {updated} updated, {errors} errors.",
            added=added,
            updated=updated,
            errors=errors,
            error_list=error_list[:10],
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500