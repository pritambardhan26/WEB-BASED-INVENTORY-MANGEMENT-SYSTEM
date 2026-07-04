from datetime import datetime
from ..extensions import db


class Supplier(db.Model):
    __tablename__ = "suppliers"

    supplier_id = db.Column(db.String(20),  primary_key=True)
    name        = db.Column(db.String(120), nullable=False)
    company     = db.Column(db.String(120), nullable=True)   # nullable per schema
    phone       = db.Column(db.String(15),  unique=True,  nullable=True)
    email       = db.Column(db.String(120), nullable=True)
    address     = db.Column(db.Text,        nullable=True)
    created_at  = db.Column(
                      db.DateTime,
                      server_default=db.func.current_timestamp()
                  )

    # `products` backref is defined on Product — using back_populates here
    # would require changes on Product too; simplest is letting Product own it.
    # Supplier just accesses supplier_instance.products via the Product backref.

    def to_dict(self):
        return {
            "supplier_id": self.supplier_id,
            "name":        self.name,
            "company":     self.company or "",
            "phone":       self.phone or "",
            "email":       self.email or "",
            "address":     self.address or "",
            "created_at":  self.created_at.isoformat() if self.created_at else "",
        }