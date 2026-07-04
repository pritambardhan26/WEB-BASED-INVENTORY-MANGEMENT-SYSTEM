from datetime import datetime
from ..extensions import db


# ================= SALES MASTER =================
class SalesMaster(db.Model):
    __tablename__ = "sales_master"

    sale_id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    date           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    sold_by        = db.Column(
        db.String(80),
        db.ForeignKey("users.username"),
        nullable=False
    )

    customer_name  = db.Column(db.String(120), nullable=False, default="Walk-in")
    customer_phone = db.Column(db.String(15), nullable=True)

    subtotal       = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    total_gst      = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    grand_total    = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)

    payment_mode   = db.Column(db.String(20), default="Cash")   # ✅ ADDED

    # ================= RELATIONSHIPS =================
    items = db.relationship(
        "SalesItem",
        backref="sale",
        cascade="all, delete-orphan",
        lazy=True
    )

    # ================= SERIALIZER =================
    def to_dict(self):
        return {
            "sale_id": self.sale_id,
            "date": self.date.strftime("%Y-%m-%d %H:%M:%S") if self.date else "",
            "sold_by": self.sold_by,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone or "",
            "subtotal": float(self.subtotal),
            "total_gst": float(self.total_gst),
            "grand_total": float(self.grand_total),
            "payment_mode": self.payment_mode
        }


# ================= SALES ITEMS =================
class SalesItem(db.Model):
    __tablename__ = "sales_items"

    item_id         = db.Column(db.Integer, primary_key=True, autoincrement=True)

    sale_id         = db.Column(
        db.Integer,
        db.ForeignKey("sales_master.sale_id"),
        nullable=False
    )

    product_id      = db.Column(
        db.String(30),
        db.ForeignKey("products.product_id"),
        nullable=False
    )

    product_name    = db.Column(db.String(150), nullable=False)
    category        = db.Column(db.String(80), nullable=True)

    quantity        = db.Column(db.Integer, nullable=False, default=1)

    mrp             = db.Column(db.Numeric(10, 2), nullable=False)
    total_price     = db.Column(db.Numeric(10, 2), nullable=False)

    discount_type   = db.Column(db.String(20), nullable=True)
    discount_value  = db.Column(db.Numeric(10, 2), default=0.00)

    effective_total = db.Column(db.Numeric(10, 2), nullable=False)

    # ================= SERIALIZER =================
    def to_dict(self):
        return {
            "item_id": self.item_id,
            "sale_id": self.sale_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "category": self.category or "",
            "quantity": self.quantity,
            "mrp": float(self.mrp),
            "total_price": float(self.total_price),
            "discount_type": self.discount_type or "Flat",
            "discount_value": float(self.discount_value or 0),
            "effective_total": float(self.effective_total),
        }


# ================= RETURNS =================
class Return(db.Model):
    __tablename__ = "returns"

    return_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)

    sale_id       = db.Column(
        db.Integer,
        db.ForeignKey("sales_master.sale_id"),
        nullable=False
    )

    product_id    = db.Column(
        db.String(30),
        db.ForeignKey("products.product_id"),
        nullable=False
    )

    quantity      = db.Column(db.Integer, nullable=False)
    refund_amount = db.Column(db.Numeric(10, 2), nullable=False)

    date          = db.Column(db.DateTime, default=datetime.utcnow)
    reason        = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "return_id": self.return_id,
            "sale_id": self.sale_id,
            "product_id": self.product_id,
            "quantity": self.quantity,
            "refund_amount": float(self.refund_amount),
            "date": self.date.strftime("%Y-%m-%d %H:%M:%S") if self.date else "",
            "reason": self.reason or "",
        }