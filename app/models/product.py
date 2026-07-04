from ..extensions import db


class CategoryGST(db.Model):
    __tablename__ = "category_gst"

    category = db.Column(db.String(80), primary_key=True)
    gst      = db.Column(db.Float,      nullable=False, default=18.0)

    def to_dict(self):
        return {"category": self.category, "gst": self.gst}


class Product(db.Model):
    __tablename__ = "products"

    # ── Primary key ───────────────────────────────────────────────
    product_id    = db.Column(db.String(30),  primary_key=True)

    # ── Core fields (match DB columns exactly) ───────────────────
    name          = db.Column(db.String(150), nullable=False)
    category      = db.Column(db.String(80),  nullable=True)
    supplier_id   = db.Column(
                        db.String(20),
                        db.ForeignKey("suppliers.supplier_id"),
                        nullable=True
                    )
    quantity      = db.Column(db.Integer,     default=0)
    cost_price    = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    unit_price    = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    gst           = db.Column(db.Numeric(5, 2),  nullable=False, default=18.00)
    mrp           = db.Column(db.Numeric(10, 2),  nullable=False, default=0.00)
    reorder_level = db.Column(db.Integer,     default=0)
    qr_code       = db.Column(db.String(120), nullable=True)
    created_at    = db.Column(
                        db.DateTime,
                        server_default=db.func.current_timestamp()
                    )

    # ── Relationships ─────────────────────────────────────────────
    # No backref on supplier — Supplier model already defines .products
    supplier    = db.relationship("Supplier",  lazy="select", foreign_keys=[supplier_id])
    sales_items = db.relationship("SalesItem", backref="product", lazy="dynamic")
    stock_logs  = db.relationship("StockLog",  backref="product", lazy="dynamic")
    audit_logs  = db.relationship("AuditLog",  backref="product", lazy="dynamic")
    returns     = db.relationship("Return",    backref="product", lazy="dynamic")

    # ── Computed properties ───────────────────────────────────────
    @property
    def is_low_stock(self):
        return self.quantity < self.reorder_level

    @property
    def stock_value(self):
        return float(self.quantity) * float(self.cost_price)

    # ── Serialiser ────────────────────────────────────────────────
    def to_dict(self):
        return {
            "product_id":    self.product_id,
            "name":          self.name,
            "category":      self.category or "",
            "supplier_id":   self.supplier_id or "",
            "supplier_name": self.supplier.company if self.supplier else "",
            "quantity":      self.quantity,
            "cost_price":    float(self.cost_price),
            "unit_price":    float(self.unit_price),
            "gst":           float(self.gst),
            "mrp":           float(self.mrp),
            "reorder_level": self.reorder_level,
            "is_low_stock":  self.is_low_stock,
            "qr_code":       self.qr_code or "",
            "created_at":    self.created_at.isoformat() if self.created_at else "",
        }