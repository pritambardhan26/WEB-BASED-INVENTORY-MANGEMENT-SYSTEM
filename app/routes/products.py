from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required, current_user
import os, io, base64

from ..extensions import db
from ..models.product import Product, CategoryGST
from ..models.stock   import AuditLog, StockLog

products_bp = Blueprint("products", __name__, url_prefix="/products")


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _next_id():
    rows = [p.product_id for p in Product.query.all()]
    nums = []
    for r in rows:
        try:
            nums.append(int(r))
        except (ValueError, TypeError):
            pass
    return str((max(nums) + 1) if nums else 1).zfill(3)


def _log(user, action, pid, details=""):
    db.session.add(AuditLog(
        user=user, action=action,
        product_id=pid, details=details
    ))


# ──────────────────────────────────────────────────────────────
# PAGES
# ──────────────────────────────────────────────────────────────

@products_bp.route("/")
@login_required
def index():
    return render_template("products/index.html")


# ──────────────────────────────────────────────────────────────
# API – PRODUCT LIST
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/list")
@login_required
def api_list():
    try:
        from ..models.supplier import Supplier
        q = f"%{request.args.get('q', '').strip()}%"

        rows = (
            db.session.query(Product)
            .outerjoin(Product.supplier)
            .filter(
                db.or_(
                    Product.product_id.like(q),
                    Product.name.like(q),
                    Product.category.like(q),
                    Product.supplier_id.like(q),
                    Supplier.company.like(q),
                )
            )
            .all()
        )

        total_value = db.session.query(
            db.func.coalesce(
                db.func.sum(Product.quantity * Product.cost_price), 0.0
            )
        ).scalar()

        return jsonify(
            success=True,
            products=[p.to_dict() for p in rows],
            total_inventory_value=round(float(total_value), 2),
        )
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – SINGLE PRODUCT GET
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/get/<pid>")
@login_required
def api_get(pid):
    try:
        p = Product.query.get(pid)
        if not p:
            return jsonify(success=False, message="Product not found."), 404
        return jsonify(success=True, **p.to_dict())
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – NEXT AUTO-ID
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/next-id")
@login_required
def api_next_id():
    return jsonify(success=True, product_id=_next_id())


# ──────────────────────────────────────────────────────────────
# API – SAVE (ADD / EDIT)
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/save", methods=["POST"])
@login_required
def api_save():
    try:
        data = request.get_json(force=True) or {}

        pid         = str(data.get("product_id",    "")).strip()
        name        = str(data.get("name",          "")).strip()
        category    = str(data.get("category",      "")).strip()
        supplier_id = str(data.get("supplier_id",   "")).strip()
        quantity    = int(data.get("quantity",    0))
        cost_price  = float(data.get("cost_price",  0))
        unit_price  = float(data.get("unit_price",  0))
        reorder     = int(data.get("reorder_level", 0))

        if not pid or not name:
            return jsonify(success=False, message="SKU and Name are required.")
        if not supplier_id:
            return jsonify(success=False, message="Select a supplier.")

        # Resolve GST from category
        cat_gst = CategoryGST.query.get(category)
        if cat_gst is None:
            return jsonify(
                success=False,
                message=f"No GST rate found for '{category}'. "
                        f"Add it in GST Manager first.",
                gst_missing=True,
            )
        gst = float(cat_gst.gst)

        existing = Product.query.get(pid)
        if existing:
            old_qty = existing.quantity
            existing.name         = name
            existing.category     = category
            existing.supplier_id  = supplier_id
            existing.quantity     = quantity
            existing.cost_price   = cost_price
            existing.unit_price   = unit_price
            existing.gst          = gst
            existing.mrp          = unit_price
            existing.reorder_level = reorder
            action = "EDIT"

            if quantity != old_qty:
                diff = quantity - old_qty
                db.session.add(StockLog(
                    product_id=pid,
                    product_name=name,
                    change_type="IN" if diff > 0 else "OUT",
                    quantity=abs(diff),
                    reason="Manual adjustment",
                    changed_by=current_user.username,
                ))
        else:
            db.session.add(Product(
                product_id=pid,
                name=name,
                category=category,
                supplier_id=supplier_id,
                quantity=quantity,
                cost_price=cost_price,
                unit_price=unit_price,
                gst=gst,
                mrp=unit_price,
                reorder_level=reorder,
            ))
            action = "ADD"

        _log(current_user.username, action, pid,
             f"name={name},qty={quantity},price={unit_price}")
        db.session.commit()
        return jsonify(success=True, message="Product saved successfully.")

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – DELETE
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/delete/<pid>", methods=["DELETE"])
@login_required
def api_delete(pid):
    if current_user.role != "Admin":
        return jsonify(success=False, message="Admin only.")
    try:
        p = Product.query.get(pid)
        if not p:
            return jsonify(success=False, message="Product not found.")
        _log(current_user.username, "DELETE", pid, f"Deleted: {p.name}")
        db.session.delete(p)
        db.session.commit()
        return jsonify(success=True, message="Product deleted.")
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – PRODUCTS FOR SALE (POS)
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/for-sale")
@login_required
def api_for_sale():
    try:
        rows = (
            Product.query
            .filter(Product.quantity > 0)
            .order_by(Product.name)
            .all()
        )
        return jsonify(success=True, products=[{
            "product_id": p.product_id,
            "label":      f"{p.product_id} - {p.name}",
            "name":       p.name,
            "category":   p.category or "",
            "unit_price": float(p.unit_price),
            "gst":        float(p.gst),
            "quantity":   p.quantity,
        } for p in rows])
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – SUPPLIERS FOR SELECT
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/suppliers-for-select")
@login_required
def api_suppliers_for_select():
    from ..models.supplier import Supplier
    rows = Supplier.query.order_by(Supplier.company).all()
    return jsonify(success=True, suppliers=[{
        "supplier_id": s.supplier_id,
        "label":       f"{s.supplier_id} - {s.company}",
    } for s in rows])


# ──────────────────────────────────────────────────────────────
# API – GST MANAGER
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/gst/list")
@login_required
def api_gst_list():
    rows = CategoryGST.query.order_by(CategoryGST.category).all()
    return jsonify(success=True, categories=[r.to_dict() for r in rows])


@products_bp.route("/api/gst/save", methods=["POST"])
@login_required
def api_gst_save():
    if current_user.role != "Admin":
        return jsonify(success=False, message="Admin only.")
    try:
        data     = request.get_json(force=True) or {}
        category = str(data.get("category", "")).strip()
        gst      = float(data.get("gst", 0))
        if not category:
            return jsonify(success=False, message="Category cannot be empty.")
        existing = CategoryGST.query.get(category)
        if existing:
            existing.gst = gst
        else:
            db.session.add(CategoryGST(category=category, gst=gst))
        _log(current_user.username, "EDIT", "-", f"GST: {category}={gst}%")
        db.session.commit()
        return jsonify(success=True, message=f"GST for '{category}' set to {gst}%")
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


@products_bp.route("/api/gst/delete/<category>", methods=["DELETE"])
@login_required
def api_gst_delete(category):
    if current_user.role != "Admin":
        return jsonify(success=False, message="Admin only.")
    try:
        c = CategoryGST.query.get(category)
        if not c:
            return jsonify(success=False, message="Category not found.")
        _log(current_user.username, "DELETE", "-", f"GST deleted: {category}")
        db.session.delete(c)
        db.session.commit()
        return jsonify(success=True, message=f"Deleted '{category}'")
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – AUDIT LOG
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/audit-log")
@login_required
def api_audit_log():
    action = request.args.get("action", "ALL")
    pid    = request.args.get("product_id", "").strip()
    q      = AuditLog.query
    if action != "ALL":
        q = q.filter(AuditLog.action == action)
    if pid:
        q = q.filter(AuditLog.product_id.like(f"%{pid}%"))
    rows = q.order_by(AuditLog.id.desc()).limit(200).all()
    return jsonify(success=True, logs=[r.to_dict() for r in rows])


# ──────────────────────────────────────────────────────────────
# API – BARCODE (single label PDF)
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/barcode/<pid>")
@login_required
def api_barcode(pid):
    try:
        p = Product.query.get(pid)
        if not p:
            return jsonify(success=False, message="Product not found.")

        from reportlab.graphics.barcode import code128
        from reportlab.pdfgen           import canvas as rl_canvas
        from reportlab.lib.units        import mm
        from reportlab.lib.colors       import black

        bar_h  = 20 * mm
        bar_w  = 60 * mm
        bc     = code128.Code128(pid, barHeight=bar_h, barWidth=0.9,
                                 humanReadable=True)
        page_w = max(bc.width, bar_w) + 20
        page_h = bar_h + 30

        buf = io.BytesIO()
        c   = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))
        bc.drawOn(c, 10, 8)
        label = p.name[:28] + ("…" if len(p.name) > 28 else "")
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(black)
        c.drawCentredString(page_w / 2, bar_h + 16, label)
        c.setFont("Helvetica", 7)
        c.drawCentredString(page_w / 2, 2,
                            f"MRP: Rs.{float(p.unit_price):.2f}")
        c.save()
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()

        return jsonify(
            success=True,
            barcode=b64,
            product_id=pid,
            name=p.name,
            price=float(p.unit_price),
            category=p.category or "",
        )
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – BARCODE SHEET (A4 multi-label PDF)
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/barcode-sheet", methods=["POST"])
@login_required
def api_barcode_sheet():
    try:
        data   = request.get_json(force=True) or {}
        pids   = data.get("product_ids", [])
        copies = int(data.get("copies", 1))

        if not pids:
            return jsonify(success=False, message="No products selected.")

        from reportlab.lib.pagesizes    import A4
        from reportlab.lib.units        import mm
        from reportlab.pdfgen           import canvas as rl_canvas
        from reportlab.graphics.barcode import code128
        from reportlab.graphics.shapes  import Drawing
        from reportlab.graphics         import renderPDF
        from reportlab.lib.colors       import black, HexColor
        import tempfile

        LW, LH      = 62 * mm, 28 * mm
        COLS, ROWS  = 3, 9
        ML, MT      = 8 * mm, 10 * mm
        GAP_X, GAP_Y = 3 * mm, 3 * mm

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        c   = rl_canvas.Canvas(tmp.name, pagesize=A4)
        PAGE_W, PAGE_H = A4

        items = []
        for pid in pids:
            p = Product.query.get(pid)
            if p:
                for _ in range(copies):
                    items.append(p)

        idx = 0
        while idx < len(items):
            for row in range(ROWS):
                for col in range(COLS):
                    if idx >= len(items):
                        break
                    p  = items[idx]; idx += 1
                    x  = ML + col * (LW + GAP_X)
                    y  = PAGE_H - MT - (row + 1) * (LH + GAP_Y)

                    c.setStrokeColor(HexColor("#CCCCCC"))
                    c.setLineWidth(0.3)
                    c.rect(x, y, LW, LH, stroke=1, fill=0)

                    c.setFont("Helvetica-Bold", 7)
                    c.setFillColor(black)
                    name = p.name[:28] + ("…" if len(p.name) > 28 else "")
                    c.drawCentredString(x + LW / 2, y + LH - 7, name)

                    bc   = code128.Code128(p.product_id,
                                           barHeight=10 * mm, barWidth=0.7,
                                           humanReadable=True)
                    bc_x = x + (LW - bc.width) / 2
                    bc_y = y + 6
                    d    = Drawing(bc.width, 10 * mm + 4)
                    d.add(bc)
                    renderPDF.draw(d, c, bc_x, bc_y)

                    c.setFont("Helvetica", 6.5)
                    c.drawCentredString(
                        x + LW / 2, y + 2,
                        f"Rs.{float(p.unit_price):.2f}  |  {p.category or ''}"
                    )

            if idx < len(items):
                c.showPage()

        c.save()

        with open(tmp.name, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode()
        os.unlink(tmp.name)

        return jsonify(success=True, pdf=pdf_b64, count=len(items))
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – BULK IMPORT TEMPLATE DOWNLOAD
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/bulk-import-template")
@login_required
def api_bulk_import_template():
    try:
        import pandas as pd

        df = pd.DataFrame(columns=[
            "product_id", "name", "category", "supplier_id",
            "quantity", "cost_price", "unit_price", "reorder_level",
        ])
        df.loc[0] = ["001", "Sample Product", "Grocery", "001",
                     100, 50.00, 80.00, 10]

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Products")
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name="product_import_template.xlsx",
            mimetype=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
        )
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ──────────────────────────────────────────────────────────────
# API – BULK IMPORT FROM EXCEL
# ──────────────────────────────────────────────────────────────

@products_bp.route("/api/bulk-import", methods=["POST"])
@login_required
def api_bulk_import():
    if current_user.role != "Admin":
        return jsonify(success=False, message="Admin only.")
    try:
        import pandas as pd

        if "file" not in request.files:
            return jsonify(success=False, message="No file uploaded.")

        file = request.files["file"]
        if not file.filename.endswith((".xlsx", ".xls")):
            return jsonify(success=False,
                           message="Only .xlsx or .xls files allowed.")

        df = pd.read_excel(file)
        required = [
            "product_id", "name", "category", "supplier_id",
            "quantity", "cost_price", "unit_price", "reorder_level",
        ]
        missing = [col for col in required if col not in df.columns]
        if missing:
            return jsonify(
                success=False,
                message=f"Missing columns: {', '.join(missing)}",
            )

        added = updated = errors = 0
        error_list = []

        for i, row in df.iterrows():
            try:
                pid         = str(row["product_id"]).strip()
                name        = str(row["name"]).strip()
                category    = str(row["category"]).strip()
                supplier_id = str(row["supplier_id"]).strip()
                quantity    = int(row["quantity"]    or 0)
                cost_price  = float(row["cost_price"]  or 0)
                unit_price  = float(row["unit_price"]  or 0)
                reorder     = int(row["reorder_level"] or 0)

                if not pid or not name:
                    error_list.append(f"Row {i + 2}: Empty SKU or Name")
                    errors += 1
                    continue

                cat_gst = CategoryGST.query.get(category)
                gst     = float(cat_gst.gst) if cat_gst else 18.0

                existing = Product.query.get(pid)
                if existing:
                    existing.name          = name
                    existing.category      = category
                    existing.supplier_id   = supplier_id
                    existing.quantity      = quantity
                    existing.cost_price    = cost_price
                    existing.unit_price    = unit_price
                    existing.gst           = gst
                    existing.mrp           = unit_price
                    existing.reorder_level = reorder
                    updated += 1
                else:
                    db.session.add(Product(
                        product_id=pid,
                        name=name,
                        category=category,
                        supplier_id=supplier_id,
                        quantity=quantity,
                        cost_price=cost_price,
                        unit_price=unit_price,
                        gst=gst,
                        mrp=unit_price,
                        reorder_level=reorder,
                    ))
                    added += 1

            except Exception as row_err:
                error_list.append(f"Row {i + 2}: {row_err}")
                errors += 1

        db.session.commit()
        _log(
            current_user.username, "ADD", "-",
            f"Bulk import: {added} added, {updated} updated, {errors} errors",
        )
        db.session.commit()

        return jsonify(
            success=True,
            message=(
                f"Import complete: {added} added, "
                f"{updated} updated, {errors} errors"
            ),
            added=added,
            updated=updated,
            errors=errors,
            error_list=error_list[:10],
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500