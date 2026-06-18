"""HTML stripper: removes paywalls, overlays, cookie banners, popups."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

# ── Patterns for elements to nuke ──────────────────────────────────────────

# Class/id fragments commonly used by paywalls/overlays/modals
NUKE_PATTERNS = [
    # Paywalls & subscription gates
    r"paywall", r"gate", r"premium[-_]?(gate|content|overlay|wall)",
    r"subscription[-_]?(gate|modal|overlay|banner|prompt|wrapper)",
    r"regwall", r"metered", r"subs?[-_]?(container|overlay|modal)",
    r"trial[-_]?(banner|overlay)",
    r"article[-_]?limit", r"read[-_]?limit",
    r"access[-_]?(gate|overlay|wall)", r"locked[-_]?content",
    r"signin[-_]?wall", r"login[-_]?prompt",
    r"free[-_]?article[-_]?limit",

    # Cookie / GDPR / consent banners
    r"cookie", r"gdpr", r"consent", r"ccpa", r"cmp[-_]?(wrapper|container|banner)",
    r"notice[-_]?(banner|overlay|bar)", r"privacy[-_]?(banner|notice|bar)",
    r"cookie[-_]?(bar|banner|notice|consent|wall|popup)",

    # Newsletter / signup mid-article
    r"newsletter[-_]?(signup|modal|popup|cta|banner|form|inline)",
    r"email[-_]?(signup|capture|gate)",
    r"signup[-_]?(prompt|form|wrapper)", r"subscribe[-_]?(cta|form)",
    r"registration[-_]?(module|form|prompt)",
    r"inline[-_]?(subscribe|signup|cta)",

    # Modals / overlays
    r"modal", r"overlay", r"popup", r"pop[-_]?up",
    r"dialog[_-]?(container|wrapper|overlay)",
    r"lightbox", r"fancybox", r"reveal[-_]?(modal|overlay)",
    r"backdrop", r"screen[-_]?cover",
    r"interstitial", r"layer[-_]?(wrapper|overlay)",
    r"slide[-_]?(in|out|up|down|overlay)",
    r"fixed[-_]?(bottom|top|cta|banner|bar)",
    r"sticky[-_]?(banner|footer|header|bar|bottom|cta)",

    # Blockers / walls
    r"blocker", r"wall", r"shield",
    r"gatekeeper", r"content[-_]?gate",
]

# Combine into one big case-insensitive regex
NUKE_RE = re.compile("|".join(NUKE_PATTERNS), re.I)

# Specific tag combos we always nuke
NUKE_TAGS = {"script", "noscript"}

# Attributes that suggest an overlay (inline styles or data attributes)
OVERLAY_STYLE_PATTERNS = [
    re.compile(r"position\s*:\s*fixed", re.I),
    re.compile(r"position\s*:\s*sticky", re.I),
    re.compile(r"z-index\s*:\s*\d{4,}", re.I),  # z-index >= 1000
]

OVERLAY_DATA_ATTRS = [
    re.compile(r"data-.*(?:overlay|modal|popup|paywall|gate)", re.I),
]


def _has_nuke_pattern(element: Tag) -> bool:
    """Check class/id/data attributes against nuke patterns."""
    if element.attrs is None:
        return False
    for attr_name in ("id", "class", "data-component", "data-module", "role"):
        vals = element.get(attr_name)
        if vals is None:
            continue
        if isinstance(vals, list):
            vals = " ".join(str(v) for v in vals)
        else:
            vals = str(vals)
        if NUKE_RE.search(vals):
            return True
    return False


def _is_overlay_by_style(element: Tag) -> bool:
    """Check inline style for fixed/sticky positioning or high z-index."""
    if element.attrs is None:
        return False
    style = element.get("style", "")
    if not style:
        return False
    return any(p.search(style) for p in OVERLAY_STYLE_PATTERNS)


def _is_overlay_by_data(element: Tag) -> bool:
    """Check data attributes."""
    if element.attrs is None:
        return False
    for attr in element.attrs:
        if any(p.search(attr) for p in OVERLAY_DATA_ATTRS):
            return True
    return False


def _is_visible(element: Tag) -> bool:
    """Quick check: element not hidden."""
    if element.attrs is None:
        return True  # can't determine visibility, keep it
    style = element.get("style", "") or ""
    if re.search(r"display\s*:\s*none", style, re.I):
        return False
    if re.search(r"visibility\s*:\s*hidden", style, re.I):
        return False
    return True


def _has_only_nuke_children(element: Tag) -> bool:
    """If all visible children would be nuked, nuke the parent too."""
    visible_children = [
        c for c in element.children
        if isinstance(c, Tag) and _is_visible(c)
    ]
    if not visible_children:
        return False
    return all(_should_nuke(c) for c in visible_children)


def _should_nuke(element: Tag) -> bool:
    """Composite decision: should this element be removed?"""
    if not _is_visible(element):
        return False

    if element.name in NUKE_TAGS:
        return True

    # Check paywall/overlay patterns
    if _has_nuke_pattern(element):
        return True

    # Check style-based overlays
    if _is_overlay_by_style(element):
        return True

    # Check data attributes
    if _is_overlay_by_data(element):
        return True

    return False


def strip_page(html: str, base_url: str) -> str:
    """Strip paywalls, overlays, cookie banners from HTML and return clean page."""
    soup = BeautifulSoup(html, "lxml")

    # ── Pass 1: Strip nukable elements ──────────────────────────────
    changed = True
    while changed:
        changed = False
        for element in soup.find_all(True):
            if not isinstance(element, Tag):
                continue
            if _should_nuke(element):
                element.decompose()
                changed = True

    # ── Pass 2: Remove empty container wrappers ─────────────────────
    for element in soup.find_all(True):
        if not isinstance(element, Tag):
            continue
        # Don't strip <body>, <html>, <head>
        if element.name in ("html", "head", "body", "meta", "link", "base", "title"):
            continue
        # Remove empty block elements (after stripping nuked children and whitespace)
        text = element.get_text(strip=True)
        if not text and element.name in (
            "div", "section", "article", "aside", "nav", "header",
            "footer", "span", "main", "figure", "details"
        ):
            element.decompose()

    # ── Pass 3: Rewrite relative URLs to absolute ──────────────────
    for tag, attr in [("a", "href"), ("img", "src"), ("link", "href"),
                       ("script", "src"), ("source", "src"), ("video", "src"),
                       ("audio", "src"), ("iframe", "src")]:
        for element in soup.find_all(tag):
            if element.attrs is None:
                continue
            val = element.get(attr)
            if val and not val.startswith(("http://", "https://", "//", "data:", "#", "javascript:")):
                if val.startswith("//"):
                    element[attr] = "https:" + val
                else:
                    element[attr] = urljoin(base_url, val)

    # ── Pass 4: Set viewport for mobile ────────────────────────────
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if not viewport:
        meta = soup.new_tag("meta")
        meta["name"] = "viewport"
        meta["content"] = "width=device-width, initial-scale=1.0"
        if soup.head:
            soup.head.append(meta)
        else:
            head = soup.new_tag("head")
            head.append(meta)
            if soup.html:
                soup.html.insert(0, head)

    # ── Pass 5: Inject a small CSS to prevent scroll-locking ──────
    style_tag = soup.new_tag("style")
    style_tag.string = """
        body { overflow: auto !important; }
        html { overflow: auto !important; }
        [style*="overflow: hidden"] { overflow: auto !important; }
    """
    if soup.head:
        soup.head.append(style_tag)

    return str(soup)
