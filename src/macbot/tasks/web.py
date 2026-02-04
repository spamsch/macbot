"""Tasks: Web Fetch and Search

Simple web tasks for fetching content and searching.
Use these for quick lookups instead of browser automation.
"""

import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx

from macbot.tasks.base import Task


def html_to_text(html: str, max_length: int = 10000) -> str:
    """Convert HTML to readable plain text.

    Args:
        html: Raw HTML content
        max_length: Maximum text length to return

    Returns:
        Extracted text content
    """
    # Remove script and style elements
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<noscript[^>]*>.*?</noscript>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

    # Replace common block elements with newlines
    html = re.sub(r'<(br|hr|p|div|li|tr|h[1-6])[^>]*>', '\n', html, flags=re.IGNORECASE)

    # Remove remaining HTML tags
    text = re.sub(r'<[^>]+>', '', html)

    # Decode common HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces to single
    text = re.sub(r'\n\s*\n', '\n\n', text)  # Multiple newlines to double
    text = text.strip()

    if len(text) > max_length:
        text = text[:max_length] + "... [truncated]"

    return text


class WebFetchTask(Task):
    """Fetch and read content from a URL.

    Use this for simple web lookups - fetches the page and extracts
    readable text content. Much faster than browser automation.

    For interactive websites that require JavaScript, use browser_* tasks instead.
    """

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a web page and extract readable text content. "
            "Use this for simple lookups (articles, documentation, static pages). "
            "For JavaScript-heavy sites or forms, use browser_* tasks instead."
        )

    async def execute(
        self,
        url: str,
        max_length: int = 10000,
    ) -> dict[str, Any]:
        """Fetch a URL and extract text content.

        Args:
            url: The URL to fetch.
            max_length: Maximum text length to return (default 10000).

        Returns:
            Dictionary with url, title, and text content.
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                html = response.text

                # Extract title
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                title = html_to_text(title_match.group(1)) if title_match else ""

                # Extract text content
                text = html_to_text(html, max_length)

                return {
                    "success": True,
                    "url": str(response.url),
                    "title": title,
                    "content": text,
                }
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}"}
        except httpx.RequestError as e:
            return {"success": False, "error": f"Request failed: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class WebSearchTask(Task):
    """Search the web using DuckDuckGo.

    Use this for quick web searches. Returns top results with titles,
    URLs, and snippets. No API key required.

    For more control or JavaScript-rendered results, use browser_* tasks.
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web using DuckDuckGo. Returns titles, URLs, and snippets. "
            "Use this for quick lookups. For complex searches or JS-heavy sites, "
            "use browser_navigate + browser_snapshot instead."
        )

    async def execute(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict[str, Any]:
        """Search the web.

        Args:
            query: Search query.
            max_results: Maximum number of results to return (default 5).

        Returns:
            Dictionary with search results.
        """
        try:
            # Use DuckDuckGo HTML search (no API key needed)
            search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            ) as client:
                response = await client.get(search_url)
                response.raise_for_status()

                html = response.text

                # Parse search results from DuckDuckGo HTML
                results = []

                # Find result blocks
                result_pattern = re.compile(
                    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                    re.DOTALL | re.IGNORECASE
                )

                for match in result_pattern.finditer(html):
                    if len(results) >= max_results:
                        break

                    url = match.group(1)
                    title = html_to_text(match.group(2))
                    snippet = html_to_text(match.group(3))

                    # DuckDuckGo wraps URLs - extract actual URL
                    if "uddg=" in url:
                        url_match = re.search(r'uddg=([^&]+)', url)
                        if url_match:
                            from urllib.parse import unquote
                            url = unquote(url_match.group(1))

                    if title and url:
                        results.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                        })

                if not results:
                    return {
                        "success": True,
                        "query": query,
                        "results": [],
                        "message": "No results found",
                    }

                return {
                    "success": True,
                    "query": query,
                    "results": results,
                }

        except httpx.RequestError as e:
            return {"success": False, "error": f"Search failed: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


def register_web_tasks(registry) -> None:
    """Register web tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(WebFetchTask())
    registry.register(WebSearchTask())
