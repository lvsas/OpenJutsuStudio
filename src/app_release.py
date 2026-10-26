"""Application SemVer only: independent from recipe/capsule/model versions."""

VERSION = "0.1.0-alpha.1"


def render_release(html: str) -> str:
    """Fill the fixed server-owned label; raw templates keep a truthful fallback."""
    return html.replace('<span data-app-version>v0 alpha</span>',
                        f'<span data-app-version>v{VERSION}</span>')
