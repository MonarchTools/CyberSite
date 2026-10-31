
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from app.extensions import db


class Admin(UserMixin, db.Model):
    __tablename__ = "admins"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(
            self.password_hash,
            password
        )


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    ip_address = db.Column(
        db.String(45),
        unique=True,
        nullable=False,
        index=True
    )

    failed_attempts = db.Column(
        db.Integer,
        default=0,
        nullable=False
    )

    locked_until = db.Column(
        db.Float,
        nullable=True
    )

    updated_at = db.Column(
        db.Float,
        nullable=False
    )
