"""
utils/research.py
Turns any input (a URL, a pasted article/paragraph, or an uploaded file's
text) into a Wikipedia-style research brief:
  - title + short intro (tldr)
  - structured sections (Overview / Key Points / Context)
  - topical keywords
  - related images + related topic links (sourced live from Wikipedia,
    no API key required)
  - an optional map (if the content is about a real, real-world place)
"""

import re
import json
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "RAGBase-Research/1.0 (educational project; contact: amitanant5852@gmail.com)"
}

WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
NOMINATIM = "https://nominatim.openstreetmap.org/search"


# ---------------------------------------------------------------------------
# Input extraction
# ---------------------------------------------------------------------------
def fetch_url_text(url: str, timeout: int = 12) -> tuple[str, str]:
    """Downloads a URL and extracts readable article text. Returns (title, text)."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "iframe"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url

    candidates = soup.find_all(["article"]) or soup.find_all(["main"])
    if not candidates:
        candidates = soup.find_all(["div", "section"])

    best_text = ""
    if candidates:
        best_text = max((c.get_text(" ", strip=True) for c in candidates), key=len, default="")
    if len(best_text) < 400:
        best_text = soup.get_text(" ", strip=True)

    return title, re.sub(r"\s+", " ", best_text).strip()


# ---------------------------------------------------------------------------
# LLM-powered structured brief
# ---------------------------------------------------------------------------
def build_research_brief(groq_client, model: str, text: str, title_hint: str = "") -> dict:
    trimmed = text[:14000]

    prompt = f"""You are a meticulous research editor writing a neutral, encyclopedia-style
brief about the content below (think Wikipedia's tone: factual, structured, no fluff,
no first person, no marketing language).

Respond with STRICT JSON only, no markdown fences, in exactly this shape:
{{
  "title": "short descriptive title (refine the hint, don't just copy it)",
  "tldr": "a crisp 2-3 sentence lead paragraph summarizing the whole topic",
  "sections": [
    {{"heading": "Overview", "content": "2-4 sentence paragraph"}},
    {{"heading": "Key Points", "bullets": ["point 1", "point 2", "..."]}},
    {{"heading": "Additional Context", "content": "2-3 sentence paragraph, or empty string if nothing more to add"}}
  ],
  "keywords": ["topic1", "topic2", "topic3", "topic4"],
  "location": "a real-world place name central to this content, or null if none applies"
}}

Rules:
- "Key Points" bullets: 5-8 items, each a single self-contained factual sentence, ordered by importance.
- Keep sections factual and specific to the content given; never invent facts not supported by it.
- "keywords" must be short topical nouns useful for looking up related articles (4-6 items).
- "location" should only be set if there's a genuine, specific real-world place (city/country/landmark)
  that the content is meaningfully about — not a generic mention. Otherwise null.

TITLE HINT: {title_hint or "none"}

CONTENT:
{trimmed}
"""
    completion = groq_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1200,
    )
    raw = completion.choices[0].message.content.strip()
    raw = re.sub(r"^```(json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    data = json.loads(raw)

    data.setdefault("title", title_hint or "Research Brief")
    data.setdefault("tldr", "")
    data.setdefault("sections", [])
    data.setdefault("keywords", [])
    data.setdefault("location", None)
    return data


# ---------------------------------------------------------------------------
# Wikipedia enrichment — free, no API key. Gives real images + real related links.
# ---------------------------------------------------------------------------
def _wiki_get(params: dict) -> dict:
    params = {**params, "format": "json", "origin": "*"}
    r = requests.get(WIKI_SEARCH, params=params, headers=HEADERS, timeout=8)
    r.raise_for_status()
    return r.json()


def wiki_enrich(keywords: list, title: str) -> dict:
    """Looks up the best-matching Wikipedia pages for the topic and returns
    representative images + a list of related-topic links."""
    images, related = [], []
    seen_titles = set()

    search_terms = [title] + keywords[:4]
    for term in search_terms:
        if not term or len(related) >= 6:
            continue
        try:
            search_data = _wiki_get({"action": "query", "list": "search", "srsearch": term, "srlimit": 2})
            hits = search_data.get("query", {}).get("search", [])
        except Exception:
            hits = []

        for hit in hits:
            page_title = hit.get("title")
            if not page_title or page_title in seen_titles:
                continue
            seen_titles.add(page_title)

            try:
                summary = requests.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(page_title)}",
                    headers=HEADERS, timeout=8,
                ).json()
            except Exception:
                summary = {}

            page_url = summary.get("content_urls", {}).get("desktop", {}).get("page")
            thumb = summary.get("thumbnail", {}).get("source")
            extract = summary.get("extract", "")

            if page_url:
                related.append({"title": page_title, "url": page_url, "snippet": extract[:140]})
            if thumb and len(images) < 6:
                images.append({"src": thumb, "caption": page_title})

            if len(related) >= 6:
                break

    return {"images": images, "related": related}


# ---------------------------------------------------------------------------
# Map — free geocoding via OpenStreetMap Nominatim, no API key.
# ---------------------------------------------------------------------------
def geocode_location(place_name: str):
    try:
        r = requests.get(
            NOMINATIM,
            params={"q": place_name, "format": "json", "limit": 1},
            headers=HEADERS, timeout=8,
        )
        r.raise_for_status()
        results = r.json()
        if not results:
            return None
        lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
        return {
            "name": place_name,
            "lat": lat,
            "lon": lon,
            "osm_embed": (
                f"https://www.openstreetmap.org/export/embed.html?"
                f"bbox={lon-0.05}%2C{lat-0.05}%2C{lon+0.05}%2C{lat+0.05}&marker={lat}%2C{lon}"
            ),
            "gmaps_url": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
        }
    except Exception:
        return None
