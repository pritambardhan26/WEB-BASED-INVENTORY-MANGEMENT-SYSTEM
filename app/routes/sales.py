import os
from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, request, jsonify,
                   send_file, current_app)
from flask_login import login_required, current_user
from flask_mail import Message

from ..extensions import db, mail
from ..models.sales    import SalesMaster, SalesItem, Return
from ..models.product  import Product
from ..models.customer import Customer

sales_bp = Blueprint("sales", __name__, url_prefix="/sales")

PAYMENT_MODES = ["Cash", "UPI", "Card", "Credit", "Split"]


# ── UPI Config ────────────────────────────────────────────────
@sales_bp.route("/api/upi-config")
@login_required
def api_upi_config():
    """Return UPI merchant config for the frontend QR generator."""
    cfg = current_app.config
    return jsonify(
        upiId=cfg.get("COMPANY_UPI_ID", "lalbaghenterprise@upi"),
        payeeName=cfg.get("COMPANY_NAME", "LALBAGH ENTERPRISE"),
        currency="INR",
    )


# ── Internal calc helper ──────────────────────────────────────
def _calc(unit_price, qty, gst_pct, disc_type, disc_val):
    base     = qty * unit_price
    disc_amt = disc_val if disc_type == "Flat" else base * disc_val / 100.0
    after    = max(base - disc_amt, 0.0)
    half     = gst_pct / 2.0
    cgst     = round(after * half / 100.0, 2)
    sgst     = round(after * half / 100.0, 2)
    return {
        "base":     base,
        "after":    after,
        "disc_amt": round(disc_amt, 2),
        "cgst":     cgst,
        "sgst":     sgst,
        "gst":      round(cgst + sgst, 2),
        "final":    round(after + cgst + sgst, 2),
    }


# ── Index ─────────────────────────────────────────────────────
@sales_bp.route("/")
@login_required
def index():
    return render_template("sales/index.html")


# ══════════════════════════════════════════════════════════════
#  BARCODE LOOKUP
# ══════════════════════════════════════════════════════════════
@sales_bp.route("/api/barcode/<path:code>")
@login_required
def api_barcode_lookup(code):
    code = code.strip()
    if not code:
        return jsonify(success=False, message="Empty barcode.", sound="error")

    product = None

    if hasattr(Product, "barcode"):
        product = Product.query.filter_by(barcode=code).first()

    if product is None and code.isdigit():
        product = db.session.get(Product, int(code))

    if product is None:
        return jsonify(
            success=False,
            message=f"No product found for barcode: {code}",
            sound="error",
        )

    if product.quantity <= 0:
        return jsonify(
            success=False,
            message=f"'{product.name}' is out of stock.",
            sound="error",
            product_id=product.product_id,
        )

    return jsonify(
        success=True,
        sound="success",
        product={
            "product_id":  product.product_id,
            "name":        product.name,
            "category":    getattr(product, "category", ""),
            "unit_price":  float(product.unit_price),
            "gst":         float(product.gst),
            "quantity":    product.quantity,
            "barcode":     code,
        },
    )


# ── Stock peek ────────────────────────────────────────────────
@sales_bp.route("/api/stock/<int:product_id>")
@login_required
def api_stock_peek(product_id):
    p = db.session.get(Product, product_id)
    if not p:
        return jsonify(success=False, message="Product not found.")
    return jsonify(success=True, product_id=product_id, quantity=p.quantity)


# ══════════════════════════════════════════════════════════════
#  CHECKOUT — with MySQL row-level locking to prevent oversell
#  IMPORTANT: Uses datetime.now() for LOCAL system timestamp
#             SalesItem has NO date column — not passed at all
#             payment_mode saved directly to SalesMaster
# ══════════════════════════════════════════════════════════════
@sales_bp.route("/api/checkout", methods=["POST"])
@login_required
def api_checkout():
    try:
        data           = request.get_json(force=True) or {}
        cart           = data.get("cart", [])
        customer_name  = data.get("customer_name",  "Walk-in").strip() or "Walk-in"
        customer_phone = data.get("customer_phone", "").strip()
        customer_email = data.get("customer_email", "").strip()
        payment_mode   = data.get("payment_mode",   "Cash").strip()
        cash_amount    = float(data.get("cash_amount", 0) or 0)
        upi_amount     = float(data.get("upi_amount",  0) or 0)
        card_amount    = float(data.get("card_amount", 0) or 0)

        if not cart:
            return jsonify(success=False, message="Cart is empty.")

        # ── STEP 1 — Acquire exclusive row locks in deterministic order
        sorted_cart     = sorted(cart, key=lambda x: x["product_id"])
        locked_products = {}

        for item in sorted_cart:
            pid = item["product_id"]
            p = (
                Product.query
                .filter_by(product_id=pid)
                .with_for_update()
                .first()
            )
            if not p:
                db.session.rollback()
                return jsonify(
                    success=False,
                    message=f"Product ID {pid} not found.",
                )
            locked_products[pid] = p

        # ── STEP 2 — Validate stock AFTER lock is held
        for item in cart:
            p   = locked_products[item["product_id"]]
            qty = int(item["qty"])
            if qty <= 0:
                db.session.rollback()
                return jsonify(success=False,
                    message=f"Invalid quantity for {p.name}.")
            if p.quantity < qty:
                db.session.rollback()
                return jsonify(
                    success=False,
                    message=(
                        f"Not enough stock for '{p.name}'. "
                        f"Only {p.quantity} unit(s) remaining — "
                        f"another sale may have just been processed."
                    ),
                    stock_conflict=True,
                    product_id=p.product_id,
                    available=p.quantity,
                )

        # ── STEP 3 — Compute totals
        subtotal = total_gst = 0.0
        cat_gst  = {}
        for item in cart:
            c = _calc(
                float(item["unit_price"]),
                int(item["qty"]),
                float(item["gst_pct"]),
                item["disc_type"],
                float(item["disc_val"]),
            )
            subtotal  += c["after"]
            total_gst += c["gst"]
            cat = item["category"]
            if cat not in cat_gst:
                cat_gst[cat] = {"pct": float(item["gst_pct"]), "cgst": 0.0, "sgst": 0.0}
            cat_gst[cat]["cgst"] += c["cgst"]
            cat_gst[cat]["sgst"] += c["sgst"]

        grand_total = round(subtotal + total_gst, 2)

        # ── Use LOCAL system time (not UTC) for invoice timestamp
        now = datetime.now()

        # ── Build payment_mode string for SalesMaster
        if payment_mode == "Split":
            total_paid = round(cash_amount + upi_amount + card_amount, 2)
            if abs(total_paid - grand_total) > 0.5:
                db.session.rollback()
                return jsonify(success=False,
                    message=(f"Split amounts ({total_paid}) "
                             f"don't match total ({grand_total})"))
            payment_details = f"Cash:{cash_amount},UPI:{upi_amount},Card:{card_amount}"
        else:
            payment_details = payment_mode

        # ── STEP 4 — Write SalesMaster
        #    payment_mode is now a proper column on the model
        master = SalesMaster(
            date=now,
            sold_by=current_user.username,
            customer_name=customer_name,
            customer_phone=customer_phone or None,
            subtotal=round(subtotal, 2),
            total_gst=round(total_gst, 2),
            grand_total=grand_total,
            payment_mode=payment_details,   # ← saved to DB column
        )
        db.session.add(master)
        db.session.flush()   # get sale_id before items

        # ── STEP 5 — Write SalesItems & decrement stock
        #    NOTE: SalesItem has NO date column in the new model — do NOT pass it
        for item in cart:
            c = _calc(
                float(item["unit_price"]),
                int(item["qty"]),
                float(item["gst_pct"]),
                item["disc_type"],
                float(item["disc_val"]),
            )
            db.session.add(SalesItem(
                sale_id=master.sale_id,
                product_id=item["product_id"],
                product_name=item["product_name"],
                category=item["category"],
                quantity=int(item["qty"]),
                mrp=float(item["unit_price"]),
                total_price=c["base"],
                discount_type=item["disc_type"],
                discount_value=float(item["disc_val"]),
                effective_total=c["final"],
            ))
            locked_products[item["product_id"]].quantity -= int(item["qty"])

        # ── STEP 6 — Single commit; locks released here
        db.session.commit()

        # ── STEP 7 — Generate invoice PDF
        invoice_filename = (f"invoice_{master.sale_id}_"
                            f"{now.strftime('%Y%m%d%H%M%S')}.pdf")
        invoice_path = os.path.join(
            current_app.config["INVOICE_DIR"], invoice_filename)

        _generate_invoice_pdf(
            invoice_path, master, cart, cat_gst,
            subtotal, total_gst, grand_total, payment_details)

        # ── STEP 8 — E-mail invoice (non-blocking, failures suppressed)
        if customer_email:
            try:
                with open(invoice_path, "rb") as f:
                    msg = Message(
                        subject=(
                            f"Invoice from "
                            f"{current_app.config.get('COMPANY_NAME', 'LALBAGH ENTERPRISE')}"
                            f" — Rs.{grand_total:.2f}"
                        ),
                        recipients=[customer_email],
                        body=(
                            f"Dear {customer_name},\n\n"
                            f"Thank you for shopping!\n"
                            f"Payment: {payment_details}\n"
                            f"Amount: Rs.{grand_total:.2f}\n\n"
                            f"Best regards,\n"
                            f"{current_app.config.get('COMPANY_NAME', 'LALBAGH ENTERPRISE')}"
                        ),
                    )
                    msg.attach(invoice_filename, "application/pdf", f.read())
                    mail.send(msg)
            except Exception:
                pass   # don't fail the sale if email fails

        return jsonify(
            success=True,
            sale_id=master.sale_id,
            grand_total=grand_total,
            invoice_file=invoice_filename,
            payment_mode=payment_details,
            message=f"Checkout complete. Sale ID: {master.sale_id}",
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


# ══════════════════════════════════════════════════════════════
#  HOLD BILL  (in-memory, per-process)
# ══════════════════════════════════════════════════════════════
_held_bills = {}


@sales_bp.route("/api/hold-bill", methods=["POST"])
@login_required
def api_hold_bill():
    try:
        import uuid
        data    = request.get_json(force=True) or {}
        cart    = data.get("cart", [])
        cust    = data.get("customer_name", "Walk-in")
        note    = data.get("note", "")
        if not cart:
            return jsonify(success=False, message="Cart is empty.")
        bill_id = str(uuid.uuid4())[:8].upper()
        _held_bills[bill_id] = {
            "cart":          cart,
            "customer_name": cust,
            "note":          note,
            "held_by":       current_user.username,
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return jsonify(success=True, bill_id=bill_id,
                       message=f"Bill held as #{bill_id}")
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@sales_bp.route("/api/held-bills")
@login_required
def api_held_bills():
    bills = []
    for bid, b in _held_bills.items():
        total = sum(
            _calc(
                float(i["unit_price"]),
                int(i["qty"]),
                float(i["gst_pct"]),
                i["disc_type"],
                float(i["disc_val"]),
            )["final"]
            for i in b["cart"]
        )
        bills.append({
            "bill_id":       bid,
            "customer_name": b["customer_name"],
            "note":          b["note"],
            "held_by":       b["held_by"],
            "timestamp":     b["timestamp"],
            "items":         len(b["cart"]),
            "total":         round(total, 2),
        })
    return jsonify(success=True, bills=bills)


@sales_bp.route("/api/recall-bill/<bill_id>")
@login_required
def api_recall_bill(bill_id):
    b = _held_bills.get(bill_id)
    if not b:
        return jsonify(success=False, message="Bill not found.")
    del _held_bills[bill_id]
    return jsonify(success=True, bill=b)


@sales_bp.route("/api/delete-held-bill/<bill_id>", methods=["DELETE"])
@login_required
def api_delete_held_bill(bill_id):
    if bill_id in _held_bills:
        del _held_bills[bill_id]
    return jsonify(success=True)


# ── Invoice download ──────────────────────────────────────────
@sales_bp.route("/invoice/<filename>")
@login_required
def download_invoice(filename):
    invoice_dir = current_app.config["INVOICE_DIR"]
    path = os.path.join(invoice_dir, filename)
    if not os.path.exists(path):
        return jsonify(error="Invoice not found"), 404
    return send_file(path, as_attachment=False,
                     download_name=filename, mimetype="application/pdf")


# ── Sales history ─────────────────────────────────────────────
@sales_bp.route("/api/history")
@login_required
def api_history():
    rows = SalesMaster.query.order_by(
        SalesMaster.sale_id.desc()).limit(50).all()
    return jsonify(success=True, sales=[s.to_dict() for s in rows])


@sales_bp.route("/api/recent-sales")
@login_required
def api_recent_sales():
    cutoff = datetime.now() - timedelta(days=10)
    rows   = SalesMaster.query.filter(
        SalesMaster.date >= cutoff
    ).order_by(SalesMaster.sale_id.desc()).limit(50).all()
    return jsonify(success=True, sales=[{
        "sale_id":       s.sale_id,
        "date":          s.date.strftime("%Y-%m-%d %H:%M"),
        "customer_name": s.customer_name,
        "grand_total":   float(s.grand_total),
        "payment_mode":  s.payment_mode or "Cash",
        "label": (f"{s.sale_id} — {s.date.strftime('%Y-%m-%d')} — "
                  f"{s.customer_name} — Rs.{float(s.grand_total):.2f}"),
    } for s in rows])


@sales_bp.route("/api/sale-items/<int:sale_id>")
@login_required
def api_sale_items(sale_id):
    items = SalesItem.query.filter_by(sale_id=sale_id).all()
    return jsonify(success=True, items=[i.to_dict() for i in items])


# ── Returns / Refunds ─────────────────────────────────────────
@sales_bp.route("/api/process-return", methods=["POST"])
@login_required
def api_process_return():
    try:
        data    = request.get_json(force=True) or {}
        refunds = data.get("refunds", [])
        reason  = data.get("reason", "").strip()
        if not reason:
            return jsonify(success=False, message="Reason is required.")
        if not refunds:
            return jsonify(success=False, message="No refund items.")

        total_refunded = 0.0
        for r in refunds:
            sid   = r["sale_id"]
            pid   = r["product_id"]
            r_qty = int(r["qty"])
            if r_qty <= 0:
                continue
            item = SalesItem.query.filter_by(
                sale_id=sid, product_id=pid).first()
            if not item:
                return jsonify(success=False,
                               message=f"Sale item not found: {pid}")
            already = db.session.query(
                db.func.coalesce(db.func.sum(Return.quantity), 0)
            ).filter_by(sale_id=sid, product_id=pid).scalar()
            if r_qty + already > item.quantity:
                return jsonify(success=False,
                    message=f"Cannot refund {r_qty} for {item.product_name}.")
            unit_eff = (float(item.effective_total) / item.quantity
                        if item.quantity else float(item.mrp))
            r_amt = round(unit_eff * r_qty, 2)
            db.session.add(Return(
                sale_id=sid,
                product_id=pid,
                quantity=r_qty,
                refund_amount=r_amt,
                date=datetime.now(),
                reason=reason,
            ))
            p = db.session.get(Product, pid)
            if p:
                p.quantity += r_qty
            item.effective_total = max(float(item.effective_total or 0) - r_amt, 0)
            master = db.session.get(SalesMaster, int(sid))
            if master:
                master.grand_total = max(float(master.grand_total or 0) - r_amt, 0)
            total_refunded += r_amt

        db.session.commit()
        return jsonify(success=True,
            total_refunded=total_refunded,
            message=f"Refund of Rs.{total_refunded:.2f} processed.")
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=str(e)), 500


@sales_bp.route("/api/return-history")
@login_required
def api_return_history():
    rows = Return.query.order_by(Return.return_id.desc()).limit(50).all()
    return jsonify(success=True, returns=[r.to_dict() for r in rows])


# ══════════════════════════════════════════════════════════════
#  INVOICE PDF GENERATOR
#  Uses datetime.now() (local system time) — matches invoice timestamp
# ══════════════════════════════════════════════════════════════
def _generate_invoice_pdf(filepath, master, cart, cat_gst,
                           subtotal, total_gst, grand_total,
                           payment_mode="Cash"):
    """
    Professional A4 Invoice — IMS · Lalbagh Enterprise
    Uses ReportLab only (no external image file needed).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib           import colors
    from reportlab.pdfgen        import canvas as rl_canvas
    from reportlab.platypus      import Table, TableStyle

    cfg            = current_app.config
    PAGE_W, PAGE_H = A4
    ML = MR = 36

    C_TEAL      = colors.HexColor("#1D9E75")
    C_TEAL_D    = colors.HexColor("#0F6E56")
    C_TEAL_L    = colors.HexColor("#E1F5EE")
    C_BLUE_L    = colors.HexColor("#E6F1FB")
    C_BLUE_D    = colors.HexColor("#185FA5")
    C_NAVY      = colors.HexColor("#0B1120")
    C_DARK      = colors.HexColor("#1E293B")
    C_MUTED     = colors.HexColor("#64748B")
    C_BORDER    = colors.HexColor("#E2E8F0")
    C_BG        = colors.HexColor("#F8FAFC")
    C_WHITE     = colors.white
    C_RED       = colors.HexColor("#B91C1C")
    C_GREEN_BAR = colors.HexColor("#34D472")
    C_ACCENT    = colors.HexColor("#F0FDF8")

    c = rl_canvas.Canvas(filepath, pagesize=A4)
    c.setTitle(f"Invoice #{master.sale_id}")

    CW = PAGE_W - ML - MR

    def draw_ims_logo(cx_center, cy_center, size=52):
        s  = size / 400.0
        ox = cx_center - size / 2
        oy = cy_center - size / 2

        def tx(x):  return ox + x * s
        def tfy(y): return oy + (400 - y) * s

        c.saveState()
        c.setFillColor(colors.Color(0.05, 0.13, 0.27, 0.92))
        c.roundRect(tx(98), tfy(256), 204 * s, 204 * s, 40 * s, fill=1, stroke=0)
        c.setStrokeColor(colors.Color(1, 1, 1, 0.09))
        c.setLineWidth(1.5 * s)
        c.roundRect(tx(98), tfy(256), 204 * s, 204 * s, 40 * s, fill=0, stroke=1)

        c.setStrokeColor(colors.HexColor("#C8DDF5"))
        c.setLineWidth(8 * s)
        c.setLineCap(1)
        p2 = c.beginPath()
        p2.moveTo(tx(128), tfy(128))
        p2.lineTo(tx(128), tfy(194))
        p2.curveTo(tx(128), tfy(208), tx(128), tfy(208), tx(142), tfy(208))
        p2.lineTo(tx(214), tfy(208))
        p2.curveTo(tx(224), tfy(208), tx(226), tfy(208), tx(226), tfy(197))
        p2.lineTo(tx(238), tfy(150))
        p2.curveTo(tx(241), tfy(139), tx(241), tfy(139), tx(229), tfy(139))
        p2.lineTo(tx(145), tfy(139))
        c.drawPath(p2, stroke=1, fill=0)

        c.setFillColor(C_GREEN_BAR)
        c.circle(tx(152), tfy(223), 10 * s, fill=1, stroke=0)
        c.circle(tx(204), tfy(223), 10 * s, fill=1, stroke=0)

        c.setFillColor(colors.HexColor("#1DB85A"))
        c.roundRect(tx(155), tfy(200), 14 * s, 25 * s, 3.5 * s, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#18A850"))
        c.roundRect(tx(175), tfy(200), 14 * s, 37 * s, 3.5 * s, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#13973F"))
        c.roundRect(tx(195), tfy(200), 14 * s, 51 * s, 3.5 * s, fill=1, stroke=0)

        c.setStrokeColor(colors.HexColor("#C8DDF5"))
        c.setLineWidth(4.5 * s)
        c.setLineCap(1)
        p3 = c.beginPath()
        p3.moveTo(tx(162), tfy(183))
        p3.lineTo(tx(182), tfy(170))
        p3.lineTo(tx(202), tfy(156))
        p3.lineTo(tx(226), tfy(134))
        c.drawPath(p3, stroke=1, fill=0)

        c.setFillColor(colors.HexColor("#C8DDF5"))
        c.setStrokeColor(colors.HexColor("#C8DDF5"))
        arrowPath = c.beginPath()
        arrowPath.moveTo(tx(226), tfy(134))
        arrowPath.lineTo(tx(214), tfy(133))
        arrowPath.lineTo(tx(223), tfy(143))
        arrowPath.close()
        c.drawPath(arrowPath, stroke=0, fill=1)

        c.setFillColor(colors.HexColor("#E8F4FF"))
        c.setFont("Helvetica-Bold", 72 * s)
        c.drawCentredString(tx(200), tfy(318), "IMS")

        c.setFillColor(C_GREEN_BAR)
        c.setStrokeColor(colors.Color(0, 0, 0, 0))
        c.roundRect(tx(118), tfy(323), 164 * s, 3 * s, 1.5 * s, fill=1, stroke=0)

        c.restoreState()

    # ── HEADER BAR ────────────────────────────────────────────
    HDR_H = 88
    hdr_y = PAGE_H - HDR_H

    c.setFillColor(C_NAVY)
    c.rect(0, hdr_y, PAGE_W, HDR_H, fill=1, stroke=0)
    c.setFillColor(C_TEAL)
    c.rect(0, hdr_y, 5, HDR_H, fill=1, stroke=0)

    draw_ims_logo(ML + 30, hdr_y + HDR_H / 2, size=58)

    tx_x = ML + 65
    c.setFillColor(C_WHITE)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(tx_x, hdr_y + HDR_H - 22, cfg.get("COMPANY_NAME", "Your Company"))
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.Color(1, 1, 1, 0.65))
    c.drawString(tx_x, hdr_y + HDR_H - 34, cfg.get("COMPANY_ADDR", "Address"))
    c.drawString(tx_x, hdr_y + HDR_H - 44,
                 f"GSTIN: {cfg.get('COMPANY_GSTIN', '')}   ·   Ph: {cfg.get('COMPANY_PHONE', '')}")

    inv_label = "INVOICE"
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(C_TEAL)
    iw = c.stringWidth(inv_label, "Helvetica-Bold", 18)
    c.drawString(PAGE_W - MR - iw, hdr_y + HDR_H - 22, inv_label)

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(C_WHITE)
    num_str = f"# {master.sale_id}"
    nw = c.stringWidth(num_str, "Helvetica-Bold", 9)
    c.drawString(PAGE_W - MR - nw, hdr_y + HDR_H - 34, num_str)

    # ── LOCAL timestamp used directly — already datetime.now()
    date_str = master.date.strftime("%d %b %Y, %I:%M %p") if master.date else ""
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.Color(1, 1, 1, 0.55))
    dw = c.stringWidth(date_str, "Helvetica", 7.5)
    c.drawString(PAGE_W - MR - dw, hdr_y + HDR_H - 45, date_str)

    pm_label = payment_mode[:12].upper()
    pm_w     = c.stringWidth(pm_label, "Helvetica-Bold", 7) + 16
    c.setFillColor(C_TEAL)
    c.roundRect(PAGE_W - MR - pm_w, hdr_y + 8, pm_w, 16, 8, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(C_WHITE)
    c.drawCentredString(PAGE_W - MR - pm_w / 2, hdr_y + 14, pm_label)

    y = hdr_y

    # ── BILLED TO / SERVED BY ─────────────────────────────────
    INFO_H = 52
    y -= INFO_H

    c.setFillColor(C_ACCENT)
    c.rect(0, y, PAGE_W, INFO_H, fill=1, stroke=0)
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.5)
    c.line(0, y + INFO_H, PAGE_W, y + INFO_H)
    c.line(0, y,          PAGE_W, y)

    c.setFont("Helvetica", 6.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, y + INFO_H - 13, "BILLED TO")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(C_DARK)
    c.drawString(ML, y + INFO_H - 26, master.customer_name or "Walk-in Customer")
    c.setFont("Helvetica", 8)
    c.setFillColor(C_MUTED)
    c.drawString(ML, y + INFO_H - 37, master.customer_phone or "—")

    mid = PAGE_W / 2
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.5)
    c.line(mid, y + 8, mid, y + INFO_H - 8)

    c.setFont("Helvetica", 6.5)
    c.setFillColor(C_MUTED)
    c.drawString(mid + 16, y + INFO_H - 13, "SERVED BY")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(C_DARK)
    c.drawString(mid + 16, y + INFO_H - 26, master.sold_by or "—")
    c.setFont("Helvetica", 8)
    c.setFillColor(C_MUTED)
    c.drawString(mid + 16, y + INFO_H - 37, date_str)

    y -= 14

    # ── ITEMS TABLE ───────────────────────────────────────────
    COL_W    = [140, 28, 60, 58, 58, 55, 55, 69]
    tbl_data = [[
        "Product / Category", "Qty", "Unit Price",
        "Discount", "Taxable", "CGST", "SGST", "Total"
    ]]

    row_fills = []
    for idx, item in enumerate(cart, start=1):
        unit_p  = float(item["unit_price"])
        qty     = int(item["qty"])
        gst_pct = float(item["gst_pct"])
        dt_     = item["disc_type"]
        dv      = float(item["disc_val"])
        cv      = _calc(unit_p, qty, gst_pct, dt_, dv)
        half    = gst_pct / 2.0
        disc_str = (f"Rs.{dv:.2f}" if dt_ == "Flat"
                    else (f"{dv:.0f}%" if dv else "—"))
        tbl_data.append([
            f"{item['product_name']}\n{item['category']}",
            str(qty),
            f"Rs.{unit_p:.2f}",
            disc_str,
            f"Rs.{cv['after']:.2f}",
            f"@{half:.1f}%\nRs.{cv['cgst']:.2f}",
            f"@{half:.1f}%\nRs.{cv['sgst']:.2f}",
            f"Rs.{cv['final']:.2f}",
        ])
        row_fills.append(idx)

    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0),  C_NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  C_WHITE),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  7.5),
        ("TOPPADDING",    (0, 0), (-1, 0),  7),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  7),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        ("ALIGN",         (0, 0), (0,  0),  "LEFT"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("TOPPADDING",    (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("TEXTCOLOR",     (0, 1), (-1, -1), C_DARK),
        ("ALIGN",         (1, 1), (-1, -1), "CENTER"),
        ("ALIGN",         (0, 1), (0,  -1), "LEFT"),
        ("FONTNAME",      (0, 1), (0,  -1), "Helvetica-Bold"),
        ("FONTNAME",      (7, 1), (7,  -1), "Helvetica-Bold"),
        ("BACKGROUND",    (5, 1), (5,  -1), C_TEAL_L),
        ("TEXTCOLOR",     (5, 1), (5,  -1), C_TEAL_D),
        ("BACKGROUND",    (6, 1), (6,  -1), C_BLUE_L),
        ("TEXTCOLOR",     (6, 1), (6,  -1), C_BLUE_D),
        ("BACKGROUND",    (7, 1), (7,  -1), colors.HexColor("#F0FDF8")),
        ("TEXTCOLOR",     (7, 1), (7,  -1), C_TEAL_D),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, C_TEAL),
        ("LINEBELOW",     (0, 1), (-1, -2), 0.3, C_BORDER),
        ("LINEBELOW",     (0, -1),(-1, -1), 0.5, C_BORDER),
    ]
    for i in row_fills:
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (4, i), C_BG))

    tbl = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    _, tbl_h = tbl.wrapOn(c, CW, PAGE_H)
    tbl_y    = y - tbl_h
    tbl.drawOn(c, ML, tbl_y)
    y = tbl_y - 16

    # ── TOTALS PANEL ──────────────────────────────────────────
    PANEL_W = 240
    PANEL_X = PAGE_W - MR - PANEL_W

    total_cgst = sum(v["cgst"] for v in cat_gst.values())
    total_sgst = sum(v["sgst"] for v in cat_gst.values())
    total_disc = sum(
        float(item["disc_val"]) if item["disc_type"] == "Flat"
        else float(item["unit_price"]) * int(item["qty"]) * float(item["disc_val"]) / 100.0
        for item in cart
    )

    rows_panel = []
    rows_panel.append(("Subtotal (taxable)", f"Rs. {subtotal:.2f}", "normal"))
    if total_disc > 0:
        rows_panel.append(("Total Discount", f"- Rs. {total_disc:.2f}", "discount"))
    rows_panel.append(("—", "", "divider"))
    rows_panel.append(("GST Breakdown", "", "tax_head"))
    for cat, vals in sorted(cat_gst.items()):
        half = vals["pct"] / 2.0
        rows_panel.append((f"  CGST {half:.1f}% ({cat})", f"Rs. {vals['cgst']:.2f}", "sub_cat"))
        rows_panel.append((f"  SGST {half:.1f}% ({cat})", f"Rs. {vals['sgst']:.2f}", "sub_cat"))
    rows_panel.append(("—", "", "divider"))
    rows_panel.append(("Total CGST",  f"Rs. {total_cgst:.2f}", "normal"))
    rows_panel.append(("Total SGST",  f"Rs. {total_sgst:.2f}", "normal"))
    rows_panel.append(("Total Tax",   f"Rs. {total_gst:.2f}",  "normal"))
    rows_panel.append(("—", "", "divider"))
    rows_panel.append(("GRAND TOTAL", f"Rs. {grand_total:.2f}", "grand"))
    rows_panel.append((f"Payment: {payment_mode}", "", "payment"))

    ROW_H = {"normal": 12, "discount": 12, "divider": 8, "grand": 20,
              "tax_head": 13, "sub_cat": 11, "payment": 12}
    panel_h = sum(ROW_H[r[2]] for r in rows_panel) + 20
    panel_y = y - panel_h

    c.setFillColor(C_ACCENT)
    c.roundRect(PANEL_X - 8, panel_y - 4, PANEL_W + 16, panel_h + 8, 8, fill=1, stroke=0)
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.5)
    c.roundRect(PANEL_X - 8, panel_y - 4, PANEL_W + 16, panel_h + 8, 8, fill=0, stroke=1)
    c.setFillColor(C_TEAL)
    c.roundRect(PANEL_X - 8, panel_y - 4, 4, panel_h + 8, 2, fill=1, stroke=0)

    ry = y - 10
    for label, value, style in rows_panel:
        if style == "divider":
            c.setStrokeColor(C_BORDER)
            c.setLineWidth(0.4)
            c.line(PANEL_X, ry, PAGE_W - MR, ry)
            ry -= 8
            continue

        if style == "grand":
            c.setFillColor(C_TEAL)
            c.roundRect(PANEL_X - 4, ry - 14, PANEL_W + 4, 22, 6, fill=1, stroke=0)
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(C_WHITE)
            c.drawString(PANEL_X + 2, ry - 6, label)
            c.setFont("Helvetica-Bold", 13)
            c.drawRightString(PAGE_W - MR, ry - 4, value)
            ry -= ROW_H["grand"]
            continue

        if style == "tax_head":
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(C_TEAL)
            c.drawString(PANEL_X, ry, label.upper())
            ry -= ROW_H["tax_head"]
            continue

        if style == "payment":
            c.setFont("Helvetica", 7.5)
            c.setFillColor(C_MUTED)
            c.drawString(PANEL_X, ry - 2, label)
            ry -= ROW_H["payment"]
            continue

        font = "Helvetica-Bold" if style == "normal" else "Helvetica"
        lc   = C_DARK if style != "discount" else C_RED
        vc   = C_TEAL_D if style == "normal" else (C_RED if style == "discount" else C_MUTED)
        if style == "sub_cat":
            lc = vc = C_MUTED

        c.setFont(font, 8)
        c.setFillColor(lc)
        c.drawString(PANEL_X, ry, label)
        if value:
            c.setFillColor(vc)
            c.drawRightString(PAGE_W - MR, ry, value)
        ry -= ROW_H[style]

    y = min(panel_y - 16, ry - 16)

    # ── UPI QR on invoice ─────────────────────────────────────
    if "UPI" in payment_mode.upper():
        try:
            import qrcode as _qr
            import io as _io
            from reportlab.lib.utils import ImageReader as _IR

            upi_id   = cfg.get("COMPANY_UPI_ID", "lalbaghenterprise@upi")
            pay_name = cfg.get("COMPANY_NAME",   "LALBAGH ENTERPRISE")
            upi_str  = (
                f"upi://pay?pa={upi_id}"
                f"&pn={pay_name.replace(' ', '%20')}"
                f"&am={grand_total:.2f}&cu=INR"
                f"&tn=Invoice%20{master.sale_id}"
            )

            qr_img = _qr.make(upi_str)
            buf    = _io.BytesIO()
            qr_img.save(buf, format="PNG")
            buf.seek(0)

            QR_SIZE = 80
            qr_x    = ML
            qr_y    = y - QR_SIZE - 10

            c.setFillColor(C_ACCENT)
            c.roundRect(qr_x - 6, qr_y - 10, QR_SIZE + 82, QR_SIZE + 20, 8, fill=1, stroke=0)
            c.setStrokeColor(C_BORDER)
            c.setLineWidth(0.5)
            c.roundRect(qr_x - 6, qr_y - 10, QR_SIZE + 82, QR_SIZE + 20, 8, fill=0, stroke=1)

            c.drawImage(_IR(buf), qr_x, qr_y, width=QR_SIZE, height=QR_SIZE)

            c.setFont("Helvetica-Bold", 7.5)
            c.setFillColor(colors.HexColor("#6F3FC1"))
            c.drawString(qr_x + QR_SIZE + 8, qr_y + QR_SIZE - 10, "Scan to Pay via UPI")
            c.setFont("Helvetica", 7)
            c.setFillColor(C_MUTED)
            c.drawString(qr_x + QR_SIZE + 8, qr_y + QR_SIZE - 22, "UPI ID:")
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(C_DARK)
            c.drawString(qr_x + QR_SIZE + 8, qr_y + QR_SIZE - 33, upi_id)
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(colors.HexColor("#15803D"))
            c.drawString(qr_x + QR_SIZE + 8, qr_y + QR_SIZE - 47, f"Rs. {grand_total:.2f}")
            c.setFont("Helvetica", 6.5)
            c.setFillColor(C_MUTED)
            c.drawString(qr_x + QR_SIZE + 8, qr_y + QR_SIZE - 58,
                         "Google Pay · PhonePe · Paytm · BHIM")
        except ImportError:
            pass

    # ── FOOTER ────────────────────────────────────────────────
    FOOTER_H = 38
    c.setFillColor(C_NAVY)
    c.rect(0, 0, PAGE_W, FOOTER_H, fill=1, stroke=0)
    c.setFillColor(C_TEAL)
    c.rect(0, 0, 5, FOOTER_H, fill=1, stroke=0)

    draw_ims_logo(ML + 16, FOOTER_H / 2, size=28)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(C_WHITE)
    c.drawString(ML + 36, FOOTER_H - 14, "Thank you for your purchase!")
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.Color(1, 1, 1, 0.55))
    c.drawString(ML + 36, FOOTER_H - 24, "Returns accepted within 7 days with original invoice.")

    pm_w2 = c.stringWidth(payment_mode[:10].upper(), "Helvetica-Bold", 7) + 16
    c.setFillColor(C_TEAL)
    c.roundRect(PAGE_W - MR - pm_w2, 11, pm_w2, 16, 8, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(C_WHITE)
    c.drawCentredString(PAGE_W - MR - pm_w2 / 2, 17, payment_mode[:10].upper())

    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.Color(1, 1, 1, 0.3))
    pg_txt = "Page 1 of 1"
    pw = c.stringWidth(pg_txt, "Helvetica", 6.5)
    c.drawString((PAGE_W - pw) / 2, 6, pg_txt)

    c.save()