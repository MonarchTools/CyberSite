import os


class Config:

    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "change-this-secret-key"
    )

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///cybersite.db"
    )
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    SQLALCHEMY_TRACK_MODIFICATIONS = False
