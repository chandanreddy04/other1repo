"""Guard: every App Store / Play Store link in the web app points at the real app.

Store links were previously broken in several places — an iOS URL with a name
slug but no app ID (`apps.apple.com/app/made-it-home`, which Apple does not
resolve), a Play URL with the wrong package (`id=app.madeithome` instead of
`com.madeithome.app`), and dead `href="#"` badges. These links live hardcoded
in Jinja templates + inline-HTML routes (no shared config), so this test scans
them all and fails on any regression.

Related: docs/mobile-release.md (store identifiers), the mobile bundle id
`com.madeithome.app`, and the App Store Connect app id `6787024225`.
"""

import re
from pathlib import Path

# Canonical, correct store identifiers — the single source of truth for the test.
IOS_APP_ID = "6787024225"
ANDROID_PACKAGE = "com.madeithome.app"

IOS_URL = f"https://apps.apple.com/app/id{IOS_APP_ID}"
ANDROID_URL = f"https://play.google.com/store/apps/details?id={ANDROID_PACKAGE}"

WEB_DIR = Path(__file__).resolve().parent.parent / "app" / "web"

APPLE_RE = re.compile(r"https://apps\.apple\.com/[^\s\"'<>]+")
PLAY_RE = re.compile(r"https://play\.google\.com/store/apps/details\?id=[^\s\"'<>&]+")


def _web_source_files() -> list[Path]:
    files = list(WEB_DIR.rglob("*.html")) + list(WEB_DIR.rglob("routes_*.py"))
    assert files, "no web source files found — path wrong?"
    return files


def test_every_apple_store_link_uses_the_real_app_id():
    offenders = []
    for path in _web_source_files():
        for url in APPLE_RE.findall(path.read_text()):
            # Only App Store product links (not AASA/media badges) must carry the id.
            if "/app/" in url and url != IOS_URL:
                offenders.append(f"{path.name}: {url}")
    assert not offenders, (
        "App Store links must be exactly "
        f"{IOS_URL} (name-slug URLs without /id<number> don't resolve): "
        + "; ".join(offenders)
    )


def test_every_play_store_link_uses_the_real_package():
    offenders = []
    for path in _web_source_files():
        for url in PLAY_RE.findall(path.read_text()):
            if url != ANDROID_URL:
                offenders.append(f"{path.name}: {url}")
    assert not offenders, (
        f"Play Store links must use id={ANDROID_PACKAGE}: " + "; ".join(offenders)
    )


def test_no_dead_placeholder_store_buttons():
    # A store badge/button that links nowhere (href="#") is a shipped dead link.
    offenders = []
    for path in WEB_DIR.rglob("*.html"):
        for line in path.read_text().splitlines():
            if 'href="#"' in line and ("app-store" in line or "store-btn" in line):
                offenders.append(f"{path.name}: {line.strip()[:80]}")
    assert not offenders, "dead store buttons (href='#'): " + "; ".join(offenders)
