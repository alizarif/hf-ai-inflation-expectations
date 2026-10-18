"""One shared news search per topic per wave; results are captured and frozen.

Primary: a single OpenRouter call per topic using the Exa web-search server tool
(~$0.007 per search). Every returned citation (title, URL, excerpt) is kept.
Fallback: Google News RSS (free) if the search fails or returns too few items.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests

from .config import stable_hash

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
RSS_BASE = "https://news.google.com/rss"
RSS_PARAMS = "hl=en-US&gl=US&ceid=US:en"


def _clean(text: str | None) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


def _domain(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host.removeprefix("www.")


SECTION_WORDS = {"news", "hub", "section", "topic", "topics", "category", "latest", "politics", "business",
                 "economy", "entertainment", "world", "us", "en", "en-us", "home", "index.html"}


def is_article(url: str) -> bool:
    """True for an individual story; False for homepages, section fronts and aggregators."""
    parsed = urllib.parse.urlparse(url)
    if _domain(url) in {"news.google.com", "google.com", "msn.com", "news.yahoo.com"}:
        return False
    segments = [seg for seg in parsed.path.split("/") if seg]
    if not segments or all(seg.lower() in SECTION_WORDS for seg in segments):
        return False
    for seg in segments:
        if len(seg.split("-")) >= 3 or re.search(r"\d{4,}", seg) or re.search(r"[a-z0-9]{12,}", seg.lower()):
            return True
    return False


def search_openrouter(client, cfg: dict, query: str, today: str) -> tuple[list[dict], dict]:
    s = cfg["search"]
    prompt = (
        f"Today is {today}. Use the web search tool once with this query: \"{query}\". "
        "Look for individual news articles published in the last day, not homepages or section pages. "
        "Then list every result you received, one line each, with its title and URL. Do not add commentary."
    )
    call = client.chat(
        s["searcher_model"],
        [{"role": "user", "content": prompt}],
        tools=[{"type": "openrouter:web_search",
                "parameters": {"engine": "exa", "max_results": s["max_results"]}}],
        max_tool_calls=2,
    )
    items, seen = [], set()
    for ann in call.get("annotations", []):
        cit = ann.get("url_citation") if ann.get("type") == "url_citation" else None
        if not cit or not cit.get("url") or cit["url"] in seen or not is_article(cit["url"]):
            continue
        seen.add(cit["url"])
        items.append({
            "title": _clean(cit.get("title")),
            "url": cit["url"],
            "source": _domain(cit["url"]),
            "published": cit.get("published_date") or cit.get("published") or "",
            "excerpt": _clean(cit.get("content")),
        })
    return items[: s.get("keep_articles", len(items))], call


def search_rss(query: str | None, max_items: int, timeout: int = 45) -> tuple[list[dict], dict]:
    if query.startswith("top news stories"):   # general arm -> Google News front page
        url = f"{RSS_BASE}?{RSS_PARAMS}"
    else:
        q = urllib.parse.quote(f"{re.sub(r' [A-Z][a-z]+ \d{1,2}, \d{4}$', '', query)} when:1d")
        url = f"{RSS_BASE}/search?q={q}&{RSS_PARAMS}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "hf-ai-inflation-expectations/1.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        if len(items) >= max_items:
            break
        src = it.find("source")
        items.append({
            "title": _clean(it.findtext("title")),
            "url": _clean(it.findtext("link")),
            "source": _clean(src.text if src is not None else ""),
            "published": _clean(it.findtext("pubDate")),
            "excerpt": _clean(it.findtext("description")),
        })
    return items, {"status": "ok", "url": url, "raw_xml": r.text}


def render(items: list[dict], max_chars: int) -> str:
    blocks = []
    for i, it in enumerate(items, 1):
        head = f"[{i}] {it['title']}"
        meta = ", ".join(x for x in (it.get("source"), it.get("published")) if x)
        if meta:
            head += f" ({meta})"
        excerpt = it.get("excerpt", "")
        if excerpt and excerpt != it["title"]:
            if len(excerpt) > max_chars:
                excerpt = excerpt[:max_chars].rsplit(" ", 1)[0] + " …"
            head += f"\n{excerpt}"
        blocks.append(head)
    return "\n\n".join(blocks)


def collect(cfg: dict, client, today: str, date_text: str = "") -> tuple[dict[str, dict], list[dict]]:
    """Return ({arm: snapshot}, [raw search call records])."""
    s = cfg["search"]
    snapshots: dict[str, dict] = {}
    raw_calls: list[dict] = []
    for arm, spec in cfg["arms"].items():
        query = spec.get("query")
        if query:
            query = query.format(date=date_text).strip()
        collected = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not query:
            snapshots[arm] = {"arm": arm, "query": None, "provider": None, "collected_at_utc": collected,
                              "items": [], "text": "", "hash": stable_hash("")}
            continue
        items, provider, notes = [], None, []
        if s["provider"] == "openrouter_exa" and client is not None:
            try:
                items, call = search_openrouter(client, cfg, query, today)
                raw_calls.append({"kind": "search", "arm": arm, "provider": "openrouter_exa", **call})
                provider = "openrouter_exa"
                if call["status"] != "ok":
                    notes.append(f"search failed: {call['error'][:200]}")
            except Exception as exc:   # never let one topic kill the wave
                notes.append(f"search error: {exc}")
        if len(items) < s["min_results"] and s.get("fallback") == "google_news_rss":
            notes.append(f"exa returned {len(items)} items; using Google News RSS")
            try:
                items, call = search_rss(query, s.get("keep_articles", s["max_results"]))
                raw_calls.append({"kind": "search", "arm": arm, "provider": "google_news_rss", **call})
                provider = "google_news_rss"
            except Exception as exc:
                notes.append(f"rss error: {exc}")
                items, provider = [], None
        text = render(items, s["max_excerpt_chars"])
        snapshots[arm] = {"arm": arm, "query": query, "provider": provider, "collected_at_utc": collected,
                          "n_items": len(items), "items": items, "text": text, "hash": stable_hash(text),
                          "notes": notes}
    return snapshots, raw_calls
