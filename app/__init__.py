from app.modules.products.models import Product, Category
from app.modules.home.models import SiteSetting
from app.modules.admin.models import Admin
from app.modules.shop.models import Order, OrderItem
from app.modules.contact.models import ContactMessage
from app.modules.customers.models import Customer
from app.modules.blog.models import Post
from pathlib import Path
from flask import Flask

from config import Config
from app.extensions import db, login_manager, csrf
from app.security import ensure_secret_key, init_security
from app.db_upgrade import upgrade_schema
from app.errors import register_error_handlers
from app.seo import init_seo
from app.static_cache import init_static_cache


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    init_static_cache(app)
    ensure_secret_key(app)
    init_security(app)
    register_error_handlers(app)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "admin.login"
    login_manager.session_protection = "strong"
    login_manager.login_message = "برای دسترسی ابتدا وارد شوید."
    login_manager.login_message_category = "warning"

    from app.modules.home.models import SiteSetting
    from app.modules.admin.models import Admin

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(Admin, int(user_id))
        except (TypeError, ValueError):
            return None

    from app.modules.home.routes import home_bp
    from app.modules.products.routes import products_bp
    from app.modules.blog.routes import blog_bp
    from app.modules.admin.routes import admin_bp
    from app.modules.contact.routes import contact_bp
    from app.modules.shop.routes import shop_bp
    from app.modules.slides.routes import slides_bp
    from app.modules.content.routes import content_bp
    from app.modules.comments.routes import comments_bp
    from app.modules.seo.routes import seo_bp
    from app.modules.stats.routes import stats_bp
    from app.modules.customers.routes import customers_bp
    from app.modules.customers.auth import current_customer
    from app.modules.comments import models as _comment_models  # noqa: F401 - برای create_all
    from app.modules.content import models as _content_models  # noqa: F401 - برای create_all
    from app.modules.content.service import get_text
    from app.modules.slides import models as _slide_models  # noqa: F401 - برای create_all
    from app.modules.shop.services import cart_count
    from app.utils import format_rial

    app.register_blueprint(home_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(contact_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(slides_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(comments_bp)
    app.register_blueprint(seo_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(customers_bp)
    init_seo(app)

    app.jinja_env.filters["rial"] = format_rial

    @app.context_processor
    def inject_cart_count():
        return {"cart_item_count": cart_count()}

    @app.context_processor
    def inject_customer():
        # مشتری واردشده (یا None)؛ جدا از Flask-Login که فقط برای مدیر است
        return {"customer": current_customer()}

    @app.context_processor
    def inject_site_content():
        # c('کلید') = متن ویرایش‌شدهٔ مدیر یا متن پیش‌فرض
        return {"c": get_text}

    with app.app_context():
        db.create_all()
        upgrade_schema()

        if not db.session.get(SiteSetting, 1):
            db.session.add(
                SiteSetting(
                    id=1,
                    site_name="CyberSite",
                    site_description="Personal Cyber Platform"
                )
            )
            db.session.commit()

    return app
