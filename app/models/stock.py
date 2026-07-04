from datetime import datetime
from ..extensions import db


class StockLog(db.Model):
    __tablename__ = "stock_logs"

    log_id       = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    product_id   = db.Column(db.String(30),  db.ForeignKey("products.product_id"),  nullable=True)
    product_name = db.Column(db.String(150), nullable=False)
    change_type  = db.Column(db.Enum("IN", "OUT"), nullable=False)
    quantity     = db.Column(db.Integer,     nullable=False)
    reason       = db.Column(db.Text,        nullable=True)
    changed_by   = db.Column(db.String(80),  db.ForeignKey("users.username"), nullable=True)
    date         = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "log_id":       self.log_id,
            "product_id":   self.product_id or "",
            "product_name": self.product_name,
            "change_type":  self.change_type,
            "quantity":     self.quantity,
            "reason":       self.reason or "",
            "changed_by":   self.changed_by or "",
            "date":         self.date.strftime("%Y-%m-%d %H:%M:%S") if self.date else "",
        }


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id         = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    timestamp  = db.Column(db.DateTime,   default=datetime.utcnow)
    user       = db.Column(db.String(80), nullable=True)
    action     = db.Column(db.String(20), nullable=True)   # ADD / EDIT / DELETE
    product_id = db.Column(
                     db.String(30),
                     db.ForeignKey("products.product_id", ondelete="SET NULL"),
                     nullable=True
                 )
    details    = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id":         self.id,
            "timestamp":  self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "",
            "user":       self.user or "",
            "action":     self.action or "",
            "product_id": self.product_id or "",
            "details":    self.details or "",
        }