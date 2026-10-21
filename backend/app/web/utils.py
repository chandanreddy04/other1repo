"""Small helpers shared by the web (Jinja/htmx) routes: phone display value,
the HttpOnly auth cookie (set and clear), the one redirect-target validator
(`safe_next_path`), and the store/marketing User-Agent fallback used by the
app-claimed /plans and /subscription browser landers.

Related: app/web/routes_web.py, app/web/routes_htmx_auth.py,
.claude/rules/security.md (redirect-safety rule),
tests/test_web_account_and_landing.py (safe_next_path cases),
tests/test_app_path_fallbacks.py (store_redirect_url cases).
"""

from fastapi.responses import Response

# Canonical store URLs (see tests/test_store_links.py, the single place
# these are pinned against the real App Store Connect id / Play package).
IOS_APP_STORE_URL = "https://apps.apple.com/app/id6787024225"
ANDROID_PLAY_STORE_URL = (
    "https://play.google.com/store/apps/details?id=com.madeithome.app"
)


def store_redirect_url(user_agent: str | None, *, marketing_origin: str) -> str:
    """Where a browser landing on an app-claimed path (/plans, /subscription
    — and /sub, which redirects into /plans) should go. Reaching the server
    means the OS didn't hand the URL to the app: usually no app installed,
    sometimes a Stripe return the OS declined to intercept (the store
    listing then offers "Open"). Send a phone to its store, everything else
    (desktop, an unrecognized UA) to the marketing site.

    A User-Agent sniff is a fallback heuristic, not a security boundary —
    good enough to route a first-time visitor to the right store listing.
    """
    ua = (user_agent or "").lower()
    if "android" in ua:
        return ANDROID_PLAY_STORE_URL
    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return IOS_APP_STORE_URL
    return marketing_origin


# Characters a same-origin path we redirect to never needs. `"`/`'`/`<`/`>`
# are rejected too because next_url is echoed into HTML attributes and into
# fragments/auth_form.html's hx-vals. That hx-vals is now built with
# `|tojson` (security.md), which already makes a quote inert there; the
# rejection is kept as defence in depth — a path never needs these chars.
_FORBIDDEN_NEXT_CHARS = frozenset("\\\"'<>")


def safe_next_path(url: str | None, default: str | None = None) -> str | None:
    """Return `url` if it is a safe same-origin redirect path, else `default`.

    THE redirect-target validator for user-supplied `next`/`back` values
    (security.md) — never restate the check inline. Rejects:
    - anything not starting with `/` (absolute URLs, schemes, "None");
    - `//…` (protocol-relative → another host);
    - any `\\` (browsers normalise `/\\evil.com` to `//evil.com`, which
      matters for the `window.location.replace` in routes_htmx_auth.py);
    - any ASCII control or whitespace character (browsers strip tab/newline
      from URLs, so `/\\t/evil.com` becomes `//evil.com`);
    - any of `"`, `'`, `<`, `>` — a path never needs them (defence in
      depth for the hx-vals in fragments/auth_form.html, which `|tojson`
      already makes safe).
    Percent-encoded forms (`/%5cevil.com`) are left encoded: every redirect
    sink here sends the value as-is, and the browser does not decode `%5c`
    into a separator.
    """
    if not url or not url.startswith("/") or url.startswith("//"):
        return default
    for ch in url:
        if ch in _FORBIDDEN_NEXT_CHARS or ord(ch) <= 0x20 or ord(ch) == 0x7F:
            return default
    return url


def get_phone_display_value(phone: str) -> str:
    """Extract national number from E164 for form display."""
    if phone.startswith("+1"):
        return phone[2:]
    elif phone.startswith("1"):
        return phone[1:]
    return phone


def set_auth_cookie(
    response: Response, access_token: str, max_age: int = 604800
) -> None:
    """Set authentication cookie on a response.

    Args:
        response: FastAPI response object
        access_token: JWT access token
        max_age: Cookie lifetime in seconds (default: 7 days)
    """
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
    )


def clear_auth_cookie(response: Response) -> None:
    """Expire the authentication cookie on a response.

    Mirrors `set_auth_cookie`'s attributes (path `/`, no domain, Secure,
    HttpOnly, SameSite=lax) so the browser matches and drops the same cookie.
    """
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=True,
        samesite="lax",
    )
