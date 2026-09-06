"""Shared presentation for the dashboard.

Trading-terminal visual language: black canvas, orange accent, gold for
brand emphasis. Semantic colour (success/warning/danger/info) stays on its
own conventional hues, never orange/gold, so a "blocking issue" badge is
never mistaken for decoration.

Theme is resolved from ``st.context.theme.type`` — the viewer's actual
active theme — rather than ``theme.base``, which only reports the server's
configured default and can't see a manual flip of Streamlit's own theme
switch.

CSS and the animated plexus background live in ``app/assets/`` as real
``.css``/``.html`` files, loaded once at import time, rather than as string
literals in this module.

No emoji anywhere: an internal analytical tool should read as a tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

TONES: tuple[str, ...] = ("neutral", "info", "success", "warning", "danger")

_ASSETS = Path(__file__).parent / "assets"

# app_bg/surface match .streamlit/config.toml's backgroundColor/secondaryBackgroundColor.
_PALETTES = {
    "dark": {
        "app_bg": "#0A0807",
        "surface": "#171310",
        "neutral_bg": "#171310",
        "neutral_fg": "#B8ADA0",
        "info_bg": "#0F2429",
        "info_fg": "#4DD8E8",
        "success_bg": "#12261A",
        "success_fg": "#2ECC71",
        "warning_bg": "#2B2210",
        "warning_fg": "#FFC94A",
        "danger_bg": "#2E1212",
        "danger_fg": "#FF4D4D",
        "border": "#332A1E",
        "muted": "#B8ADA0",
        "orange": "#FF6A00",
        "gold": "#D4AF37",
        "plexus_nodes": ("#FF6A00", "#FFCB47"),
        "plexus_line": "#FFCB47",
    },
    "light": {
        "app_bg": "#FFFDF9",
        "surface": "#FBF3E7",
        "neutral_bg": "#EDE4D3",
        "neutral_fg": "#4A4238",
        "info_bg": "#E3F3F4",
        "info_fg": "#0B5F68",
        "success_bg": "#E7F6EC",
        "success_fg": "#196538",
        "warning_bg": "#FFF3D6",
        "warning_fg": "#6E4D00",
        "danger_bg": "#FBE9E7",
        "danger_fg": "#A6301F",
        "border": "#E7D9C3",
        "muted": "#4A4238",
        "orange": "#C1440E",
        "gold": "#7A5100",
        "plexus_nodes": ("#0891B2", "#22D3EE"),
        "plexus_line": "#0891B2",
    },
}


def _active_theme() -> str:
    """The viewer's actual active theme, falling back to the server default."""
    reported = st.context.theme.type
    if reported in ("light", "dark"):
        return reported
    return "light" if st.get_option("theme.base") == "light" else "dark"


def _root_vars(p: dict[str, str]) -> str:
    """The ``:root { --fe-*: ...; }`` block for one resolved palette."""
    return (
        "<style>:root {"
        f"--fe-neutral-bg:{p['neutral_bg']};--fe-neutral-fg:{p['neutral_fg']};"
        f"--fe-info-bg:{p['info_bg']};--fe-info-fg:{p['info_fg']};"
        f"--fe-success-bg:{p['success_bg']};--fe-success-fg:{p['success_fg']};"
        f"--fe-warning-bg:{p['warning_bg']};--fe-warning-fg:{p['warning_fg']};"
        f"--fe-danger-bg:{p['danger_bg']};--fe-danger-fg:{p['danger_fg']};"
        f"--fe-border:{p['border']};--fe-muted:{p['muted']};"
        f"--fe-orange:{p['orange']};--fe-gold:{p['gold']};--fe-surface:{p['surface']};"
        "}</style>"
    )


_STATIC_CSS = f"\n<style>\n{(_ASSETS / 'dashboard.css').read_text()}\n</style>\n"
_PLEXUS_HTML = (_ASSETS / "plexus.html").read_text()


def inject() -> None:
    """Add the shared stylesheet to the current page.

    Called unconditionally on every run: Streamlit renders each page from
    scratch, so a session-scoped guard would leave the second page unstyled.
    """
    palette = _PALETTES[_active_theme()]
    st.markdown(_root_vars(palette) + _STATIC_CSS, unsafe_allow_html=True)


def animated_background(page: str) -> None:
    """The drifting plexus canvas behind the whole app.

    Call first, before any other content, so it paints earliest and sits
    behind everything else without needing a negative z-index. ``page`` is a
    distinct label (e.g. "home", "data") baked into the markup so this
    component's identity never collides with the same call on another page.
    """
    html = (
        _PLEXUS_HTML.replace("__THEMES_JSON__", json.dumps(_PALETTES))
        .replace("__DEFAULT_THEME__", _active_theme())
        .replace("__PAGE__", page)
    )
    components.html(html, height=1)


def lozenge(text: str, tone: str = "neutral") -> str:
    """A status badge, as HTML to embed in a markdown block."""
    if tone not in TONES:
        tone = "neutral"
    return (
        f'<span class="fe-lozenge" style="background:var(--fe-{tone}-bg);'
        f'color:var(--fe-{tone}-fg)">{text}</span>'
    )


def status_row(name: str, badge: str, meta: str = "") -> str:
    """One line of a status list: name, optional detail, then the badge."""
    detail = f'<span class="fe-row-meta">{meta}</span>' if meta else ""
    return (
        f'<div class="fe-row"><span class="fe-row-name">{name}</span>'
        f"<span>{detail}&nbsp;&nbsp;{badge}</span></div>"
    )


def finding_row(badge: str, where: str, detail: str) -> str:
    """One finding: badge and location on top, the message in full beneath.

    A table clips the message, and the message is the part that explains the
    finding. Here it wraps instead.
    """
    location = f'<span class="fe-finding-where">{where}</span>' if where else ""
    return (
        f'<div class="fe-finding"><div class="fe-finding-head">{badge}{location}</div>'
        f'<div class="fe-finding-detail">{detail}</div></div>'
    )


def eyebrow(text: str) -> str:
    """A small uppercase section label."""
    return f'<div class="fe-eyebrow">{text}</div>'


def page_header(title: str, subtitle: str = "", *, eyebrow_text: str = "FINLYTICS") -> None:
    """The hero block at the top of a page: brand eyebrow, gradient title, subtitle."""
    sub = f'<div class="fe-hero-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="fe-hero">'
        f'<div class="fe-hero-eyebrow">{eyebrow_text}</div>'
        f'<div class="fe-hero-title">{title}</div>'
        f"{sub}"
        f"</div>",
        unsafe_allow_html=True,
    )


def sidebar_brand() -> None:
    """The brand mark under the page nav in the sidebar."""
    st.sidebar.markdown(
        '<div class="fe-sidebar-brand">'
        '<div class="fe-sidebar-mark">Finlytics</div>'
        '<div class="fe-sidebar-name">Forecasting Engine</div>'
        "</div>",
        unsafe_allow_html=True,
    )
