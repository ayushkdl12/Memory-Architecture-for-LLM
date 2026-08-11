"""Web search for the chat pipeline (ChatGPT Search / Claude Web Search analogue).

Providers:
  - "duckduckgo": free, no API key (HTML endpoint). Default.
  - "tavily": better quality, requires a free TAVILY_API_KEY.

`should_search()` is the trigger heuristic: informational queries get live web
context; personal/memory queries stay local.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

import httpx

from .llm import LLMError

SEARCH_TRIGGERS = (
    "what is", "what are", "what's", "who is", "when", "where", "why",
    "how to", "how does", "how do", "latest", "news", "weather", "price",
    "vs", "vs.", "explain", "difference", "best", "top ", "review",
    "current", "today", "stock", "who won", "deadline for", "meaning",
    "tutorial", "guide", "update", "2024", "2025", "2026",
)

PERSONAL_HINTS = (
    "my name", "i prefer", "my age", "my birthday", "my phone", "my email",
    "do i like", "what do i", "my goal", "my deadline", "remember",
    "my manager", "my team", "the photo", "the doc", "that pdf",
)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def should_search(query: str) -> bool:
    """Heuristic: search only clearly informational, non-personal queries."""
    q = query.lower().strip()
    if q.startswith("/search"):
        return True
    if len(q) < 15 or len(q) > 400:
        return False
    if any(p in q for p in PERSONAL_HINTS):
        return False
    return any(t in q for t in SEARCH_TRIGGERS)


class DuckDuckGoProvider:
    name = "duckduckgo"

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=25)

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            resp = self.http.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/126.0 Safari/537.36"
                },
            )
            resp.raise_for_status()
        except Exception as exc:
            raise LLMError(f"DuckDuckGo search failed: {exc}") from exc
        return self._parse(resp.text, max_results)

    def _parse(self, page: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        # <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=<enc>&rut=...">Title</a>
        for m in re.finditer(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page
        ):
            href, title = m.group(1), html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
            url = self._real_url(href)
            if not url:
                continue
            results.append(SearchResult(title=title.strip(), url=url, snippet=""))
            if len(results) >= max_results:
                break
        # <a class="result__snippet" ...>...</a> — attach snippets by order
        snippets = list(re.finditer(r'class="result__snippet"[^>]*>(.*?)</a>', page))
        for i, sn in enumerate(snippets[: len(results)]):
            results[i].snippet = html.unescape(
                re.sub(r"<[^>]+>", "", sn.group(1))
            ).strip()
        return results

    @staticmethod
    def _real_url(href: str) -> str:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return unquote(m.group(1))
        if href.startswith("http"):
            return href
        return ""


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=30)

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        resp = self.http.post(
            "https://api.tavily.com/search",
            json={"api_key": self.api_key, "query": query, "max_results": max_results},
        )
        resp.raise_for_status()
        out = []
        for r in resp.json().get("results", []):
            out.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                )
            )
        return out[:max_results]


class SearchService:
    def __init__(
        self,
        provider: str = "duckduckgo",
        tavily_api_key: str = "",
        max_results: int = 5,
        char_budget: int = 1200,
    ):
        self.max_results = max_results
        self.char_budget = char_budget
        if provider == "tavily":
            if not tavily_api_key.strip():
                raise LLMError("SEARCH_PROVIDER=tavily requires TAVILY_API_KEY")
            self._provider = TavilyProvider(tavily_api_key)
        else:
            self._provider = DuckDuckGoProvider()

    def search(self, query: str) -> list[SearchResult]:
        return self._provider.search(query, self.max_results)

    def format_context(self, results: list[SearchResult]) -> str:
        """Numbered, budget-limited block injected into the system prompt."""
        if not results:
            return ""
        lines = ["<web search results>"]
        budget = self.char_budget
        for i, r in enumerate(results, 1):
            snip = r.snippet[: budget]
            budget -= len(snip) + 64
            lines.append(f"[{i}] {r.title}\n    {r.url}\n    {snip}")
            if budget <= 80:
                break
        lines.append("</web search results>")
        lines.append(
            "If you used the web results above, cite them inline like [1], [2] "
            "and give the source URLs."
        )
        return "\n".join(lines)
