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


# ── Crossref API Search ───────────────────────────────────────────────
# Free, no API key required. Rate limit: ~50 req/s (polite pool).
# Docs: https://api.crossref.org/swagger-ui/

def search_crossref(query, limit=5, filter_type=None):
    """Search Crossref for academic papers by title, author, or keywords.

    Args:
        query: Free-text search query.
        limit: Max results (capped at 20).
        filter_type: Optional Crossref type filter (e.g. 'journal-article').

    Returns:
        List of paper dicts with keys: title, authors, year, doi, url,
        publisher, container_title (journal name), citation_count.
    """
    import urllib.parse
    params = {
        "query": query,
        "rows": min(limit, 20),
    }
    if filter_type:
        params["filter"] = f"type:{filter_type}"

    url = f"https://api.crossref.org/works?{urllib.parse.urlencode(params)}"

    data = _fetch_json(url, retries=2, timeout=12)
    items = data.get("message", {}).get("items", [])

    papers = []
    for item in items:
        author_list = item.get("author", [])
        authors = []
        for a in author_list:
            given = a.get("given", "")
            family = a.get("family", "")
            if given or family:
                authors.append(f"{family}, {given}".strip(", "))
            elif "name" in a:
                authors.append(a["name"])

        published = item.get("published-print", {}) or item.get("created", {})
        date_parts = published.get("date-parts", [[None]])[0]
        year = date_parts[0] if date_parts else None

        title_list = item.get("title", ["Untitled"])
        title = title_list[0] if title_list else "Untitled"

        container = item.get("container-title", [""])
        journal = container[0] if container else ""

        papers.append({
            "title": title,
            "authors": authors,
            "year": year,
            "doi": item.get("DOI", ""),
            "url": item.get("URL", f"https://doi.org/{item.get('DOI', '')}" if item.get("DOI") else ""),
            "publisher": item.get("publisher", ""),
            "container_title": journal,
            "citation_count": item.get("is-referenced-by-count", 0),
        })

    return papers


def search_paper_multi(query, limit=10):
    """Search across multiple sources (Semantic Scholar + Crossref)
    and merge/deduplicate results.

    Returns papers sorted by citation count (descending).
    """
    # Search both sources in parallel-like fashion
    # (Sequential here for simplicity; could be threaded)
    ss_results = search_papers(query, limit=limit)
    cx_results = search_crossref(query, limit=limit)

    # Merge and deduplicate by title similarity
    seen_titles = set()
    merged = []

    def _simplify(t):
        """Normalize title for dedup comparison."""
        return "".join(c.lower() for c in t if c.isalnum())

    for paper in ss_results:
        key = _simplify(paper["title"])
        if key not in seen_titles:
            seen_titles.add(key)
            paper["_source"] = "semantic_scholar"
            merged.append(paper)

    for paper in cx_results:
        key = _simplify(paper["title"])
        if key not in seen_titles:
            seen_titles.add(key)
            paper["_source"] = "crossref"
            merged.append(paper)

    merged.sort(key=lambda p: p.get("citationCount", 0) or 0, reverse=True)
    return merged[:limit]


def format_crossref_apa(paper):
    """Format a Crossref paper dict as APA 7th reference."""
    return format_reference_apa(paper)
