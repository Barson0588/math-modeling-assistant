"""Semantic Scholar API client — free, no key required.
Rate limit: ~100 requests per 5 minutes without API key.
Docs: https://api.semanticscholar.org/api-docs/
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import time

BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,authors,year,citationCount,externalIds,url,abstract"


def _fetch_json(url, retries=1, timeout=8):
    """Fetch JSON from URL with retry for 429 rate limits."""
    for attempt in range(retries + 1):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "MathModelingAssistant/1.0 (mailto:wuqqi@example.com)")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(2 * (attempt + 1))
            else:
                return {}
        except Exception:
            if attempt < retries:
                time.sleep(1)
            else:
                return {}
    return {}


def search_papers(query, limit=10):
    """Search Semantic Scholar for papers matching a query."""
    params = urllib.parse.urlencode({
        "query": query,
        "limit": min(limit, 20),
        "fields": FIELDS,
    })
    url = f"{BASE_URL}/paper/search?{params}"

    data = _fetch_json(url)

    papers = []
    for item in data.get("data", []):
        authors = item.get("authors", [])
        papers.append({
            "title": item.get("title", ""),
            "authors": [a.get("name", "") for a in authors],
            "year": item.get("year"),
            "citationCount": item.get("citationCount", 0),
            "doi": (item.get("externalIds") or {}).get("DOI", ""),
            "url": item.get("url", ""),
            "abstract": (item.get("abstract") or "")[:300],
        })

    return papers


def search_by_keywords(keywords, limit=10):
    """Search papers by multiple keywords extracted from problem description."""
    all_papers = []
    seen = set()

    # Only search the first 2 keywords to stay responsive
    for kw in keywords[:2]:
        papers = search_papers(kw, limit=5)
        for p in papers:
            if p["title"] not in seen:
                seen.add(p["title"])
                all_papers.append(p)

    # Sort by citation count descending
    all_papers.sort(key=lambda p: p.get("citationCount", 0) or 0, reverse=True)
    return all_papers[:limit]


def format_reference_apa(paper):
    """Format a single paper as APA 7th edition reference."""
    authors = paper.get("authors", [])
    year = paper.get("year", "n.d.")
    title = paper.get("title", "Untitled")
    doi = paper.get("doi", "")
    url = paper.get("url", "")

    # Format authors: Last, F. M., Last, F. M., & Last, F. M.
    if authors:
        author_str = ", ".join(authors[:5])
        if len(authors) > 5:
            author_str += ", et al."
        author_str += "."
    else:
        author_str = "[Unknown]."

    ref = f"{author_str} ({year}). {title}."
    if doi:
        ref += f" https://doi.org/{doi}"
    elif url:
        ref += f" {url}"

    return ref


def format_references_apa(papers):
    """Format a list of papers as APA 7th edition references."""
    return [format_reference_apa(p) for p in papers]
