"""صفحه‌های خطای فارسی و هماهنگ با ظاهر سایت."""

from flask import render_template

from app.extensions import db


MESSAGES = {
    403: ("دسترسی ندارید", "اجازهٔ دیدن این صفحه را ندارید."),
    404: ("صفحه پیدا نشد", "آدرسی که باز کردید وجود ندارد یا جابه‌جا شده است."),
    405: ("درخواست مجاز نیست", "این صفحه با این روش قابل استفاده نیست."),
    413: ("فایل خیلی بزرگ است", "حجم فایل انتخاب‌شده بیشتر از حد مجاز (۵ مگابایت) است."),
    429: ("درخواست‌های زیاد", "کمی صبر کنید و دوباره تلاش کنید."),
    500: ("خطای سرور", "مشکلی پیش آمد. دوباره تلاش کنید؛ اگر ادامه داشت خبر بدهید."),
}


def register_error_handlers(app):
    def make_handler(code):
        title, message = MESSAGES[code]

        def handler(error):
            if code == 500:
                db.session.rollback()

            return render_template(
                "errors/error.html", code=code, title=title, message=message
            ), code

        return handler

    for code in MESSAGES:
        app.register_error_handler(code, make_handler(code))
