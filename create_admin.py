
from pathlib import Path
from getpass import getpass

from dotenv import load_dotenv

# .env باید پیش از import کردن app (و config) خوانده شود
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from app import create_app
from app.extensions import db
from app.modules.admin.models import Admin

app = create_app()

with app.app_context():
    print("\n=== CyberSite Admin Setup ===\n")

    username = input("Admin username: ").strip()

    if len(username) < 3:
        raise SystemExit("Username must contain at least 3 characters.")

    if Admin.query.filter_by(username=username).first():
        raise SystemExit("This username already exists.")

    password = getpass("Admin password: ")
    confirm = getpass("Confirm password: ")

    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")

    if password != confirm:
        raise SystemExit("Passwords do not match.")

    admin = Admin(username=username)
    admin.set_password(password)

    db.session.add(admin)
    db.session.commit()

    print("\nAdmin account created successfully.")
