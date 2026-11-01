"""رندر امن متن پست‌ها، بدون وابستگی خارجی.

اصل کار: ابتدا همهٔ متن escape می‌شود و فقط بعد از آن چند الگوی ساده به برچسب‌های
ثابت و مجاز تبدیل می‌شوند. هیچ HTML خامی از ورودی عبور نمی‌کند، پس نیازی به
پاک‌ساز (sanitizer) جدا نیست.

فرمت‌های پشتیبانی‌شده:

    ## عنوان بخش          ### عنوان زیربخش         (# هم مثل ## است)
    **پررنگ**   *مورب*   `کد`   [متن](https://example.com)
    - مورد لیست        1. مورد لیست شماره‌دار
    > نقل‌قول
    ```
    بلوک کد
    ```

پیوندها فقط با http، https یا مسیر داخلی (که با / شروع شود) پذیرفته می‌شوند؛
javascript: و data: و مانند آن به متن ساده تبدیل می‌شوند.
"""

import re

from markupsafe import Markup, escape


MAX_LENGTH = 20_000

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FENCE = re.compile(r"^```")
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_UNORDERED = re.compile(r"^[-*]\s+(.*)$")
_ORDERED = re.compile(r"^\d{1,3}[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")

_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")

# آدرس بعد از escape بررسی می‌شود؛ نقل‌قول‌ها در آن دیگر به شکل &#34; هستند
_SAFE_URL = re.compile(r"^(?:https?://[^\s]+|/(?!/)[^\s]*)$", re.IGNORECASE)

_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


def _inline(raw):
    """یک خط متن خام را به HTML امن تبدیل می‌کند."""
    text = str(escape(raw))
    stash = []

    def keep(html):
        stash.append(html)
        return _PLACEHOLDER.format(len(stash) - 1)

    text = _CODE_SPAN.sub(
        lambda m: keep(f"<code>{m.group(1)}</code>"), text
    )

    def link(match):
        label, url = match.group(1), match.group(2)

        if not _SAFE_URL.match(url):
            return match.group(0)

        return keep(
            f'<a href="{url}" rel="nofollow noopener noreferrer">{label}</a>'
        )

    text = _LINK.sub(link, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)

    return _PLACEHOLDER_RE.sub(lambda m: stash[int(m.group(1))], text)


def _list(lines, pattern, tag):
    items = "".join(
        f"<li>{_inline(pattern.match(line).group(1))}</li>" for line in lines
    )
    return f"<{tag}>{items}</{tag}>"


def _block(lines):
    if len(lines) == 1:
        heading = _HEADING.match(lines[0])

        if heading:
            level = max(len(heading.group(1)), 2)
            return f"<h{level}>{_inline(heading.group(2).strip())}</h{level}>"

    if all(_UNORDERED.match(line) for line in lines):
        return _list(lines, _UNORDERED, "ul")

    if all(_ORDERED.match(line) for line in lines):
        return _list(lines, _ORDERED, "ol")

    if all(_QUOTE.match(line) for line in lines):
        inner = "<br>".join(_inline(_QUOTE.match(l).group(1)) for l in lines)
        return f"<blockquote>{inner}</blockquote>"

    return "<p>" + "<br>".join(_inline(line) for line in lines) + "</p>"


def render_body(text):
    """متن خام پست را به HTML امن (Markup) تبدیل می‌کند."""
    text = _CONTROL_CHARS.sub("", (text or "")[:MAX_LENGTH])
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    output = []
    paragraph = []
    code = None

    def flush():
        if paragraph:
            output.append(_block(paragraph))
            paragraph.clear()

    for line in lines:
        if code is not None:
            if _FENCE.match(line.strip()):
                output.append(
                    "<pre><code>" + str(escape("\n".join(code))) + "</code></pre>"
                )
                code = None
            else:
                code.append(line)
            continue

        if _FENCE.match(line.strip()):
            flush()
            code = []
            continue

        stripped = line.strip()

        if not stripped:
            flush()
        elif _HEADING.match(stripped):
            # عنوان بدون نیاز به خط خالی دور آن، بلوک مستقل است
            flush()
            output.append(_block([stripped]))
        else:
            paragraph.append(stripped)

    flush()

    if code is not None:
        # بلوک کدِ بسته‌نشده تا انتها کد حساب می‌شود
        output.append(
            "<pre><code>" + str(escape("\n".join(code))) + "</code></pre>"
        )

    return Markup("\n".join(output))
