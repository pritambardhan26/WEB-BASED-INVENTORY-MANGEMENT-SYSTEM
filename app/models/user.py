from datetime import datetime
from flask_login import UserMixin
from ..extensions import db, login_manager
import bcrypt


class Employee(db.Model):
    __tablename__ = "employees"

    emp_id    = db.Column(db.String(20),  primary_key=True)
    name      = db.Column(db.String(120), nullable=False)
    phone     = db.Column(db.String(15),  unique=True, nullable=False)
    email     = db.Column(db.String(120), unique=True, nullable=False)
    role      = db.Column(db.Enum("Admin", "Employee"), nullable=False, default="Employee")
    join_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)

    # Relationship
    user = db.relationship("User", backref="employee", uselist=False,
                           foreign_keys="User.emp_id")

    def to_dict(self):
        return {
            "emp_id":    self.emp_id,
            "name":      self.name,
            "phone":     self.phone,
            "email":     self.email,
            "role":      self.role,
            "join_date": self.join_date.isoformat() if self.join_date else "",
        }


class User(UserMixin, db.Model):
    __tablename__ = "users"

    username          = db.Column(db.String(80),  primary_key=True)
    password          = db.Column(db.String(255),  nullable=False)
    email             = db.Column(db.String(120),  nullable=False)
    role              = db.Column(db.Enum("Admin", "Employee"), nullable=False, default="Employee")
    emp_id            = db.Column(db.String(20), db.ForeignKey("employees.emp_id"), unique=True, nullable=True)
    is_online         = db.Column(db.Boolean, default=False)
    last_login        = db.Column(db.DateTime, nullable=True)
    security_question = db.Column(db.String(255), nullable=True)
    security_answer   = db.Column(db.String(255), nullable=True)
    otp               = db.Column(db.String(10),  nullable=True)
    otp_expiry        = db.Column(db.DateTime,    nullable=True)

    # Flask-Login requires get_id() to return a string
    def get_id(self):
        return self.username

    def check_password(self, raw: str) -> bool:
        stored = self.password.encode()
        return bcrypt.checkpw(raw.encode(), stored)

    def set_password(self, raw: str):
        self.password = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()

    def to_dict(self):
        return {
            "username":   self.username,
            "email":      self.email,
            "role":       self.role,
            "is_online":  self.is_online,
            "last_login": self.last_login.isoformat() if self.last_login else "",
        }


@login_manager.user_loader
def load_user(username: str):
    return User.query.get(username)
