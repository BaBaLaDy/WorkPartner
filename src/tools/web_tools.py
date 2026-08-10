"""Web tools: web_search and web_extract.

web_search uses DuckDuckGo (free, no API key) for web searches.
web_extract fetches a URL and converts its content to Markdown.

Pattern inspired by HermesAgent's built-in web toolset.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------

def web_search(query: str, max_results: int = 10) -> str:
    """Search the web using DuckDuckGo and return top results.

    Returns title, URL, and description for each result.
    Use this to find current information, documentation, or answers
    that are beyond your knowledge cutoff.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (1-20, default 10).
    """
    max_results = max(1, min(max_results, 20))

    DDGS = _import_ddgs()
    if DDGS is None:
        return (
            "Error: ddgs package not installed. "
            "Run: pip install ddgs"
        )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return f"Error searching DuckDuckGo: {e}"

    if not results:
        return f"No results found for '{query}'. Try a shorter or different query."

    lines = [f"## Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        href = r.get("href", "")
        body = r.get("body", "")
        lines.append(f"{i}. **{title}**\n   URL: {href}\n   {body}\n")

    return "\n".join(lines)


def _import_ddgs():
    """Import DDGS from the preferred package (ddgs) with fallback."""
    import warnings
    try:
        from ddgs import DDGS  # >= 9.0 renamed
        return DDGS
    except ImportError:
        pass
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from duckduckgo_search import DDGS  # < 9.0
        return DDGS
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# web_extract
# ---------------------------------------------------------------------------

def web_extract(url: str, max_chars: int = 8000) -> str:
    """Fetch a web page and extract its content as Markdown text.

    Useful for reading documentation, articles, or any web page the user
    references by URL. Returns the page content converted to plain Markdown.
    Content longer than max_chars is truncated.

    Args:
        url: The full URL to fetch (e.g. https://example.com/page).
        max_chars: Maximum characters to return (default 8000, max 20000).
    """
    import urllib.parse

    max_chars = max(500, min(max_chars, 20000))

    # Basic URL validation
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return f"Error: invalid URL '{url}'. Provide a full URL with scheme (https://...)."

    try:
        import httpx
    except ImportError:
        return (
            "Error: httpx package not installed. "
            "Run: pip install httpx"
        )

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as e:
        return f"Error fetching URL: HTTP {e.response.status_code}"
    except Exception as e:
        return f"Error fetching URL: {e}"

    # Convert HTML to Markdown
    text = _html_to_markdown(html)

    if not text or not text.strip():
        return f"No readable content found at {url}."

    # Truncate if needed
    if len(text) > max_chars:
        text = text[:max_chars] + (
            f"\n\n---\n[Content truncated at {max_chars} chars. "
            f"Original: ~{len(text)} chars. Use web_extract with higher max_chars if needed.]"
        )

    return f"## Content from: {url}\n\n{text}"


# ---------------------------------------------------------------------------
# HTML → Markdown conversion (no external dependency needed for basic)
# ---------------------------------------------------------------------------

def _html_to_markdown(html: str) -> str:
    """Convert HTML to plain Markdown text.

    Tries markdownify first (better quality), falls back to a built-in
    regex-based converter if markdownify is not installed.
    """
    try:
        from markdownify import markdownify as md
        return md(html, heading_style="ATX", strip=["script", "style", "nav", "footer", "iframe"]).strip()
    except ImportError:
        pass

    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0
        h.skip_internal_links = True
        text = h.handle(html)
        return _clean_whitespace(text)
    except ImportError:
        pass

    # Fallback: basic tag stripping with a few regex rules
    return _simple_html_to_text(html)


def _simple_html_to_text(html: str) -> str:
    """Basic HTML-to-text fallback when no converter library is available."""
    # Remove script, style, nav, footer, header
    for tag in ("script", "style", "nav", "footer", "header", "noscript", "iframe"):
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Replace block-level elements with newlines
    for tag in ("p", "div", "article", "section", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"):
        html = re.sub(rf"<\s*{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(rf"<\s*/\s*{tag}\s*>", "\n", html, flags=re.IGNORECASE)

    # Replace <br> with newlines
    html = re.sub(r"<\s*br\s*/?\s*>", "\n", html, flags=re.IGNORECASE)

    # Strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)

    # Decode common entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#x27;", "'").replace("&#39;", "'")
    html = html.replace("&nbsp;", " ")

    return _clean_whitespace(html)


def _clean_whitespace(text: str) -> str:
    """Collapse excessive whitespace while preserving paragraph breaks."""
    # Collapse multiple blank lines to max 2
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    # Strip leading/trailing whitespace per line
    lines = [l.strip() for l in text.splitlines()]
    # Remove leading/trailing blank lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
