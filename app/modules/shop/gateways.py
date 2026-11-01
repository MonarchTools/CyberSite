"""درگاه‌های پرداخت.

- ``ZarinPalGateway``: اتصال به زرین‌پال (API نسخهٔ ۴).
- ``MockGateway``: درگاه آزمایشی؛ فقط در حالت توسعه/تست مجاز است.

مبلغ همیشه از دیتابیس خوانده می‌شود، هرگز از پارامترهای بازگشت از درگاه.
"""

import secrets

import requests
from flask import current_app, url_for


class GatewayError(Exception):
    """خطای درگاه. ``retryable=True`` یعنی وضعیت نامشخص است (مثلاً قطع شبکه)."""

    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class ZarinPalGateway:
    name = "zarinpal"

    def __init__(self, merchant_id, sandbox=False):
        self.merchant_id = (merchant_id or "").strip()
        self.sandbox = sandbox

        if not self.merchant_id:
            raise GatewayError(
                "شناسهٔ پذیرندهٔ زرین‌پال (ZARINPAL_MERCHANT_ID) تنظیم نشده است."
            )

    @property
    def api_base(self):
        if self.sandbox:
            return "https://sandbox.zarinpal.com"
        return "https://payment.zarinpal.com"

    @property
    def pay_base(self):
        if self.sandbox:
            return "https://sandbox.zarinpal.com"
        return "https://www.zarinpal.com"

    def _post(self, path, payload):
        try:
            response = requests.post(
                f"{self.api_base}{path}",
                json=payload,
                headers={"Accept": "application/json"},
                timeout=15,
            )
        except requests.RequestException as error:
            current_app.logger.warning("ZarinPal request failed: %s", error)
            raise GatewayError(
                "ارتباط با درگاه پرداخت برقرار نشد.",
                retryable=True,
            )

        try:
            body = response.json()
        except ValueError:
            body = {}

        if not isinstance(body, dict):
            body = {}

        if response.status_code >= 500:
            raise GatewayError(
                "درگاه پرداخت موقتاً در دسترس نیست.",
                retryable=True,
            )

        return body

    @staticmethod
    def _error_message(body):
        errors = body.get("errors")

        if isinstance(errors, list) and errors:
            errors = errors[0]

        if isinstance(errors, dict) and errors:
            return f"{errors.get('message', 'خطای درگاه')} ({errors.get('code', '?')})"

        return "پاسخ نامعتبر از درگاه پرداخت."

    def start(self, order, callback_url):
        metadata = {
            "mobile": order.phone,
            "order_id": str(order.id),
        }

        if order.email:
            metadata["email"] = order.email

        body = self._post(
            "/pg/v4/payment/request.json",
            {
                "merchant_id": self.merchant_id,
                "amount": int(order.total_rial),
                "currency": "IRR",
                "callback_url": callback_url,
                "description": f"سفارش شمارهٔ {order.id}",
                "metadata": metadata,
            },
        )

        data = body.get("data")

        if isinstance(data, dict) and data.get("code") == 100 and data.get("authority"):
            return str(data["authority"])

        raise GatewayError(self._error_message(body))

    def payment_url(self, authority):
        return f"{self.pay_base}/pg/StartPay/{authority}"

    def verify(self, order):
        body = self._post(
            "/pg/v4/payment/verify.json",
            {
                "merchant_id": self.merchant_id,
                "amount": int(order.total_rial),
                "authority": order.authority,
            },
        )

        data = body.get("data")

        # ۱۰۰: تأیید موفق، ۱۰۱: قبلاً تأیید شده
        if isinstance(data, dict) and data.get("code") in (100, 101):
            return str(data.get("ref_id", ""))

        raise GatewayError(self._error_message(body))


class MockGateway:
    """درگاه آزمایشی برای توسعه و تست؛ هیچ پولی جابه‌جا نمی‌شود."""

    name = "mock"

    @staticmethod
    def _paid():
        return current_app.extensions.setdefault("mock_gateway_paid", set())

    def start(self, order, callback_url):
        return "MOCK" + secrets.token_hex(12)

    def payment_url(self, authority):
        return url_for("shop.mock_pay", authority=authority)

    def mark_paid(self, authority):
        self._paid().add(authority)

    def verify(self, order):
        if order.authority in self._paid():
            return f"MOCK-{order.id}"

        raise GatewayError("پرداخت انجام نشده است.")


def get_gateway():
    name = current_app.config.get("PAYMENT_GATEWAY", "zarinpal")

    if name == "mock":
        if not (current_app.debug or current_app.testing):
            raise GatewayError(
                "درگاه آزمایشی فقط در حالت توسعه فعال می‌شود."
            )
        return MockGateway()

    if name == "zarinpal":
        return ZarinPalGateway(
            current_app.config.get("ZARINPAL_MERCHANT_ID"),
            sandbox=current_app.config.get("ZARINPAL_SANDBOX", False),
        )

    raise GatewayError("درگاه پرداخت نامعتبر تنظیم شده است.")
