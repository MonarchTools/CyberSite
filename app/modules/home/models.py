
from app.extensions import db


class SiteSetting(db.Model):
    __tablename__ = "site_settings"

    id = db.Column(db.Integer, primary_key=True)

    site_name = db.Column(
        db.String(100),
        nullable=False
    )

    site_description = db.Column(
        db.String(255),
        nullable=True
    )
