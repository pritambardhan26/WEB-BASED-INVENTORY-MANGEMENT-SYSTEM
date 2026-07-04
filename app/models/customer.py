from datetime import datetime
from ..extensions import db


class Customer(db.Model):
    __tablename__ = "customers"

    customer_id = db.Column(db.String(20), primary_key=True)

    name  = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(15), unique=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # ================= RELATIONSHIP =================
    # Link via phone → sales_master.customer_phone
    sales = db.relationship(
        "SalesMaster",
        backref="customer",
        primaryjoin="Customer.phone == foreign(SalesMaster.customer_phone)",
        lazy=True
    )

    # ================= SERIALIZER =================
    def to_dict(self):
        return {
            "customer_id": self.customer_id,
            "name": self.name or "",
            "phone": self.phone or "",
            "email": self.email or "",
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else ""
        }