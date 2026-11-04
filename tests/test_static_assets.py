"""فایل‌های CSS/JS: هر فایل باید در یک قالب استفاده شود و هر آدرس باید فایل داشته باشد."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent / "app"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"

ASSET = re.compile(r"filename=['\"]((?:css|js)/[A-Za-z0-9_/.-]+\.(?:css|js))['\"]")
IMPORT = re.compile(r"@import\s+(?:url\()?['\"]?([^'\")\s;]+)")


def _referenced():
    found = set()

    for template in TEMPLATES.rglob("*.html"):
        found.update(ASSET.findall(template.read_text(encoding="utf-8-sig")))

    # فایل‌هایی که با @import از یک CSS دیگر بارگذاری می‌شوند
    for name in list(found):
        if name.endswith(".css"):
            text = (STATIC / name).read_text(encoding="utf-8-sig")
            base = (STATIC / name).parent

            for target in IMPORT.findall(text):
                found.add((base / target).resolve().relative_to(STATIC).as_posix())

    return found


def test_every_referenced_asset_exists():
    missing = [n for n in _referenced() if not (STATIC / n).is_file()]

    assert missing == [], f"قالب‌ها به فایل‌های ناموجود اشاره می‌کنند: {missing}"


def test_no_unused_css_or_js_files():
    referenced = _referenced()
    on_disk = {
        p.relative_to(STATIC).as_posix()
        for folder in ("css", "js")
        for p in (STATIC / folder).rglob("*")
        if p.suffix in (".css", ".js")
    }

    unused = sorted(on_disk - referenced)

    assert unused == [], (
        f"این فایل‌ها در هیچ قالبی استفاده نمی‌شوند و باید حذف شوند: {unused}"
    )


def test_theme_init_sets_background_before_css_arrives():
    script = (STATIC / "js" / "theme-init.js").read_text(encoding="utf-8-sig")

    assert "documentElement.style.backgroundColor" in script
    assert "#0E1426" in script and "#FAFAFC" in script
    assert "backgroundColor = \"\"" in (STATIC / "js" / "main.js").read_text(encoding="utf-8-sig")


def test_static_urls_are_versioned_and_cacheable():
    from app import create_app
    from config import Config

    class Cfg(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite://"

    app = create_app(Cfg)

    with app.test_request_context("/"):
        from flask import url_for

        versioned = url_for("static", filename="css/layout.css")
        font = url_for("static", filename="fonts/Vazirmatn-Variable.woff2", v=None)

    assert re.fullmatch(r"/static/css/layout\.css\?v=\d+", versioned)
    assert font == "/static/fonts/Vazirmatn-Variable.woff2"

    response = app.test_client().get(versioned)

    assert response.status_code == 200
    assert "max-age=31536000" in response.headers["Cache-Control"]
    assert "immutable" in response.headers["Cache-Control"]


def test_css_gate_script_comes_after_all_stylesheets():
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8-sig")
    head = base.split("</head>")[0]

    assert "js/css-gate.js" in head
    assert head.rindex("js/css-gate.js") > head.rindex("rel=\"stylesheet\"")
    assert head.rindex("js/css-gate.js") > head.rindex("{% block page_css %}")
