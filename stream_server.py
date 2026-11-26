import asyncio
from collections import Counter
import html as html_lib
from io import BytesIO
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

try:
    from aiohttp import web
except ImportError:
    class _StdlibWebResponse:
        def __init__(self, text="", body=None, status=200, headers=None, content_type="text/plain"):
            self.status = status
            self.headers = dict(headers or {})
            if content_type and "Content-Type" not in self.headers:
                self.headers["Content-Type"] = content_type
            if body is not None:
                self.body = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
            else:
                self.body = str(text or "").encode("utf-8")

    class _StdlibRouter:
        def __init__(self):
            self.routes = []

        def add_get(self, path, handler):
            self.routes.append(("GET", path, handler))

        def add_route(self, method, path, handler):
            self.routes.append((str(method or "*").upper(), path, handler))

        def resolve(self, method, path):
            req_method = str(method or "GET").upper()
            clean_path = (path or "/").split("?", 1)[0]
            for route_method, route_path, handler in self.routes:
                if route_path == clean_path and (route_method == "*" or route_method == req_method):
                    return handler
            return None

    class _StdlibApplication:
        def __init__(self):
            self.router = _StdlibRouter()

    class _StdlibAppRunner:
        def __init__(self, app):
            self.app = app
            self._sites = []

        async def setup(self):
            return None

        async def cleanup(self):
            for site in list(self._sites):
                await site.stop()
            self._sites.clear()

    class _StdlibTCPSite:
        def __init__(self, runner, host="127.0.0.1", port=8765):
            self.runner = runner
            self.host = host
            self.port = port
            self._server = None
            self._thread = None
            runner._sites.append(self)

        async def start(self):
            import http.server
            import threading

            app = self.runner.app

            class _Handler(http.server.BaseHTTPRequestHandler):
                def _dispatch(handler_self):
                    handler_fn = app.router.resolve(handler_self.command, handler_self.path)
                    if handler_fn is None:
                        handler_self.send_response(404)
                        handler_self.end_headers()
                        handler_self.wfile.write(b"Not Found")
                        return
                    resp = asyncio.run(handler_fn(handler_self))
                    handler_self.send_response(getattr(resp, "status", 200))
                    for k, v in (getattr(resp, "headers", None) or {}).items():
                        handler_self.send_header(k, v)
                    body_bytes = getattr(resp, "body", b"") or b""
                    handler_self.send_header("Content-Length", str(len(body_bytes)))
                    handler_self.end_headers()
                    handler_self.wfile.write(body_bytes)

                def do_GET(handler_self):
                    handler_self._dispatch()

                def do_POST(handler_self):
                    handler_self._dispatch()

                def log_message(handler_self, _format, *_args):
                    return

            self._server = http.server.ThreadingHTTPServer((self.host, self.port), _Handler)
            self.port = self._server.server_port
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()

        async def stop(self):
            if self._server is not None:
                await asyncio.to_thread(self._server.shutdown)
                self._server.server_close()
                self._server = None
            if self._thread is not None:
                self._thread.join(timeout=2)
                self._thread = None

    class _StdlibWebSocketResponse:
        def can_prepare(self, _request):
            return type("_CanPrepare", (), {"ok": False})()

    class _StdlibWebModule:
        Response = _StdlibWebResponse
        Application = _StdlibApplication
        AppRunner = _StdlibAppRunner
        TCPSite = _StdlibTCPSite
        WebSocketResponse = _StdlibWebSocketResponse

        @staticmethod
        def json_response(data, status=200, headers=None):
            return _StdlibWebResponse(
                body=json.dumps(data).encode("utf-8"),
                status=status,
                headers=headers,
                content_type="application/json; charset=utf-8",
            )

    web = _StdlibWebModule()

try:
    from curl_cffi import requests as cureq
except ImportError:
    cureq = None
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
from prescriptive_orientation import evaluate_orientation, evaluate_state_classification
from server import fetch_social_hashtag_trends

CONNECTED_CLIENTS = set()
LATEST_TRENDS = None
TREND_REFRESH_SECONDS = 60
LAYER2_MACRO_TTL_SECONDS = 6 * 60 * 60
LAYER2_MACRO_CACHE = {"expires_at": 0.0, "data": None}
HANSARD_TTL_SECONDS = 6 * 60 * 60
HANSARD_ERROR_TTL_SECONDS = 15 * 60
HANSARD_CACHE = {"expires_at": 0.0, "data": None}
TELEMETRY_CACHE_PATH = os.environ.get(
    "TELEMETRY_CACHE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "telemetry_cache.json"),
)
HANSARD_PORTAL_URL = os.environ.get("HANSARD_PORTAL_URL", "https://e-portal.parlzim.gov.zw/")
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "").strip()
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "").strip()
PARLZIM_STATIC_PORTALS = (
    ("Bill Digests", "https://www.parlzim.gov.zw/bill-digest/"),
    ("Enacted Acts", "https://www.parlzim.gov.zw/acts/"),
    ("Policy Briefs", "https://www.parlzim.gov.zw/policy-briefs/"),
    ("Fact Sheets", "https://www.parlzim.gov.zw/fact-sheets/"),
)
PARLZIM_FALLBACK_MIRRORS = {
    "Bill Digests": ("ZimLII Uncommenced & OpenParly Bills", "https://zimlii.org/legislation/uncommenced"),
    "Enacted Acts": ("ZimLII Recent Legislation", "https://zimlii.org/legislation/recent"),
    "Policy Briefs": (
        "OpenParly Policy & Committee PDFs",
        "https://openparly.com/wp-json/wp/v2/posts?categories=13,1719,3777&per_page=8&_fields=id,date,title,link,content,excerpt,author&_embed=author",
    ),
    "Fact Sheets": ("ZimLII Subsidiary Legislation", "https://zimlii.org/legislation/subsidiary"),
    "Hansards": (
        "OpenParly ParlZim Hansard Archive",
        "https://openparly.com/wp-json/wp/v2/media?mime_type=application/pdf&search=hansard&per_page=8&_fields=id,date,title,source_url",
    ),
}
OPENPARLY_SUPPLEMENT_QUERIES = {
    "Bill Digests": (
        "https://openparly.com/wp-json/wp/v2/media?mime_type=application/pdf&search=bill&per_page=8&_fields=id,date,title,source_url",
    ),
    "Policy Briefs": (
        "https://openparly.com/wp-json/wp/v2/posts?categories=13,1719,3777&per_page=8&_fields=id,date,title,link,content,excerpt,author&_embed=author",
        "https://openparly.com/wp-json/wp/v2/media?mime_type=application/pdf&search=policy&per_page=6&_fields=id,date,title,source_url",
        "https://openparly.com/wp-json/wp/v2/media?mime_type=application/pdf&search=analysis&per_page=4&_fields=id,date,title,source_url",
    ),
    "Hansards": (
        "https://openparly.com/wp-json/wp/v2/media?mime_type=application/pdf&search=hansard&per_page=8&_fields=id,date,title,source_url",
        "https://openparly.com/wp-json/wp/v2/media?mime_type=application/pdf&search=NATIONAL-ASSEMBLY&per_page=6&_fields=id,date,title,source_url",
        "https://openparly.com/wp-json/wp/v2/media?mime_type=application/pdf&search=Vol.&per_page=6&_fields=id,date,title,source_url",
    ),
}
HANSARD_RISK_CORPUS = (
    "corruption tender embezzlement illicit financial flows asset recovery graft scandal looting",
    "inflation parallel market currency depreciation exchange rate foreign currency shortage devaluation",
    "budget deficit unauthorized expenditure audit discrepancy public funds misappropriation debt",
    "parliamentary walkout suspension clash censure motion of no confidence boycott standoff",
)
ENGLISH_STOPWORDS = frozenset({
    "the", "and", "for", "that", "with", "this", "from", "are", "was", "were",
    "will", "would", "have", "has", "had", "not", "but", "all", "any", "can",
    "could", "should", "shall", "may", "might", "must", "into", "about", "there",
    "their", "they", "them", "these", "those", "which", "who", "whom", "what",
    "when", "where", "why", "how", "been", "being", "its", "our", "out", "over",
    "under", "more", "most", "some", "such", "than", "then", "very", "also",
    "only", "other", "between", "through", "during", "before", "after", "above",
    "below", "each", "few", "both", "same", "own", "while", "because", "until",
})
logger = logging.getLogger("kuvhura.orientation")
TIMELINE_WINDOW_DAYS = 30
TELEMETRY_TIMELINE = [
    {"date": "2026-10-16", "phi": 54.80, "markov_crisis_prob": 12.4, "state": "Stable Consolidation"},
    {"date": "2026-10-17", "phi": 54.20, "markov_crisis_prob": 12.8, "state": "Stable Consolidation"},
    {"date": "2026-10-18", "phi": 53.60, "markov_crisis_prob": 13.1, "state": "Stable Consolidation"},
    {"date": "2026-10-19", "phi": 53.10, "markov_crisis_prob": 13.5, "state": "Stable Consolidation"},
    {"date": "2026-10-20", "phi": 52.40, "markov_crisis_prob": 14.0, "state": "Stable Consolidation"},
    {"date": "2026-10-21", "phi": 51.90, "markov_crisis_prob": 14.3, "state": "Stable Consolidation"},
    {"date": "2026-10-22", "phi": 51.20, "markov_crisis_prob": 14.8, "state": "Latent Friction"},
    {"date": "2026-10-23", "phi": 50.60, "markov_crisis_prob": 15.2, "state": "Latent Friction"},
    {"date": "2026-10-24", "phi": 49.90, "markov_crisis_prob": 15.6, "state": "Latent Friction"},
    {"date": "2026-10-25", "phi": 49.30, "markov_crisis_prob": 16.0, "state": "Latent Friction"},
    {"date": "2026-10-26", "phi": 48.60, "markov_crisis_prob": 16.5, "state": "Latent Friction"},
    {"date": "2026-10-27", "phi": 48.00, "markov_crisis_prob": 16.9, "state": "Latent Friction"},
    {"date": "2026-10-28", "phi": 47.20, "markov_crisis_prob": 17.4, "state": "Latent Friction"},
    {"date": "2026-10-29", "phi": 46.50, "markov_crisis_prob": 17.9, "state": "Latent Friction"},
    {"date": "2026-10-30", "phi": 45.80, "markov_crisis_prob": 18.3, "state": "Latent Friction"},
    {"date": "2026-10-31", "phi": 45.10, "markov_crisis_prob": 18.7, "state": "Latent Friction"},
    {"date": "2026-11-01", "phi": 44.40, "markov_crisis_prob": 19.2, "state": "Latent Friction"},
    {"date": "2026-11-02", "phi": 43.70, "markov_crisis_prob": 19.6, "state": "Latent Friction"},
    {"date": "2026-11-03", "phi": 43.00, "markov_crisis_prob": 20.0, "state": "Latent Friction"},
    {"date": "2026-11-04", "phi": 42.30, "markov_crisis_prob": 20.4, "state": "Latent Friction"},
    {"date": "2026-11-05", "phi": 41.60, "markov_crisis_prob": 20.8, "state": "Latent Friction"},
    {"date": "2026-11-06", "phi": 40.90, "markov_crisis_prob": 21.2, "state": "Latent Friction"},
    {"date": "2026-11-07", "phi": 40.20, "markov_crisis_prob": 21.6, "state": "Latent Friction"},
    {"date": "2026-11-08", "phi": 39.50, "markov_crisis_prob": 22.0, "state": "Latent Friction"},
    {"date": "2026-11-09", "phi": 38.10, "markov_crisis_prob": 24.5, "state": "Latent Friction"},
    {"date": "2026-11-10", "phi": 36.80, "markov_crisis_prob": 27.0, "state": "Latent Friction"},
    {"date": "2026-11-11", "phi": 34.20, "markov_crisis_prob": 31.0, "state": "Accelerated Degradation"},
    {"date": "2026-11-12", "phi": 30.50, "markov_crisis_prob": 38.0, "state": "Accelerated Degradation"},
    {"date": "2026-11-13", "phi": 27.90, "markov_crisis_prob": 42.5, "state": "Acute Crisis"},
    {"date": "2026-11-14", "phi": 24.15, "markov_crisis_prob": 46.8, "state": "Acute Systemic Crisis"},
]
_SEED_MACRO_PROXIES = (
    32.5, 33.0, 33.4, 34.0, 34.5, 35.0, 35.6, 36.2, 36.8, 37.2,
    37.8, 38.4, 39.0, 39.5, 40.0, 40.6, 41.2, 41.8, 42.3, 42.9,
    43.4, 44.0, 44.5, 45.0, 48.0, 50.0, 55.0, 60.0, 62.0, 65.0,
)
for _seed, _macro_proxy in zip(TELEMETRY_TIMELINE, _SEED_MACRO_PROXIES):
    _seed["macro_volatility_proxy"] = _macro_proxy
    _seed["fsi"] = round(
        0.40 * (100.0 - _seed["phi"])
        + 0.35 * _seed["markov_crisis_prob"]
        + 0.25 * _macro_proxy,
        2,
    )
    _seed["warning_level"] = (
        "Stable Consolidation" if _seed["fsi"] <= 25
        else "Latent Friction" if _seed["fsi"] <= 50
        else "Accelerated Degradation" if _seed["fsi"] <= 75
        else "Acute Systemic Crisis"
    )
TIMELINE_BASELINE_DATE = None
TIMELINE_BASELINE = None
LATEST_DUAL_ENGINE_INPUTS = None
LATEST_FSI_INPUTS = None
LATEST_HANSARD_STATUS = None
MARKOV_TRANSITION_MATRIX = (
    (0.75, 0.20, 0.05),
    (0.15, 0.60, 0.25),
    (0.05, 0.30, 0.65),
)


def compute_bayesian_posterior(prior_phi, social_volume, engagement_score):
    """Update Φ with configured signal likelihoods; telemetry inputs are proxies."""
    for name, value in (
        ("prior_phi", prior_phi),
        ("social_volume", social_volume),
        ("engagement_score", engagement_score),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number.")
    if not 0 <= prior_phi <= 100:
        raise ValueError("prior_phi must be between 0 and 100.")
    if social_volume < 0 or engagement_score < 0:
        raise ValueError("social_volume and engagement_score must be non-negative.")

    prior_crisis_prob = 1.0 - prior_phi / 100.0
    is_high_stress = social_volume > 80 or engagement_score > 1200
    p_evidence_given_crisis = 0.82 if is_high_stress else 0.18
    p_evidence_given_stable = 0.25 if is_high_stress else 0.75
    p_evidence = (
        p_evidence_given_crisis * prior_crisis_prob
        + p_evidence_given_stable * (1 - prior_crisis_prob)
    )
    posterior_prob = p_evidence_given_crisis * prior_crisis_prob / p_evidence
    updated_phi = round((1.0 - posterior_prob) * 100, 2)
    return max(5.0, min(95.0, updated_phi))


def compute_markov_path_projection(last_crisis_prob):
    """Project one transition using the supplied three-state Markov matrix."""
    if (
        isinstance(last_crisis_prob, bool)
        or not isinstance(last_crisis_prob, (int, float))
        or not math.isfinite(last_crisis_prob)
        or not 0 <= last_crisis_prob <= 100
    ):
        raise ValueError("last_crisis_prob must be a finite percentage from 0 to 100.")

    current_state_vector = [
        max(0.0, 1.0 - last_crisis_prob / 50.0),
        0.5,
        min(1.0, last_crisis_prob / 100.0),
    ]
    total = sum(current_state_vector)
    current_state_vector = [state / total for state in current_state_vector]
    next_vector = [
        sum(
            current_state_vector[index] * MARKOV_TRANSITION_MATRIX[index][state]
            for index in range(3)
        )
        for state in range(3)
    ]
    return round(next_vector[2] * 100, 2)


def _tokenize_hansard(text):
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text or "")
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html_lib.unescape(cleaned).lower()
    return [
        token for token in re.findall(r"[a-z]{2,}", cleaned)
        if token not in ENGLISH_STOPWORDS
    ]


def score_hansard_text(live_text):
    """Compute 40-100 TF-IDF cosine similarity friction index from parliamentary text."""
    docs_tokens = [_tokenize_hansard(doc) for doc in HANSARD_RISK_CORPUS]
    live_tokens = _tokenize_hansard(live_text)
    if not live_tokens:
        return None
    all_docs = docs_tokens + [live_tokens]
    num_docs = len(all_docs)

    doc_freq = Counter()
    for tokens in all_docs:
        for term in set(tokens):
            doc_freq[term] += 1

    def _tfidf_vector(tokens):
        counts = Counter(tokens)
        vec = {}
        norm_sq = 0.0
        for term, tf in counts.items():
            idf = math.log((1.0 + num_docs) / (1.0 + doc_freq[term])) + 1.0
            weight = tf * idf
            vec[term] = weight
            norm_sq += weight * weight
        norm = math.sqrt(norm_sq)
        if norm > 0:
            for term in vec:
                vec[term] /= norm
        return vec

    ref_vectors = [_tfidf_vector(tokens) for tokens in docs_tokens]
    live_vector = _tfidf_vector(live_tokens)

    similarities = []
    for ref_vec in ref_vectors:
        sim = sum(live_vector.get(term, 0.0) * weight for term, weight in ref_vec.items())
        similarities.append(sim)

    mean_similarity = sum(similarities) / len(similarities)
    semantic_friction = min(100.0, max(40.0, (mean_similarity * 250.0) + 42.0))
    return round(semantic_friction, 2)


def _strip_html(raw_html):
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html or "")
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    return " ".join(html_lib.unescape(cleaned).split())


MONTH_NAME_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _clean_issue_title(raw_title):
    title = html_lib.unescape(str(raw_title or ""))
    title = re.sub(r"\s+(?:First|Second|Third|Fourth|Fifth)\s+Ses\s*sion\s*:?.*$", "", title, flags=re.IGNORECASE)
    title = " ".join(title.split())
    if not title:
        return ""
    if title.count("_") >= 2 or (" " not in title and title.count("-") >= 3):
        title = re.sub(r"[_\-]+", " ", title)
        title = " ".join(title.split())
        if title.isupper():
            title = title.title()
    return title


NON_ISSUE_TITLES = frozenset({
    "parliament building mt hampden",
    "parliament building mt hampden.",
    "office of the hon speaker",
    "office of the speaker",
    "office of the hon deputy speaker",
    "office of the deputy speaker",
    "office of the hon president of senate",
    "office of the president of senate",
    "bill digests",
    "enacted acts",
    "policy briefs",
    "fact sheets",
    "hansards",
    "parliament of zimbabwe",
})

NON_ISSUE_URL_PARTS = (
    "maps.app.goo.gl",
    "goo.gl/maps",
    "google.com/maps",
    "facebook.com",
    "twitter.com",
    "x.com/",
    "youtube.com",
    "instagram.com",
    "/office-of-the-speaker",
    "/president-of-senate",
    "/deputy-speaker",
    "/clerk-of-parliament",
    "/contact",
    "/about",
    "/privacy",
    "/sitemap",
    "/wp-admin",
    "/login",
)


def _is_non_issue_link(title, url="", check_category_root=False):
    clean_title = " ".join(str(title or "").split()).strip().lower()
    clean_url = str(url or "").strip().lower()
    if clean_title.rstrip(".") in NON_ISSUE_TITLES:
        return True
    if any(part in clean_url for part in NON_ISSUE_URL_PARTS):
        return True
    if check_category_root and re.fullmatch(
        r"https?://[^/]+/(bill-digest|acts|policy-briefs|fact-sheets|hansards)/?", clean_url
    ):
        return True
    return False


def _strip_navigation_chrome(raw_html):
    raw = raw_html or ""
    if BeautifulSoup is not None and raw:
        try:
            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            main_el = soup.find("main") or soup.find("article")
            if main_el is not None and len(main_el.get_text(" ", strip=True)) >= 120:
                return str(main_el)
            body_html = str(soup)
            if len(_strip_html(body_html)) >= 120:
                return body_html
        except Exception:
            pass
    stripped = re.sub(r"(?is)<(nav|header|footer|aside)\b[^>]*>.*?</\1>", " ", raw)
    return stripped if len(_strip_html(stripped)) >= 120 else raw


def _parse_iso_date_str(raw_date):
    value = str(raw_date or "").strip()
    if not value:
        return None
    normalized = re.sub(r"\b(\d{1,2})\s+(st|nd|rd|th)\b", r"\1\2", value, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*,\s*", ", ", normalized)
    normalized = re.sub(r"\bJ\s*U\s*L\s*Y\b", "July", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bJ\s*U\s*N\s*E\b", "June", normalized, flags=re.IGNORECASE)
    iso_match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", normalized)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    try:
        dt = parsedate_to_datetime(normalized)
        if dt is not None:
            return dt.date().isoformat()
    except Exception:
        pass
    dmy = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+(January|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?),?\s+(20\d{2})\b",
        normalized,
        re.IGNORECASE,
    )
    if dmy:
        day, month_name, year = int(dmy.group(1)), dmy.group(2).lower(), int(dmy.group(3))
        month = MONTH_NAME_MAP.get(month_name)
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    mdy = re.search(
        r"\b(January|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
        normalized,
        re.IGNORECASE,
    )
    if mdy:
        month_name, day, year = mdy.group(1).lower(), int(mdy.group(2)), int(mdy.group(3))
        month = MONTH_NAME_MAP.get(month_name)
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    my = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
        normalized,
        re.IGNORECASE,
    )
    if my:
        month = MONTH_NAME_MAP.get(my.group(1).lower())
        year = int(my.group(2))
        if month:
            return f"{year:04d}-{month:02d}"
    return None


def _extract_submission_date(*texts, pub_date="", url=""):
    """Extract verified submission/publication/gazette date as YYYY-MM-DD or YYYY-MM when present."""
    for candidate in (pub_date,):
        parsed = _parse_iso_date_str(candidate)
        if parsed:
            return parsed
    akn_match = re.search(r"@(\d{4}-\d{2}-\d{2})(?:[/?#]|$)", str(url or ""))
    if akn_match:
        return akn_match.group(1)
    for text in texts:
        parsed = _parse_iso_date_str(text)
        if parsed:
            return parsed
    wp_upload = re.search(r"/wp-content/uploads/(20\d{2})/(\d{2})/", str(url or ""))
    if wp_upload:
        return f"{wp_upload.group(1)}-{wp_upload.group(2)}"
    return None


GENERIC_PDF_AUTHORS_RE = re.compile(
    r"^(?:microsoft|adobe|libreoffice|writer|pypdf|unknown|admin|user|usr|poz|nn|tatenda|mzilikazi|hansard|parliament(?:\s+of\s+zimbabwe)?|windows\s*user|zimuser\d*)$",
    re.IGNORECASE,
)


def _extract_responsible_person(*texts, author="", source_name="", title=""):
    """Extract named sponsor, minister, committee, MP, or source desk strictly from real metadata/text."""
    raw_author = " ".join(str(author or "").split())
    if raw_author and "@" not in raw_author and len(raw_author) >= 3 and not GENERIC_PDF_AUTHORS_RE.match(raw_author):
        return raw_author[:120]

    combined = " ".join(t for t in (title, *texts) if t)
    named_author_role = re.search(
        r"\b((?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)\s+[A-Z]\.?\s*[A-Za-z.'\- ]{2,45},\s+(?:Principal|Senior|Chief|Acting|Deputy)?\s*[A-Za-z ]{3,40}?(?:Officer|Director|Researcher|Clerk|Secretary|Analyst|Counsel))\b",
        combined,
    )
    if named_author_role:
        return " ".join(named_author_role.group(1).split())

    by_org_match = re.search(
        r"\bBY:\s*([A-Z][A-Za-z0-9 ,.&'\-]{4,65}?)(?=\s+(?:BACKGROUND|INTRODUCTION|EXECUTIVE|SUMMARY|1\.|ABSTRACT)\b|\n|$)",
        combined,
    )
    if by_org_match:
        candidate_org = " ".join(by_org_match.group(1).split()).rstrip(".,;:- ")
        if candidate_org:
            return candidate_org.title() if candidate_org.isupper() else candidate_org

    minister_match = re.search(
        r"\b((?:The\s+)?Ministr?y?\s+of\s+[A-Z][A-Za-z,&/\- ]{3,85}?|Minister of [A-Z][A-Za-z,&/\- ]{3,75}?)(?=\)|\]|;|\(|Notice\b|Regulations\b|Bill\b|Act\b|,?\s+20\d{2}|$)",
        combined,
    )
    if minister_match:
        cleaned_min = re.sub(r"^The\s+", "", " ".join(minister_match.group(1).split())).rstrip(".,;:- ")
        return cleaned_min

    submit_match = re.search(
        r"\b(?:tabled by|submitted by|presented by|moved by|sponsored by|prepared by|authored by)\s+([A-Z][A-Za-z.'\- ]{2,65}?)(?=[;,\n]|(?:\.(?!\s*[A-Z]))|$)",
        combined,
        re.IGNORECASE,
    )
    if submit_match:
        return " ".join(submit_match.group(1).split()).rstrip(".,;:- ")

    hon_match = re.search(
        r"\b((?:Hon\.?|Honourable|Sen\.?|Senator)\s+(?:Sen\.?\s+|Prof\.?\s+|Dr\.?\s+)?[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,3})\b",
        combined,
    )
    if hon_match:
        cand_hon = " ".join(hon_match.group(1).split())
        if not re.match(r"^(?:Hon\.?|Honourable)\s+(?:Members?|Deputy|Minister)\b", cand_hon, re.IGNORECASE):
            return cand_hon

    committee_match = re.search(
        r"\b("
        r"(?:Parliamentary\s+Legal\s+Committee|Public\s+Accounts\s+Committee)"
        r"|(?:(?:Parliamentary|Joint|Standing|Portfolio|Thematic|Public\s+Accounts)\s+)*Committee\s+on\s+"
        r"(?:the\s+)?[A-Z][A-Za-z,&/\-]+(?:\s+(?:(?:and|of|for|the|&)\s+)?[A-Z][A-Za-z,&/\-]+){0,6}"
        r"|(?:Parliamentary|Joint|Standing|Portfolio|Thematic|Public\s+Accounts)\s+Committee(?:\s+[Oo]n\s+[A-Z,&/\-]+(?:\s+(?:(?:AND|OF|FOR|THE|&)\s+)?[A-Z,&/\-]+){0,6})?"
        r")",
        combined,
    )
    if committee_match:
        candidate_committee = (
            re.sub(r"\bCOMMITTTEE\b", "Committee", committee_match.group(1), flags=re.IGNORECASE)
        )
        candidate_committee = re.sub(
            r"\s+(?:on\s+the\s+(?:preparedness|state)|Bill|Act|Report|Motion|regarding|shall|may|is|was|are|to|under|conducted)\b.*$",
            "",
            candidate_committee,
            flags=re.IGNORECASE,
        )
        candidate_committee = " ".join(candidate_committee.split()).rstrip(".,;:- ")
        if candidate_committee.lower() != "committee" and len(candidate_committee) >= 12 and not re.search(r"Standing\s+Rules", candidate_committee, re.IGNORECASE):
            if candidate_committee.isupper():
                candidate_committee = re.sub(
                    r"\b(On|Of|And|For|The|In)\b",
                    lambda m: m.group(1).lower(),
                    candidate_committee.title(),
                )
                candidate_committee = candidate_committee[:1].upper() + candidate_committee[1:]
            return candidate_committee

    chair_match = re.search(
        r"\b((?:The\s+)?(?:Acting\s+President\s+of\s+Senate|Speaker\s+of\s+the\s+National\s+Assembly|Hon\.?\s+Deputy\s+Speaker|The\s+Speaker\s+in\s+the\s+Chair))\b",
        combined,
        re.IGNORECASE,
    )
    if chair_match:
        cand_chair = " ".join(chair_match.group(1).split())
        if "speaker in the chair" in cand_chair.lower():
            return "Speaker of the National Assembly"
        return re.sub(r"^The\s+", "", cand_chair, flags=re.IGNORECASE).title() if cand_chair.isupper() else re.sub(r"^The\s+", "", cand_chair, flags=re.IGNORECASE)

    institution_match = re.search(
        r"\b(Zimbabwe Lawyers for Human Rights|Office of the Auditor[\s\-]General|Auditor[\s\-]General|Reserve Bank of Zimbabwe|Constitutional Court|ZIMRA|Parliament of Zimbabwe)\b",
        combined,
        re.IGNORECASE,
    )
    if institution_match:
        inst = " ".join(institution_match.group(1).split())
        return "Parliament of Zimbabwe" if inst.upper() == "PARLIAMENT OF ZIMBABWE" else inst

    clean_source = " ".join(str(source_name or "").split())
    if not clean_source and " - " in str(title or ""):
        possible_pub = str(title).rsplit(" - ", 1)[-1].strip()
        if 3 <= len(possible_pub) <= 60 and not re.search(r"\d{4}", possible_pub):
            clean_source = possible_pub
    if clean_source:
        return f"Submitted via {clean_source}"

    return "Not stated in portal index"


def _extract_akn_citation(url):
    raw_url = str(url or "")
    si_match = re.search(r"/akn/zw/act/si/(\d{4})/(\d+)", raw_url, re.IGNORECASE)
    if si_match:
        return f"Statutory Instrument {si_match.group(2)} of {si_match.group(1)}"
    act_match = re.search(r"/akn/zw/act/(\d{4})/(\d+)", raw_url, re.IGNORECASE)
    if act_match:
        return f"Act {act_match.group(2)} of {act_match.group(1)}"
    return ""


def _infer_policy_themes(text):
    lower = str(text or "").lower()
    themes = []
    checks = (
        ("fiscal & taxation controls", ("tax", "budget", "expenditure", "audit", "levy", "treasury", "debt")),
        ("procurement & anti-corruption oversight", ("tender", "procurement", "corruption", "embezzlement", "graft", "audit discrepancy")),
        ("currency & macro stability", ("inflation", "currency", "exchange rate", "parallel market", "depreciation", "fuel")),
        ("regulatory & civic compliance", ("private voluntary", "supervision", "terrorist financing", "constitution", "amendment", "disabilities", "court")),
        ("border & infrastructure modernisation", ("toll", "border", "chirundu", "forbes", "road", "energy", "mining")),
        ("executive portfolio governance", ("assignment of functions", "minister", "lands", "agriculture", "local authority")),
    )
    for label, keywords in checks:
        if any(kw in lower for kw in keywords):
            themes.append(label)
    return themes[:2]


def _build_issue_summary_and_excerpt(title, category, status, raw_snippet="", url="", submission_date=None):
    clean_snippet = " ".join(str(raw_snippet or "").split())
    citation = _extract_akn_citation(url)
    if clean_snippet and clean_snippet.lower() != str(title or "").strip().lower():
        content_excerpt = clean_snippet[:420] + ("…" if len(clean_snippet) > 420 else "")
    elif citation:
        date_note = f" (gazetted/dated {submission_date})" if submission_date else ""
        content_excerpt = f"{citation}{date_note} — {title}."
    else:
        content_excerpt = f"{title} ({category} · {status})."

    themes = _infer_policy_themes(f"{title} {clean_snippet}")
    theme_clause = f" Focuses on {' and '.join(themes)}." if themes else ""
    date_clause = f" Dated {submission_date}." if submission_date else ""

    if clean_snippet and len(clean_snippet) >= 45 and clean_snippet.lower() != str(title or "").strip().lower():
        first_sentence = re.split(r"(?<=[.!?])\s+", clean_snippet, maxsplit=1)[0]
        if len(first_sentence) > 220:
            first_sentence = first_sentence[:217].rstrip() + "…"
        summary = f"{first_sentence}{theme_clause}"
    elif citation:
        summary = f"{citation} ({status}).{date_clause}{theme_clause}"
    else:
        summary = f"{category} record classified as {status}.{date_clause}{theme_clause}"

    return summary.strip(), content_excerpt.strip()


def _enrich_and_rank_topics(topics):
    """Filter nav chrome, enrich missing metadata strictly from real record properties, and rank by friction risk."""
    if not isinstance(topics, list):
        return []
    deduped = {}
    for raw in topics:
        if not isinstance(raw, dict):
            continue
        raw_title = " ".join(str(raw.get("topic") or "").split())
        url = str(raw.get("url") or "").strip()
        if not raw_title or _is_non_issue_link(raw_title, url):
            continue
        title = _clean_issue_title(raw_title)
        category = str(raw.get("category") or "Parliament").strip()
        status = str(raw.get("status") or raw.get("action_status") or "Tracked").strip()
        raw_friction = raw.get("friction", raw.get("friction_score"))
        friction = round(float(raw_friction), 2) if isinstance(raw_friction, (int, float)) and not isinstance(raw_friction, bool) and math.isfinite(raw_friction) else 42.0

        existing_full = str(raw.get("full_content") or "").strip()
        existing_excerpt = str(raw.get("content_excerpt") or "").strip() or existing_full[:420]
        existing_summary = str(raw.get("summary") or "").strip()
        submission_date = raw.get("submission_date") or _extract_submission_date(
            title, existing_excerpt, existing_summary, url=url
        )
        responsible_person = str(raw.get("responsible_person") or raw.get("responsible") or "").strip()
        if not responsible_person or responsible_person == "Not stated in portal index":
            responsible_person = _extract_responsible_person(existing_excerpt, title=title)
        if not existing_summary or not existing_excerpt:
            computed_summary, computed_excerpt = _build_issue_summary_and_excerpt(
                title, category, status, raw_snippet=existing_excerpt, url=url, submission_date=submission_date
            )
            summary = existing_summary or computed_summary
            content_excerpt = existing_excerpt or computed_excerpt
        else:
            summary = existing_summary
            content_excerpt = existing_excerpt

        enriched = {
            **raw,
            "topic": title[:200],
            "category": category,
            "status": status,
            "friction": friction,
            "url": url,
            "submission_date": submission_date,
            "responsible_person": responsible_person,
            "responsible": responsible_person,
            "summary": summary,
            "content_excerpt": content_excerpt,
        }
        if existing_full:
            enriched["full_content"] = existing_full
        key = (title.lower(), category.lower())
        prev = deduped.get(key)
        if prev is None or len(enriched["content_excerpt"]) > len(prev.get("content_excerpt", "")):
            deduped[key] = enriched

    def _date_sort_key(val):
        digits = re.sub(r"\D", "", str(val or ""))
        if len(digits) == 6:
            digits += "01"
        return int(digits) if len(digits) == 8 else 0

    ranked = sorted(
        deduped.values(),
        key=lambda item: (
            -float(item.get("friction") or 0.0),
            -_date_sort_key(item.get("submission_date")),
            item.get("topic", "").lower(),
        ),
    )
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
    return ranked


def _extract_rss_topics(raw_xml, category, base_url, limit=4):
    try:
        root = ET.fromstring(raw_xml)
    except Exception:
        return [], ""
    category_status = {
        "Bill Digests": "Legislative Pipeline",
        "Enacted Acts": "Enacted / Gazetted",
        "Policy Briefs": "Policy Review",
        "Fact Sheets": "Briefing Published",
        "Hansards": "Parliamentary Debate",
    }.get(category, "Tracked")

    items = root.findall(".//item")
    text_parts = []
    candidates = []
    seen = set()
    dc_ns = "{http://purl.org/dc/elements/1.1/}"
    for item in items:
        title = " ".join(_strip_html(item.findtext("title") or "").split())
        link = (item.findtext("link") or base_url).strip()
        desc = " ".join(_strip_html(item.findtext("description") or "").split())
        pub_date = (item.findtext("pubDate") or item.findtext(f"{dc_ns}date") or "").strip()
        author = (item.findtext(f"{dc_ns}creator") or item.findtext("author") or "").strip()
        source_el = item.find("source")
        source_name = (source_el.text or "").strip() if source_el is not None else ""
        if title:
            text_parts.append(title)
        if desc:
            text_parts.append(desc)
        lower_title = title.lower()
        if len(title) >= 12 and lower_title not in seen and len(candidates) < limit:
            seen.add(lower_title)
            friction = score_hansard_text(f"{title} {desc}")
            submission_date = _extract_submission_date(title, desc, pub_date=pub_date, url=link)
            responsible_person = _extract_responsible_person(
                desc, author=author, source_name=source_name, title=title
            )
            summary, content_excerpt = _build_issue_summary_and_excerpt(
                title, category, category_status, raw_snippet=desc, url=link, submission_date=submission_date
            )
            candidates.append({
                "topic": title[:160],
                "category": category,
                "status": category_status,
                "friction": friction if friction is not None else 42.0,
                "url": link,
                "submission_date": submission_date,
                "responsible_person": responsible_person,
                "summary": summary,
                "content_excerpt": content_excerpt,
            })
    return candidates, " ".join(text_parts)


def extract_legislative_topics(raw_html, category, base_url, limit=4):
    """Extract real document/debate titles, dates, sponsors, and summaries from accessible HTML or XML RSS pages."""
    if not raw_html:
        return []
    stripped_start = raw_html.lstrip()
    if stripped_start.startswith("<?xml") or "<rss" in stripped_start[:300].lower():
        rss_candidates, _ = _extract_rss_topics(raw_html, category, base_url, limit=limit)
        return rss_candidates

    category_status = {
        "Bill Digests": "Legislative Pipeline",
        "Enacted Acts": "Enacted / Gazetted",
        "Policy Briefs": "Policy Review",
        "Fact Sheets": "Briefing Published",
        "Hansards": "Parliamentary Debate",
    }.get(category, "Tracked")

    skip_phrases = {
        "skip to content", "skip to document content", "skip to main menu", "skip to search",
        "home", "about us", "contact us", "read more", "filter results",
        "menu", "search", "login", "register", "privacy policy", "parliament of zimbabwe",
        "current legislation", "recent legislation", "subsidiary legislation",
        "uncommenced legislation", "repealed legislation",
    }
    candidates = []
    seen = set()

    content_html = _strip_navigation_chrome(raw_html)
    patterns = (
        (
            r'(?is)<a[^>]+href=["\'](/akn/zw/[^"\']+)["\'][^>]*>(.*?)</a>',
            r"(?is)<h[1-4][^>]*>(.*?)</h[1-4]>",
        )
        if "zimlii.org" in (base_url or "").lower()
        else (
            r"(?is)<h[1-4][^>]*>(.*?)</h[1-4]>",
            r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        )
    )

    for pattern in patterns:
        for match in re.finditer(pattern, content_html):
            if match.lastindex == 1:
                href = base_url
                raw_title = match.group(1)
            else:
                href = html_lib.unescape(match.group(1)).strip()
                raw_title = match.group(2)
                if href.startswith("#") or href.lower().startswith("javascript:"):
                    continue
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(base_url, href)
            title = _clean_issue_title(_strip_html(raw_title))
            lower_title = title.lower()
            if (
                len(title) < 12
                or len(title) > 160
                or lower_title in skip_phrases
                or lower_title in seen
                or _is_non_issue_link(title, href, check_category_root=(match.lastindex != 1))
                or not re.search(r"[a-zA-Z]{4,}", title)
            ):
                continue
            seen.add(lower_title)
            row_start = max(0, match.start() - 250)
            row_end = min(len(content_html), match.end() + 450)
            context_html = content_html[row_start:row_end]
            tr_start = content_html.rfind("<tr", max(0, match.start() - 1200), match.start())
            tr_end = content_html.find("</tr>", match.end(), min(len(content_html), match.end() + 1200))
            if tr_start != -1 and tr_end != -1:
                context_html = content_html[tr_start:tr_end + 5]
            context_text = " ".join(_strip_html(context_html).split())
            time_match = re.search(r'datetime=["\']([^"\']+)["\']', context_html, re.IGNORECASE)
            time_attr = time_match.group(1) if time_match else ""

            friction = score_hansard_text(f"{title} {context_text}")
            submission_date = _extract_submission_date(title, context_text, pub_date=time_attr, url=href)
            responsible_person = _extract_responsible_person(context_text, title=title)
            summary, content_excerpt = _build_issue_summary_and_excerpt(
                title, category, category_status, raw_snippet=context_text, url=href, submission_date=submission_date
            )
            candidates.append({
                "topic": title,
                "category": category,
                "status": category_status,
                "friction": friction if friction is not None else 42.0,
                "url": href,
                "submission_date": submission_date,
                "responsible_person": responsible_person,
                "responsible": responsible_person,
                "summary": summary,
                "content_excerpt": content_excerpt,
            })
            if len(candidates) >= limit:
                return candidates
    return candidates


def _get_parlzim_portals():
    return PARLZIM_STATIC_PORTALS + (("Hansards", HANSARD_PORTAL_URL),)


def _normalize_flaresolverr_endpoint(endpoint):
    trimmed = (endpoint or "").strip().rstrip("/")
    if not trimmed:
        return ""
    return trimmed if trimmed.endswith("/v1") else f"{trimmed}/v1"


def _fetch_via_flaresolverr(portal_url, timeout=20):
    solver_endpoint = _normalize_flaresolverr_endpoint(
        os.environ.get("FLARESOLVERR_URL", FLARESOLVERR_URL)
    )
    if not solver_endpoint:
        return None
    payload = json.dumps({
        "cmd": "request.get",
        "url": portal_url,
        "maxTimeout": int(timeout * 1000),
    }).encode("utf-8")
    req = urllib.request.Request(
        solver_endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
            solved = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None
    sol = solved.get("solution") or {}
    if solved.get("status") == "ok" and sol.get("response"):
        headers = {str(k).lower(): str(v) for k, v in (sol.get("headers") or {}).items()}
        body = _decode_portal_body(portal_url, headers, sol.get("response", ""))
        return int(sol.get("status", 200)), body, headers, "flaresolverr"
    return None


def _fetch_via_scraperapi(target_url, timeout=25):
    """Optional ScraperAPI proxy fetch when SCRAPER_API_KEY env var is configured."""
    api_key = os.environ.get("SCRAPER_API_KEY", SCRAPER_API_KEY).strip()
    if not api_key or not target_url:
        return None
    proxy_url = "https://api.scraperapi.com/"
    params = {"api_key": api_key, "url": target_url, "render": "false"}
    try:
        if cureq is not None:
            response = cureq.get(proxy_url, params=params, timeout=max(timeout, 25))
            status_code = getattr(response, "status_code", 200)
            headers = {str(k).lower(): str(v) for k, v in getattr(response, "headers", {}).items()}
            raw_content = getattr(response, "content", None)
            raw_payload = raw_content if isinstance(raw_content, (bytes, bytearray)) else (getattr(response, "text", "") or "")
            body = _decode_portal_body(target_url, headers, raw_payload)
            if status_code == 200 and body:
                return status_code, body, headers, "scraperapi"
            return None

        from urllib.parse import urlencode
        query_url = f"{proxy_url}?{urlencode(params)}"
        req = urllib.request.Request(
            query_url,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8"},
        )
        with urllib.request.urlopen(req, timeout=max(timeout, 25)) as resp:
            status_code = getattr(resp, "status", 200)
            headers = {str(k).lower(): str(v) for k, v in getattr(resp, "headers", {}).items()}
            body = _decode_portal_body(target_url, headers, resp.read())
            if status_code == 200 and body:
                return status_code, body, headers, "scraperapi"
    except Exception:
        return None
    return None


def extract_text_from_pdf_bytes(pdf_bytes, max_pages=12):
    """Extract normalized text streams natively from PDF bytes using pypdf."""
    if not pdf_bytes or PdfReader is None:
        return ""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages[:max_pages]:
            extracted = page.extract_text() or ""
            if extracted.strip():
                pages_text.append(extracted)
        return " ".join(" ".join(pages_text).split())
    except Exception:
        return ""


def extract_pdf_text(pdf_bytes, max_pages=12):
    """Alias for extract_text_from_pdf_bytes."""
    return extract_text_from_pdf_bytes(pdf_bytes, max_pages=max_pages)


def _is_pdf_payload(portal_url, headers, raw_payload):
    content_type = (headers or {}).get("content-type", "").lower()
    if "application/pdf" in content_type:
        return True
    if (portal_url or "").lower().split("?")[0].endswith(".pdf"):
        return True
    if isinstance(raw_payload, (bytes, bytearray)):
        return raw_payload.lstrip()[:5] == b"%PDF-"
    if isinstance(raw_payload, str):
        return raw_payload.lstrip()[:5] == "%PDF-"
    return False


def _decode_portal_body(portal_url, headers, raw_payload):
    if _is_pdf_payload(portal_url, headers, raw_payload):
        raw_bytes = raw_payload if isinstance(raw_payload, (bytes, bytearray)) else str(raw_payload).encode("latin-1", errors="ignore")
        pdf_text = extract_text_from_pdf_bytes(raw_bytes)
        if pdf_text:
            return f"<html><body><p>{html_lib.escape(pdf_text)}</p></body></html>"
        return ""
    if isinstance(raw_payload, (bytes, bytearray)):
        return raw_payload.decode("utf-8", errors="ignore")
    return raw_payload or ""


def _parse_pdf_info_date(raw_value):
    match = re.match(r"^(?:D:)?(20\d{2})(\d{2})?(\d{2})?", str(raw_value or "").strip())
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None
    if month and 1 <= month <= 12:
        if day and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return f"{year:04d}-{month:02d}"
    return None


def _read_pdf_info_and_text(pdf_bytes, max_pages=None):
    if not pdf_bytes or PdfReader is None:
        return {}, "", "", 0
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        all_pages = list(reader.pages) if max_pages is None else list(reader.pages[:max_pages])
        page_count = len(reader.pages)
        structured_pages = []
        flat_pages = []
        for idx, page in enumerate(all_pages):
            extracted = page.extract_text() or ""
            if extracted.strip():
                structured_pages.append(f"--- Page {idx + 1} ---\n{extracted.strip()}")
                flat_pages.append(extracted)
        raw_meta = getattr(reader, "metadata", None) or {}
        info = {}
        if isinstance(raw_meta, dict) or hasattr(raw_meta, "get"):
            for key, alias in (
                ("/Title", "title"), ("title", "title"),
                ("/Author", "author"), ("author", "author"),
                ("/CreationDate", "creation_date"), ("creation_date", "creation_date"),
                ("/ModDate", "mod_date"), ("mod_date", "mod_date"),
            ):
                val = raw_meta.get(key)
                if isinstance(val, str) and val.strip() and alias not in info:
                    info[alias] = val.strip()
        full_structured = re.sub(r"[ \t]+", " ", "\n\n".join(structured_pages)).strip()
        flat_text = " ".join(" ".join(flat_pages).split())
        return info, full_structured, flat_text, page_count
    except Exception:
        return {}, "", "", 0


def extract_full_pdf_text(pdf_bytes, max_pages=None):
    """Extract page-delimited text across all pages of a PDF binary using pypdf."""
    _info, full_structured, _flat, _count = _read_pdf_info_and_text(pdf_bytes, max_pages=max_pages)
    return full_structured


def _is_heading_line(line):
    words = [w for w in re.findall(r"[A-Za-z]+", line) if len(w) >= 3]
    if len(words) < 3:
        return False
    cap_ratio = sum(1 for w in words if w[0].isupper()) / len(words)
    if line.endswith(".") and not re.search(r"\b(?:Act|Bill|Report|Notice|Regulations)\.$", line, re.IGNORECASE):
        return False
    return cap_ratio >= 0.6


def _extract_pdf_true_title(info, full_structured, fallback_title=""):
    raw_meta_title = " ".join(str((info or {}).get("title") or "").split())
    if (
        12 <= len(raw_meta_title) <= 140
        and not re.match(r"^(?:file://|https?://|\\\\|[a-z]:\\)", raw_meta_title, re.IGNORECASE)
        and not re.search(r"\b(?:untitled|document\s*\d*|microsoft|adobe|libreoffice|slide|vote\s+\d+)\b|\.(?:pdf|docx?|pptx?|indd|html?)$", raw_meta_title, re.IGNORECASE)
        and not _is_non_issue_link(raw_meta_title)
        and re.search(r"[a-zA-Z]{4,}", raw_meta_title)
    ):
        cleaned_meta = re.sub(r"^Name[:\s]+", "", raw_meta_title, flags=re.IGNORECASE).strip(" ,;:-")
        if len(cleaned_meta) >= 10:
            return _clean_issue_title(cleaned_meta)

    first_page = str(full_structured or "").split("--- Page 2 ---", 1)[0]
    first_lines = [
        " ".join(raw_line.split()).strip(" :-–—|")
        for raw_line in first_page.splitlines()
        if " ".join(raw_line.split()).strip(" :-–—|")
    ]
    joined_head = " ".join(first_lines[:8])

    if re.search(r"VOTES AND PROCEEDINGS OF\s+THE NATIONAL ASSEMBLY", joined_head, re.IGNORECASE):
        date_hit = _parse_iso_date_str(joined_head)
        no_match = re.search(r"\bNo\.?\s*(\d+)\b", joined_head, re.IGNORECASE)
        no_str = f" (No. {no_match.group(1)})" if no_match else ""
        date_str = f" — {date_hit}" if date_hit else ""
        return f"National Assembly Votes and Proceedings{date_str}{no_str}"

    if "PARLIAMENT OF ZIMBABWE" in joined_head.upper() and ("The National Assembly met" in joined_head or "The Senate met" in joined_head):
        chamber = "Senate Hansard" if "The Senate met" in joined_head else "National Assembly Hansard"
        date_hit = _parse_iso_date_str(joined_head)
        vol_hint = ""
        fb_vol = re.search(r"\bVol\.?\s*(\d+)\s*No\.?\s*(\d+)\b", fallback_title or "", re.IGNORECASE)
        if fb_vol:
            vol_hint = f" Vol. {fb_vol.group(1)} No. {fb_vol.group(2)}"
        date_str = f" ({date_hit})" if date_hit else ""
        return f"{chamber}{vol_hint}{date_str}"

    report_block = " ".join(
        l for l in first_lines[:7]
        if not re.match(r"^(?:1\s*\|\s*P\s*a\s*g\s*e|SECOND SESSION.*|FIRST SESSION.*)$", l, re.IGNORECASE)
    )
    if re.match(r"^(?:first|second|third|joint)?\s*report of the\b", report_block, re.IGNORECASE):
        cleaned_report = re.sub(r"\bCOMMITTTEE\b", "Committee", report_block, flags=re.IGNORECASE)
        cleaned_report = re.sub(r"\s+\bS\.?\s*C\.?\s*\d+.*$", "", cleaned_report, flags=re.IGNORECASE)
        cleaned_report = " ".join(cleaned_report.split())
        if len(cleaned_report) >= 20:
            if cleaned_report.isupper():
                cleaned_report = re.sub(
                    r"\b(On|Of|And|For|The|In)\b",
                    lambda m: m.group(1).lower(),
                    cleaned_report.title(),
                )
                cleaned_report = cleaned_report[:1].upper() + cleaned_report[1:]
            return _clean_issue_title(cleaned_report)[:200]

    for line in first_lines:
        if line.startswith("--- Page "):
            continue
        if len(line) < 12 or len(line) > 125:
            continue
        if re.match(
            r"^(?:page\s*\d*|\d+|zimbabwe|parliament(?:\s+of\s+zimbabwe)?|national\s+assembly|senate|government\s+gazette|table\s+of\s+contents|contents|chapter\s+\d+|act\s+no\.?|bill\s+no\.?|h\.?b\.?\s*\d*|s\.?i\.?\s*\d*|distributed\s+by\s+veritas|prayers|p\s*ra\s*y\s*ers)$",
            line,
            re.IGNORECASE,
        ):
            continue
        if _is_non_issue_link(line):
            continue
        if re.search(r"\b(?:Blo\s+W\s+ers|a\s+mendment)\b", line) and fallback_title:
            return fallback_title
        if _is_heading_line(line):
            normalized = line.title() if line.isupper() else line
            return _clean_issue_title(normalized)[:160]
    return fallback_title


def _build_pdf_substantive_summary(full_structured, flat_text, max_chars=1200):
    raw_body = re.sub(r"---\s*Page\s+\d+\s*---", "\n", str(full_structured or ""))
    raw_body = re.sub(r"[\uf0b7]", "•", raw_body)
    raw_body = re.sub(r"[_=\-]{4,}", " ", raw_body)
    non_toc_lines = []
    for raw_line in raw_body.splitlines():
        clean_l = " ".join(raw_line.split()).strip()
        if not clean_l:
            continue
        if re.search(r"(?:\.{4,}|(?:\.\s){4,})", clean_l) or re.match(r"^(?:table of contents|contents|arrangement of sections)$", clean_l, re.IGNORECASE):
            continue
        non_toc_lines.append(clean_l)
    body = "\n".join(non_toc_lines)
    normalized = ""
    for pat, flags in (
        (r"\b(?:Explanatory\s+)?M\s*E?\s*M\s*o\s*r\s*a\s*n\s*d\s*u\s*M\b", re.IGNORECASE),
        (r"(?:^|\n)\s*(?:EXECUTIVE SUMMARY|BACKGROUND|\d+(?:\.\d+)?\s+INTRODUCTION|INTRODUCTION)\b", 0),
        (r"(?:^|\n)\s*(?:KEY FINDINGS|MAJOR FINDINGS|OVERVIEW)\b", 0),
        (r"\b(?:\d+\.\s+Reports from the Parliamentary Legal Committee|PETITIONS RECEIVED FROM|ANNOUNCEMENT BY THE|MINISTERIAL STATEMENT|THE MINISTER OF [A-Z][A-Z ,]+)\b", 0),
        (r"\bAN\s+ACT\s+to\b", 0),
    ):
        for match in re.finditer(pat, body, flags):
            candidate = " ".join(body[match.start():].split()).strip()
            candidate = re.sub(r"^Explanatory\s+M\s*e?\s*M\s*o\s*r\s*a\s*n\s*d\s*u\s*M\b", "Explanatory Memorandum:", candidate, flags=re.IGNORECASE)
            candidate = re.sub(r"^M\s*e?\s*M\s*o\s*r\s*a\s*n\s*d\s*u\s*M\b", "Memorandum:", candidate, flags=re.IGNORECASE)
            candidate = re.sub(r"\bExplanatory\s+M\s*E?\s*M\s*o\s*r\s*a\s*n\s*d\s*u\s*M\b", "Explanatory Memorandum:", candidate, flags=re.IGNORECASE)
            if len(candidate) >= 120 and not re.search(r"(?:\.{3,}|(?:\.\s){3,})", candidate[:200]):
                normalized = candidate
                break
        if normalized:
            break
    if not normalized:
        clean_lines = [
            line for line in non_toc_lines
            if len(line) >= 35 and not re.match(
                r"^(?:page\s*\d+|\d+|arrangement of sections|table of contents|contents|ordered in terms of standing order|terms of reference of portfolio committees|to top page|title \d+|chapter \d+:\d+|distributed by veritas)",
                line,
                re.IGNORECASE,
            )
        ]
        normalized = " ".join(clean_lines).strip() or " ".join(re.sub(r"(?:\.\s*){4,}", " ", str(flat_text or "")).split())

    if len(normalized) <= max_chars:
        return normalized
    clipped = normalized[:max_chars]
    last_period = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
    if last_period > max_chars * 0.55:
        return clipped[:last_period + 1].strip()
    return clipped.rstrip() + "..."


def extract_true_pdf_topic_and_text(pdf_bytes, fallback_title="", max_pages=None, pdf_url=""):
    """Extract true PDF heading/topic, submission date, responsible body/person, summary, and full text."""
    effective_max = max_pages if max_pages is not None else 45
    info, full_structured, flat_text, page_count = _read_pdf_info_and_text(pdf_bytes, max_pages=effective_max)
    if not flat_text:
        info_date = _parse_pdf_info_date(info.get("creation_date") or info.get("mod_date"))
        fallback_date = info_date or _extract_submission_date(url=pdf_url)
        return fallback_title, fallback_date, "Not stated in PDF", "", ""
    true_topic = _extract_pdf_true_title(info, full_structured, fallback_title=fallback_title)
    head_text = flat_text[:5000]
    submission_date = _extract_submission_date(head_text)
    if not submission_date:
        submission_date = _parse_pdf_info_date(info.get("creation_date") or info.get("mod_date"))
    if not submission_date:
        submission_date = _extract_submission_date(url=pdf_url)

    raw_pdf_author = info.get("author", "")
    if GENERIC_PDF_AUTHORS_RE.match(raw_pdf_author.strip()) or re.search(r"microsoft|adobe|libreoffice|writer|pypdf", raw_pdf_author, re.IGNORECASE):
        raw_pdf_author = ""
    responsible_person = _extract_responsible_person(head_text)
    if responsible_person == "Not stated in portal index":
        responsible_person = raw_pdf_author[:120] if raw_pdf_author and "@" not in raw_pdf_author and len(raw_pdf_author) >= 3 else "Not stated in PDF"
    summary = _build_pdf_substantive_summary(full_structured, flat_text, max_chars=1200)
    full_payload = full_structured[:60000] + ("\n\n[Truncated after 60,000 characters]" if len(full_structured) > 60000 else "")
    if page_count:
        info["page_count"] = page_count
    return true_topic, submission_date, responsible_person, summary, full_payload


def extract_pdf_metadata_and_text(pdf_bytes, max_pages=None, pdf_url=""):
    """Extract complete page text, submission date, responsible body/person, and 1200-char summary from PDF bytes."""
    _topic, submission_date, responsible_person, summary, full_payload = extract_true_pdf_topic_and_text(
        pdf_bytes, fallback_title="", max_pages=max_pages, pdf_url=pdf_url
    )
    return submission_date, responsible_person, summary, full_payload


def extract_pdf_links(raw_html, base_url, limit=4):
    """Discover real .pdf document links inside main HTML content."""
    if not raw_html or not base_url:
        return []
    from urllib.parse import urljoin, urlparse
    content_html = _strip_navigation_chrome(raw_html)
    generic_labels = {"download", "download pdf", "pdf", "view", "view pdf", "read more", "open"}
    links = []
    seen_urls = set()
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(content_html, "html.parser")
            anchors = [
                (a.get("data-downloadurl") or a.get("data-pdf") or a.get("href", ""), a.get_text(" ", strip=True))
                for a in soup.find_all(["a", "button"], href=True)
            ]
            for tag in soup.find_all(["iframe", "embed", "object"]):
                media_url = tag.get("src") or tag.get("data") or ""
                if ".pdf" in str(media_url).lower():
                    anchors.append((media_url, tag.get("title") or ""))
        except Exception:
            anchors = [
                (html_lib.unescape(m.group(1)).strip(), _strip_html(m.group(2)))
                for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content_html)
            ]
    else:
        anchors = [
            (html_lib.unescape(m.group(1)).strip(), _strip_html(m.group(2)))
            for m in re.finditer(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content_html)
        ]
        for em in re.finditer(r'(?is)<(?:iframe|embed|object)[^>]+(?:src|data)=["\']([^"\']*\.pdf[^"\']*)["\']', content_html):
            anchors.append((html_lib.unescape(em.group(1)).strip(), ""))

    for href, anchor_text in anchors:
        href = str(href or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        resolved = urljoin(base_url, href)
        parsed = urlparse(resolved)
        if not (parsed.path.lower().endswith(".pdf") or ".pdf" in resolved.lower()):
            continue
        if resolved in seen_urls or _is_non_issue_link("", resolved):
            continue
        seen_urls.add(resolved)
        label = _clean_issue_title(anchor_text)
        if not label or label.lower() in generic_labels or len(label) < 6:
            filename = os.path.splitext(os.path.basename(parsed.path))[0]
            label = _clean_issue_title(filename) or "Parliamentary PDF Document"
        links.append({"url": resolved, "title": label[:160]})
        if len(links) >= limit:
            break
    return links


def fetch_true_pdf_document(pdf_url, fallback_title="", timeout=12):
    """Download PDF binary and return (true_topic, submission_date, responsible_person, summary, full_text) via pypdf."""
    if PdfReader is None or not pdf_url:
        return fallback_title, None, "Not stated in PDF", "", ""
    raw_bytes = None
    try:
        if cureq is not None:
            response = cureq.get(pdf_url, impersonate="chrome", timeout=timeout)
            if getattr(response, "status_code", 0) == 200:
                candidate = getattr(response, "content", b"") or b""
                if candidate:
                    raw_bytes = candidate
        else:
            req = urllib.request.Request(
                pdf_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "application/pdf,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if getattr(response, "status", 200) == 200:
                    candidate = response.read()
                    if candidate:
                        raw_bytes = candidate
    except Exception:
        pass

    if not raw_bytes:
        api_key = os.environ.get("SCRAPER_API_KEY", SCRAPER_API_KEY).strip()
        if api_key:
            try:
                proxy_url = "https://api.scraperapi.com/"
                params = {"api_key": api_key, "url": pdf_url, "render": "false"}
                if cureq is not None:
                    response = cureq.get(proxy_url, params=params, timeout=max(timeout, 25))
                    if getattr(response, "status_code", 0) == 200:
                        raw_bytes = getattr(response, "content", b"") or b""
                else:
                    from urllib.parse import urlencode
                    req = urllib.request.Request(f"{proxy_url}?{urlencode(params)}")
                    with urllib.request.urlopen(req, timeout=max(timeout, 25)) as resp:
                        if getattr(resp, "status", 200) == 200:
                            raw_bytes = resp.read()
            except Exception:
                pass

    if raw_bytes:
        return extract_true_pdf_topic_and_text(
            raw_bytes, fallback_title=fallback_title, max_pages=None, pdf_url=pdf_url
        )

    if os.environ.get("FLARESOLVERR_URL", FLARESOLVERR_URL).strip():
        solved = _fetch_via_flaresolverr(pdf_url, timeout=max(timeout, 20))
        if solved is not None:
            status_code, solved_body, _headers, _transport = solved
            if status_code == 200 and solved_body:
                solved_text = _strip_html(solved_body)
                return (
                    fallback_title,
                    _extract_submission_date(solved_text[:2500], url=pdf_url),
                    _extract_responsible_person(solved_text[:2500]),
                    solved_text[:1200],
                    solved_text,
                )
    return fallback_title, None, "Not stated in PDF", "", ""


def fetch_pdf_document_metadata(pdf_url, timeout=12):
    """Download PDF binary and return (submission_date, responsible_person, summary, full_text) using pypdf."""
    _topic, sub_date, person, summary, full_text = fetch_true_pdf_document(pdf_url, fallback_title="", timeout=timeout)
    return sub_date, person, summary, full_text


def fetch_pdf_document_text(pdf_url, timeout=12):
    """Download and extract normalized text from a PDF document URL via Chrome TLS impersonation, ScraperAPI, FlareSolverr, or urllib."""
    _date, _person, _summary, full_text = fetch_pdf_document_metadata(pdf_url, timeout=timeout)
    return full_text


def _fetch_portal_response(portal_url, timeout=10):
    """Fetch a portal using curl_cffi Chrome TLS impersonation (and optional ScraperAPI / FlareSolverr), else urllib; decodes PDFs via pypdf."""
    if cureq is not None:
        response = cureq.get(portal_url, impersonate="chrome", timeout=timeout)
        status_code = getattr(response, "status_code", 200)
        headers = {str(k).lower(): str(v) for k, v in getattr(response, "headers", {}).items()}
        raw_content = getattr(response, "content", None)
        raw_payload = raw_content if isinstance(raw_content, (bytes, bytearray)) else (getattr(response, "text", "") or "")
        body = _decode_portal_body(portal_url, headers, raw_payload)
        if status_code == 403 and os.environ.get("SCRAPER_API_KEY", SCRAPER_API_KEY).strip():
            proxied = _fetch_via_scraperapi(portal_url, timeout=max(timeout, 25))
            if proxied is not None:
                return proxied
        if status_code == 403 and os.environ.get("FLARESOLVERR_URL", FLARESOLVERR_URL).strip():
            solved = _fetch_via_flaresolverr(portal_url, timeout=max(timeout, 20))
            if solved is not None:
                return solved
        return status_code, body, headers, "curl_cffi_chrome"

    req = urllib.request.Request(
        portal_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=min(timeout, 8)) as response:
            status_code = getattr(response, "status", 200)
            headers = {str(k).lower(): str(v) for k, v in getattr(response, "headers", {}).items()}
            raw_bytes = response.read()
            body = _decode_portal_body(portal_url, headers, raw_bytes)
        return status_code, body, headers, "urllib"
    except urllib.error.HTTPError as err:
        if err.code == 403 and os.environ.get("SCRAPER_API_KEY", SCRAPER_API_KEY).strip():
            proxied = _fetch_via_scraperapi(portal_url, timeout=max(timeout, 25))
            if proxied is not None:
                return proxied
        if err.code == 403 and os.environ.get("FLARESOLVERR_URL", FLARESOLVERR_URL).strip():
            solved = _fetch_via_flaresolverr(portal_url, timeout=max(timeout, 20))
            if solved is not None:
                return solved
        raise


def _extract_wp_json_topics_and_pdfs(raw_json, category, base_url, limit=4):
    """Extract real Zimbabwe Parliamentary posts, metadata, and PDF URLs from WP REST JSON."""
    try:
        items = json.loads(raw_json)
    except Exception:
        return [], [], ""
    if not isinstance(items, list):
        return [], [], ""

    category_status = {
        "Bill Digests": "Legislative Pipeline",
        "Enacted Acts": "Enacted / Gazetted",
        "Policy Briefs": "Policy Review",
        "Fact Sheets": "Briefing Published",
        "Hansards": "Parliamentary Debate",
    }.get(category, "Tracked")

    skip_title_re = re.compile(
        r"^(?:Document\s*\d+|MEDIA RELEASE|33RD POST-CABINET|31ST-POST-CABINET|UK MPs|How to|AI WhatsApp)",
        re.IGNORECASE,
    )
    topics = []
    pdf_links = []
    seen_pdfs = set()
    text_parts = []

    for item in items:
        if not isinstance(item, dict):
            continue
        raw_title = (item.get("title") or {}).get("rendered", "") if isinstance(item.get("title"), dict) else str(item.get("title") or "")
        title = _clean_issue_title(_strip_html(raw_title))
        if not title or len(title) < 8 or skip_title_re.search(title):
            continue

        source_url = str(item.get("source_url") or "").strip()
        link = str(item.get("link") or source_url or base_url).strip()
        pub_date = str(item.get("date") or "").strip()[:10]

        author_name = ""
        embedded = item.get("_embedded") or {}
        if isinstance(embedded, dict):
            authors = embedded.get("author") or []
            if authors and isinstance(authors[0], dict):
                author_name = str(authors[0].get("name") or "").strip()

        raw_content = (item.get("content") or {}).get("rendered", "") if isinstance(item.get("content"), dict) else ""
        raw_excerpt = (item.get("excerpt") or {}).get("rendered", "") if isinstance(item.get("excerpt"), dict) else ""
        snippet = _strip_html(raw_content or raw_excerpt)

        if category == "Hansards":
            hay = f"{title} {source_url}".lower()
            if not re.search(r"(hansard|votes|vol\.?\s*\d+|senate|national[\s_-]assembly)", hay, re.IGNORECASE):
                continue
        elif category == "Bill Digests":
            hay = f"{title} {source_url}".lower()
            if not re.search(r"(bill|h\.?b\.?|amendment|constitution)", hay, re.IGNORECASE):
                continue
        elif category == "Policy Briefs":
            if re.search(r"2026-National-Budget-25-November-2025-final\.pdf", source_url, re.IGNORECASE):
                continue

        if title:
            text_parts.append(title)
        if snippet:
            text_parts.append(snippet[:900])

        item_pdfs = []
        if source_url.lower().split("?")[0].endswith(".pdf"):
            item_pdfs.append(source_url)
        for m in re.finditer(r"https?://[^\"'\s<>]+\.pdf", raw_content, re.IGNORECASE):
            item_pdfs.append(m.group(0))

        for pdf_u in item_pdfs:
            if pdf_u in seen_pdfs or _is_non_issue_link(title, pdf_u):
                continue
            seen_pdfs.add(pdf_u)
            clean_label = re.sub(r"\s*\[(?:Download|Explanation)\]\s*", "", title, flags=re.IGNORECASE).strip()
            pdf_links.append({"url": pdf_u, "title": clean_label[:160], "pub_date": pub_date})
            if len(pdf_links) >= limit:
                break

        if not item_pdfs and len(topics) < limit and (
            "openparly.com" not in base_url
            or any(k in f"{title} {snippet}".lower() for k in ("zimbabwe", "bill", "parliament", "budget"))
        ):
            clean_label = re.sub(r"\s*\[(?:Download|Explanation)\]\s*", "", title, flags=re.IGNORECASE).strip()
            friction = score_hansard_text(f"{clean_label} {snippet}")
            sub_date = _extract_submission_date(clean_label, snippet, pub_date=pub_date, url=link)
            person = _extract_responsible_person(snippet, author=author_name, title=clean_label)
            summary, excerpt = _build_issue_summary_and_excerpt(
                clean_label, category, category_status, raw_snippet=snippet[:900], url=link, submission_date=sub_date
            )
            topics.append({
                "topic": clean_label[:160],
                "category": category,
                "status": category_status,
                "friction": friction if friction is not None else 42.0,
                "url": link,
                "submission_date": sub_date,
                "responsible_person": person,
                "responsible": person,
                "summary": summary,
                "content_excerpt": excerpt,
            })

    return topics[:limit], pdf_links[:limit], " ".join(text_parts)


def _discover_portal_subroutes(category, portal_url, raw_html):
    """Find official e-portal Hansard or ParlZim sub-routes/APIs when the landing HTML is an SPA or nav shell."""
    from urllib.parse import urljoin, urlparse
    candidates = []
    parsed_base = urlparse(portal_url)
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}" if parsed_base.scheme and parsed_base.netloc else portal_url.rstrip("/")

    for m in re.finditer(r'(?is)<(?:iframe|frame|a)[^>]+(?:src|href)=["\']([^"\']+)["\']', raw_html or ""):
        href = html_lib.unescape(m.group(1)).strip()
        if any(k in href.lower() for k in ("hansard", "bill-digest", "policy-brief", "publication", "document", "wp-json", "/api/")):
            full = urljoin(portal_url, href)
            if full != portal_url and full not in candidates:
                candidates.append(full)

    if category == "Hansards":
        for path in (
            "/hansards",
            "/hansard",
            "/publications",
            "/documents",
            "/national-assembly-hansard",
            "/senate-hansard",
            "/api/hansards",
            "/wp-json/wp/v2/media?mime_type=application/pdf&per_page=10",
        ):
            full = f"{origin}{path}"
            if full != portal_url and full not in candidates:
                candidates.append(full)
    elif category in ("Bill Digests", "Policy Briefs"):
        slug = "bill" if category == "Bill Digests" else "policy"
        for path in (
            f"/wp-json/wp/v2/media?mime_type=application/pdf&search={slug}&per_page=10",
            f"/wp-json/wp/v2/posts?search={slug}&per_page=8",
        ):
            full = f"{origin}{path}"
            if full not in candidates:
                candidates.append(full)

    return candidates[:6]


def _ingest_pdf_links_for_category(pdf_links, category, existing_topics, stripped_text, timeout=12):
    pdf_topics = []
    pdf_text_chunks = []
    pdf_count = 0
    for pdf_link in pdf_links:
        true_topic, pdf_date, pdf_person, raw_pdf_summary, pdf_text = fetch_true_pdf_document(
            pdf_link["url"], fallback_title=pdf_link["title"], timeout=timeout
        )
        if len(pdf_text) >= 80:
            pdf_count += 1
            flat_pdf_body = " ".join(re.sub(r"---\s*Page\s+\d+\s*---", " ", pdf_text).split())
            pdf_score = score_hansard_text(flat_pdf_body)
            pdf_text_chunks.append(flat_pdf_body)
            resolved_topic = true_topic or pdf_link["title"]
            if not pdf_date:
                pdf_date = pdf_link.get("pub_date") or _extract_submission_date(resolved_topic, url=pdf_link["url"])
            if not pdf_person or pdf_person in ("Not stated in PDF", "Not stated in portal index"):
                pdf_person = _extract_responsible_person(resolved_topic, title=resolved_topic)
            computed_summary, pdf_excerpt = _build_issue_summary_and_excerpt(
                resolved_topic,
                category,
                "PDF Downloaded & Ingested",
                raw_snippet=flat_pdf_body[:900],
                url=pdf_link["url"],
                submission_date=pdf_date,
            )
            page_markers = len(re.findall(r"---\s*Page\s+\d+\s*---", pdf_text))
            topic_item = {
                "topic": resolved_topic,
                "category": category,
                "status": "PDF Downloaded & Ingested",
                "friction": pdf_score if pdf_score is not None else 42.0,
                "url": pdf_link["url"],
                "submission_date": pdf_date,
                "responsible_person": pdf_person,
                "responsible": pdf_person,
                "summary": raw_pdf_summary or computed_summary,
                "content_excerpt": pdf_excerpt,
                "full_content": pdf_text,
            }
            if page_markers > 0:
                topic_item["page_count"] = page_markers
            pdf_topics.append(topic_item)
    if pdf_text_chunks:
        stripped_text = f"{stripped_text} {' '.join(pdf_text_chunks)}".strip()
        seen_pdf_urls = {item["url"] for item in pdf_topics}
        merged_topics = pdf_topics + [t for t in existing_topics if t.get("url") not in seen_pdf_urls]
        return merged_topics, stripped_text, pdf_count
    return existing_topics, stripped_text, pdf_count


def fetch_parliamentary_policy_tracker(use_cache=True, allow_mirror_fallback=True):
    """Read verified telemetry_cache.json first when cached; otherwise crawl the 5 ParlZim portals with automatic CF-free legislative mirror failover."""
    now = time.monotonic()
    if use_cache:
        if HANSARD_CACHE["data"] is not None and HANSARD_CACHE["expires_at"] > now:
            return HANSARD_CACHE["data"]
        disk_cache = _load_verified_telemetry_cache(allow_fresh_blocked=True)
        if disk_cache is not None:
            HANSARD_CACHE["data"] = disk_cache
            HANSARD_CACHE["expires_at"] = now + (
                HANSARD_TTL_SECONDS if disk_cache.get("status") == "available" else HANSARD_ERROR_TTL_SECONDS
            )
            return disk_cache

    sources_status = []
    scores = []
    tracked_topics = []
    total_chars = 0
    blocked_count = 0

    for category, portal_url in _get_parlzim_portals():
        primary_blocked_cf = False
        primary_error_msg = None
        primary_http_status = None
        selected_url = portal_url
        mirror_label = None
        via_fallback = False

        try:
            status_code, body, resp_headers, transport = _fetch_portal_response(portal_url, timeout=10)
            cf_mitigated = resp_headers.get("cf-mitigated", "").lower()
            is_cloudflare = status_code == 403 and (
                cf_mitigated == "challenge"
                or "cloudflare" in str(resp_headers).lower()
                or "just a moment" in body.lower()
            )
            if status_code == 403 and is_cloudflare:
                primary_blocked_cf = True
                primary_http_status = 403
                primary_error_msg = "Protected by Cloudflare challenge (HTTP 403)."
            elif status_code != 200:
                primary_http_status = status_code
                primary_error_msg = f"Portal returned HTTP {status_code}."
        except urllib.error.HTTPError as error:
            cf_mitigated = error.headers.get("cf-mitigated", "").lower() if error.headers else ""
            primary_blocked_cf = error.code == 403 and (
                cf_mitigated == "challenge" or "cloudflare" in str(error.headers).lower()
            )
            primary_http_status = error.code
            primary_error_msg = (
                "Protected by Cloudflare challenge (HTTP 403)."
                if primary_blocked_cf
                else f"Portal returned HTTP {error.code}."
            )
        except Exception as error:
            primary_error_msg = str(error)

        if primary_error_msg is not None and allow_mirror_fallback and category in PARLZIM_FALLBACK_MIRRORS:
            mirror_name, mirror_url = PARLZIM_FALLBACK_MIRRORS[category]
            try:
                m_status, m_body, m_headers, m_transport = _fetch_portal_response(mirror_url, timeout=10)
                if m_status == 200 and m_body:
                    status_code, body, resp_headers, transport = m_status, m_body, m_headers, m_transport
                    selected_url = mirror_url
                    mirror_label = mirror_name
                    via_fallback = True
                    primary_error_msg = None
            except Exception:
                pass

        if primary_error_msg is not None:
            if primary_blocked_cf:
                blocked_count += 1
            sources_status.append({
                "category": category,
                "url": portal_url,
                "status": "blocked_by_cloudflare" if primary_blocked_cf else "unavailable",
                "httpStatus": primary_http_status,
                "score": None,
                "message": primary_error_msg,
            })
            continue

        def _parse_body_for_category(raw_body, source_url, source_headers):
            trimmed = (raw_body or "").lstrip()
            if trimmed.startswith("[") or trimmed.startswith("{"):
                wp_topics, wp_pdfs, wp_text = _extract_wp_json_topics_and_pdfs(raw_body, category, source_url, limit=4)
                merged, final_txt, p_count = _ingest_pdf_links_for_category(wp_pdfs, category, wp_topics, wp_text)
                return merged, final_txt, p_count
            if trimmed.startswith("<?xml") or "<rss" in trimmed[:300].lower():
                rss_topics, rss_txt = _extract_rss_topics(raw_body, category, source_url)
                return rss_topics, rss_txt, 0
            s_text = _strip_html(raw_body)
            html_topics = extract_legislative_topics(raw_body, category, source_url)
            if status_code == 200 and PdfReader is not None and not _is_pdf_payload(source_url, source_headers, None):
                links = extract_pdf_links(raw_body, source_url, limit=4)
                merged, final_txt, p_count = _ingest_pdf_links_for_category(links, category, html_topics, s_text)
                return merged, final_txt, p_count
            return html_topics, s_text, 0

        topics, stripped_text, pdf_count = _parse_body_for_category(body, selected_url, resp_headers)

        # If ParlZim or e-portal returned an HTTP 200 SPA/nav shell with 0 specific items, probe its subroutes first
        if not topics and not via_fallback and status_code == 200:
            for sub_url in _discover_portal_subroutes(category, portal_url, body):
                try:
                    sub_status, sub_body, sub_headers, sub_transport = _fetch_portal_response(sub_url, timeout=10)
                    if sub_status == 200 and sub_body:
                        sub_topics, sub_text, sub_pdfs = _parse_body_for_category(sub_body, sub_url, sub_headers)
                        if sub_topics:
                            topics, stripped_text, pdf_count = sub_topics, f"{stripped_text} {sub_text}".strip(), sub_pdfs
                            selected_url = sub_url
                            transport = sub_transport
                            break
                except Exception:
                    continue

        # Also trigger CF-free mirror/OpenParly archive supplement if portal index exposed <2 bills/briefs/Hansards
        if allow_mirror_fallback and (len(topics) < 2 or (pdf_count == 0 and category in OPENPARLY_SUPPLEMENT_QUERIES)) and (not via_fallback or category in OPENPARLY_SUPPLEMENT_QUERIES):
            supplement_urls = list(OPENPARLY_SUPPLEMENT_QUERIES.get(category, ()))
            if not via_fallback and category in PARLZIM_FALLBACK_MIRRORS:
                m_name, m_url = PARLZIM_FALLBACK_MIRRORS[category]
                if m_url not in supplement_urls:
                    if category in OPENPARLY_SUPPLEMENT_QUERIES:
                        supplement_urls.append(m_url)
                    else:
                        supplement_urls.insert(0, m_url)
                mirror_label = mirror_label or m_name
            for sup_url in supplement_urls:
                if len(topics) >= 5 and (pdf_count > 0 or category not in OPENPARLY_SUPPLEMENT_QUERIES):
                    break
                if len(topics) >= 6:
                    break
                try:
                    s_status, s_body, s_headers, s_transport = _fetch_portal_response(sup_url, timeout=10)
                    if s_status == 200 and s_body:
                        sup_topics, sup_text, sup_pdfs = _parse_body_for_category(s_body, sup_url, s_headers)
                        if sup_topics:
                            seen_urls = {t.get("url") for t in topics}
                            per_src_cap = 2 if ("zimlii.org" in sup_url and category in OPENPARLY_SUPPLEMENT_QUERIES) else 4
                            added = 0
                            for item in sup_topics:
                                if added >= per_src_cap:
                                    break
                                if item.get("url") not in seen_urls:
                                    topics.append(item)
                                    seen_urls.add(item.get("url"))
                                    added += 1
                            stripped_text = f"{stripped_text} {sup_text}".strip()
                            pdf_count += sup_pdfs
                            via_fallback = True
                            if selected_url == portal_url:
                                selected_url = sup_url
                            mirror_label = mirror_label or PARLZIM_FALLBACK_MIRRORS.get(category, ("OpenParly Archive", sup_url))[0]
                except Exception:
                    continue

        if status_code != 200 or len(stripped_text) < 80:
            sources_status.append({
                "category": category,
                "url": selected_url,
                "status": "unavailable",
                "httpStatus": status_code,
                "score": None,
                "transport": transport,
                "message": (
                    f"Portal returned HTTP {status_code}."
                    if status_code != 200
                    else "Portal returned insufficient content."
                ),
            })
            continue

        cat_score = score_hansard_text(stripped_text)
        if cat_score is None:
            sources_status.append({
                "category": category,
                "url": selected_url,
                "status": "unavailable",
                "httpStatus": status_code,
                "score": None,
                "transport": transport,
                "message": "Portal contained no indexable legislative tokens.",
            })
            continue

        total_chars += len(stripped_text)
        scores.append(cat_score)
        tracked_topics.extend(topics[:4])
        entry_status = {
            "category": category,
            "url": selected_url,
            "status": "available",
            "httpStatus": status_code,
            "score": cat_score,
            "charCount": len(stripped_text),
            "topicCount": len(topics[:4]),
            "pdfCount": pdf_count,
            "transport": transport,
        }
        if via_fallback:
            entry_status["viaFallbackMirror"] = True
            entry_status["mirrorLabel"] = mirror_label
            entry_status["primaryUrl"] = portal_url
            entry_status["primaryStatus"] = primary_http_status or status_code
            entry_status["primaryBlockedByCloudflare"] = primary_blocked_cf
        sources_status.append(entry_status)

    total_sources = len(sources_status)
    accessible_sources = len(scores)
    if accessible_sources > 0:
        avg_score = round(sum(scores) / accessible_sources, 2)
        hansard_ok = any(s["category"] == "Hansards" and s["status"] == "available" for s in sources_status)
        ranked_topics = _enrich_and_rank_topics(tracked_topics)[:25]
        sources_with_topics = _attach_topics_to_sources(sources_status, ranked_topics)
        result = {
            "score": avg_score,
            "status": "available",
            "source": "parlzim_hansards" if hansard_ok else "parlzim_portals",
            "httpStatus": 200,
            "charCount": total_chars,
            "accessibleSources": accessible_sources,
            "totalSources": total_sources,
            "sources": sources_with_topics,
            "tracked_topics": ranked_topics,
            "summary_briefing": _build_summary_briefing(
                sources_with_topics,
                ranked_topics,
                avg_score=avg_score,
                accessible_sources=accessible_sources,
                total_sources=total_sources,
                status="available",
            ),
        }
        HANSARD_CACHE["data"] = result
        HANSARD_CACHE["expires_at"] = now + HANSARD_TTL_SECONDS
        return result

    cached_snapshot = _load_verified_telemetry_cache()
    if cached_snapshot is not None:
        HANSARD_CACHE["data"] = cached_snapshot
        HANSARD_CACHE["expires_at"] = now + HANSARD_ERROR_TTL_SECONDS
        return cached_snapshot

    all_cf = blocked_count > 0
    unavailable_status = "blocked_by_cloudflare" if all_cf else "unavailable"
    result = {
        "score": None,
        "status": unavailable_status,
        "source": "unavailable",
        "httpStatus": 403 if all_cf else None,
        "accessibleSources": 0,
        "totalSources": total_sources,
        "sources": sources_status,
        "tracked_topics": [],
        "summary_briefing": _build_summary_briefing(
            sources_status,
            [],
            avg_score=None,
            accessible_sources=0,
            total_sources=total_sources,
            status=unavailable_status,
        ),
        "message": (
            f"All {blocked_count}/{total_sources} Parliament portals are currently protected by a Cloudflare challenge (HTTP 403)."
            if all_cf
            else "Parliamentary & Policy portals are currently unreachable."
        ),
    }
    HANSARD_CACHE["data"] = result
    HANSARD_CACHE["expires_at"] = now + HANSARD_ERROR_TTL_SECONDS
    return result


def _is_fresh_timestamp(ts_value, max_age_seconds=HANSARD_TTL_SECONDS):
    if not isinstance(ts_value, str) or not ts_value:
        return False
    try:
        parsed = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        return -300 <= age <= max_age_seconds
    except Exception:
        return False


def _attach_topics_to_sources(sources, ranked_topics):
    if not isinstance(sources, list):
        return []
    grouped = {}
    for item in ranked_topics or []:
        cat = str(item.get("category") or "").strip().lower()
        grouped.setdefault(cat, []).append(item.get("topic") or "")
    hydrated_sources = []
    for src in sources:
        if not isinstance(src, dict):
            continue
        cat_key = str(src.get("category") or "").strip().lower()
        names = [n for n in grouped.get(cat_key, []) if n]
        copy = dict(src)
        copy["topics"] = names[:4]
        copy["topicCount"] = len(names)
        hydrated_sources.append(copy)
    return hydrated_sources


def _build_summary_briefing(
    sources,
    ranked_topics,
    avg_score=None,
    accessible_sources=None,
    total_sources=None,
    status="available",
    captured_at=None,
):
    sources_list = [s for s in (sources or []) if isinstance(s, dict)]
    topics_list = [t for t in (ranked_topics or []) if isinstance(t, dict)]
    total = total_sources if isinstance(total_sources, int) and total_sources > 0 else (len(sources_list) or 5)
    accessible = (
        accessible_sources
        if isinstance(accessible_sources, int)
        else sum(1 for s in sources_list if s.get("status") == "available")
    )

    scored_portals = [
        s for s in sources_list
        if s.get("status") == "available"
        and isinstance(s.get("score"), (int, float))
        and not isinstance(s.get("score"), bool)
    ]
    highest_portal = max(scored_portals, key=lambda s: s["score"], default=None)
    top_issue = topics_list[0] if topics_list else None
    top_friction = top_issue.get("friction") if top_issue else None

    if isinstance(avg_score, (int, float)) and not isinstance(avg_score, bool) and math.isfinite(avg_score):
        risk_posture = "Elevated" if (avg_score >= 50 or (isinstance(top_friction, (int, float)) and top_friction >= 50)) else "Moderate"
    elif topics_list:
        risk_posture = "Elevated" if isinstance(top_friction, (int, float)) and top_friction >= 50 else "Moderate"
    else:
        risk_posture = "Unavailable"

    dates = sorted({str(t.get("submission_date") or "").strip() for t in topics_list if str(t.get("submission_date") or "").strip()})
    if len(dates) == 1:
        date_window = dates[0]
    elif len(dates) > 1:
        date_window = f"{dates[0]} to {dates[-1]}"
    else:
        date_window = None

    active_categories = []
    for t in topics_list:
        cat = str(t.get("category") or "").strip()
        if cat and cat not in active_categories:
            active_categories.append(cat)

    coverage_gaps = [
        str(s.get("category"))
        for s in sources_list
        if s.get("status") == "available" and not s.get("topicCount") and s.get("category")
    ]

    sponsors = []
    for t in topics_list:
        person = str(t.get("responsible_person") or t.get("responsible") or "").strip()
        if person and person not in ("Not stated in portal index", "Not stated in PDF") and person not in sponsors:
            sponsors.append(person)

    if accessible > 0:
        avg_text = f"{avg_score:.1f} / 100" if isinstance(avg_score, (int, float)) and math.isfinite(avg_score) else "--"
        if top_issue:
            headline = f"{accessible}/{total} portals live (Avg Fparl {avg_text}) · Lead issue: {top_issue.get('topic')} ({float(top_issue.get('friction') or 0):.1f} / 100)"
        else:
            headline = f"{accessible}/{total} portals scanned live (Avg Fparl {avg_text}) · No bill or PDF links exposed in current index"

        parts = [
            f"Semantic TF-IDF telemetry across {accessible} of {total} Parliament of Zimbabwe portals records a composite friction score of {avg_text} ({risk_posture} posture)"
            + (
                f", highest on {highest_portal.get('category')} ({float(highest_portal.get('score')):.1f} / 100)."
                if highest_portal
                else "."
            )
        ]
        if topics_list:
            cat_summary = ", ".join(active_categories) if active_categories else "active portals"
            count_word = "submission" if len(topics_list) == 1 else "submissions"
            date_phrase = f" spanning {date_window}" if date_window else ""
            parts.append(
                f"{len(topics_list)} ranked {count_word} extracted from {cat_summary}{date_phrase}, led by #{top_issue.get('rank', 1)} {top_issue.get('topic')} ({float(top_issue.get('friction') or 0):.1f} / 100)."
            )
            if sponsors:
                parts.append(f"Identified sponsoring authorities: {', '.join(sponsors[:4])}.")
            else:
                parts.append("Portal index records omit individual MP or committee sponsor attribution.")
        else:
            parts.append("Portal HTML indexes responded HTTP 200 without exposing downloadable bill digests or PDF attachments on this crawl.")
        if coverage_gaps:
            parts.append(f"Index-only portals with no bill or PDF links in this snapshot: {', '.join(coverage_gaps)}.")
        executive_summary = " ".join(parts)
    elif status == "blocked_by_cloudflare":
        headline = f"0/{total} portals accessible — Cloudflare HTTP 403 challenge active"
        executive_summary = f"All {total} Parliament of Zimbabwe portals returned Cloudflare HTTP 403 challenges on this poll; no synthetic briefing items are generated."
    else:
        headline = f"0/{total} portals reachable — awaiting repository poll"
        executive_summary = "Parliament of Zimbabwe portals are currently unreachable; the summary briefing will populate once HTTP 200 HTML or PDF feeds are ingested."

    full_pdf_count = sum(1 for t in topics_list if t.get("full_content"))
    total_pages = sum(int(t.get("page_count") or 0) for t in topics_list if isinstance(t.get("page_count"), int))

    key_findings = []
    for idx, entry in enumerate(topics_list[:4]):
        raw_summary = " ".join(str(entry.get("summary") or entry.get("content_excerpt") or "").split())
        takeaway = raw_summary[:357].rstrip() + "..." if len(raw_summary) > 360 else raw_summary
        key_findings.append({
            "rank": entry.get("rank") or (idx + 1),
            "category": entry.get("category") or "Parliament",
            "topic": entry.get("topic") or "Parliamentary record",
            "friction": entry.get("friction"),
            "submission_date": entry.get("submission_date"),
            "responsible_person": entry.get("responsible_person") or entry.get("responsible") or "Not stated in portal index",
            "page_count": entry.get("page_count"),
            "pdf_ingested": bool(entry.get("full_content")),
            "takeaway": takeaway,
        })

    return {
        "headline": headline,
        "executive_summary": executive_summary,
        "risk_posture": risk_posture,
        "date_window": date_window,
        "issue_count": len(topics_list),
        "full_pdf_count": full_pdf_count,
        "total_pages": total_pages,
        "accessible_portals": accessible,
        "total_portals": total,
        "coverage_gaps": coverage_gaps,
        "key_findings": key_findings,
        "captured_at": captured_at,
    }


def _load_verified_telemetry_cache(allow_fresh_blocked=False):
    """Return a pre-crawled ParlZim snapshot from telemetry_cache.json when available, or recent blocked metadata if allowed."""
    cache_path = os.environ.get("TELEMETRY_CACHE_PATH", TELEMETRY_CACHE_PATH)
    if not cache_path or not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    for key in ("parlzim", "last_available_parlzim"):
        snapshot = raw.get(key)
        if not isinstance(snapshot, dict):
            continue
        score = snapshot.get("score")
        if (
            snapshot.get("status") == "available"
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and math.isfinite(score)
        ):
            hydrated = dict(snapshot)
            ranked = _enrich_and_rank_topics(hydrated.get("tracked_topics") or [])[:20]
            hydrated["tracked_topics"] = ranked
            hydrated["sources"] = _attach_topics_to_sources(hydrated.get("sources") or [], ranked)
            hydrated["fromCache"] = True
            hydrated["cacheUpdatedAt"] = raw.get("updated_at") or raw.get("timestamp") or snapshot.get("captured_at")
            hydrated["summary_briefing"] = _build_summary_briefing(
                hydrated["sources"],
                ranked,
                avg_score=round(float(score), 2),
                accessible_sources=hydrated.get("accessibleSources"),
                total_sources=hydrated.get("totalSources"),
                status="available",
                captured_at=hydrated["cacheUpdatedAt"],
            )
            return hydrated

    flat_accessible = raw.get("accessible_sources")
    flat_score = raw.get("hansard_friction")
    if (
        isinstance(flat_accessible, int)
        and flat_accessible > 0
        and isinstance(flat_score, (int, float))
        and not isinstance(flat_score, bool)
        and math.isfinite(flat_score)
    ):
        topics = _enrich_and_rank_topics(raw.get("tracked_topics") if isinstance(raw.get("tracked_topics"), list) else [])[:20]
        captured_at = raw.get("timestamp") or raw.get("updated_at")
        total_src = raw.get("total_sources", 5)
        avg_val = round(float(flat_score), 2)
        return {
            "score": avg_val,
            "status": "available",
            "source": "parlzim_portals",
            "httpStatus": 200,
            "accessibleSources": flat_accessible,
            "totalSources": total_src,
            "sources": [],
            "tracked_topics": topics,
            "fromCache": True,
            "cacheUpdatedAt": captured_at,
            "summary_briefing": _build_summary_briefing(
                [],
                topics,
                avg_score=avg_val,
                accessible_sources=flat_accessible,
                total_sources=total_src,
                status="available",
                captured_at=captured_at,
            ),
        }

    if allow_fresh_blocked and _is_fresh_timestamp(raw.get("timestamp") or raw.get("updated_at")):
        parlzim = raw.get("parlzim")
        if isinstance(parlzim, dict) and parlzim.get("status") in ("blocked_by_cloudflare", "unavailable"):
            hydrated = dict(parlzim)
            hydrated["fromCache"] = True
            hydrated["cacheUpdatedAt"] = raw.get("timestamp") or raw.get("updated_at")
            return hydrated
        if isinstance(flat_accessible, int) and flat_accessible == 0:
            return {
                "score": None,
                "status": "blocked_by_cloudflare",
                "source": "unavailable",
                "httpStatus": 403,
                "accessibleSources": 0,
                "totalSources": raw.get("total_sources", 5),
                "sources": [],
                "tracked_topics": [],
                "fromCache": True,
                "cacheUpdatedAt": raw.get("timestamp") or raw.get("updated_at"),
                "message": "Cached crawl recorded 0/5 accessible Parliament portals (Cloudflare HTTP 403).",
            }
    return None


def load_telemetry_cache():
    """Return (hansard_friction, tracked_topics, accessible_sources) from telemetry_cache.json without fabricating placeholder bills."""
    snapshot = _load_verified_telemetry_cache(allow_fresh_blocked=True)
    if not isinstance(snapshot, dict):
        return None, [], 0
    return (
        snapshot.get("score"),
        list(snapshot.get("tracked_topics") or []),
        int(snapshot.get("accessibleSources") or 0),
    )


def fetch_semantic_hansard_telemetry(use_cache=True):
    """Alias wrapper delegating to the 5-portal Parliamentary & Policy Tracker."""
    return fetch_parliamentary_policy_tracker(use_cache=use_cache)


def compute_fragility_state_index(phi, markov_crisis_prob, macro_volatility, hansard_friction=None):
    """Compute FSI from normalized 0–100 inputs (3-factor baseline or 4-factor with Hansard)."""
    checks = [
        ("phi", phi),
        ("markov_crisis_prob", markov_crisis_prob),
        ("macro_volatility", macro_volatility),
    ]
    if hansard_friction is not None:
        checks.append(("hansard_friction", hansard_friction))
    for name, value in checks:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            raise ValueError(f"{name} must be a finite value between 0 and 100.")
    if hansard_friction is not None:
        return round(
            0.35 * (100.0 - phi)
            + 0.30 * markov_crisis_prob
            + 0.20 * macro_volatility
            + 0.15 * hansard_friction,
            2,
        )
    return round(
        0.40 * (100.0 - phi)
        + 0.35 * markov_crisis_prob
        + 0.25 * macro_volatility,
        2,
    )


def compute_macro_stress_proxy(layer2_macro):
    """Scale World Bank indicators to an experimental 0–100 macro-stress proxy."""
    if not isinstance(layer2_macro, dict) or layer2_macro.get("source") != "world_bank_v2":
        return None

    try:
        growth = float(layer2_macro["GDP_Growth"])
        inflation = float(layer2_macro["Inflation"])
        debt_gni = float(layer2_macro["Debt_GNI"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (growth, inflation, debt_gni)):
        return None

    inflation_stress = min(100.0, max(0.0, inflation / 2.0))
    debt_stress = min(100.0, max(0.0, debt_gni))
    growth_stress = min(100.0, max(0.0, (10.0 - growth) * 5.0))
    return round(
        0.50 * inflation_stress
        + 0.30 * debt_stress
        + 0.20 * growth_stress,
        2,
    )


def classify_fragility_state(fsi):
    if fsi <= 25:
        return "Stable Consolidation"
    if fsi <= 50:
        return "Latent Friction"
    if fsi <= 75:
        return "Accelerated Degradation"
    return "Acute Systemic Crisis"


def derive_social_metrics(payload):
    """Derive sampled-post volume and hashtag-mention activity from social telemetry."""
    if not payload.get("available") or payload.get("sampleType") == "rss-sheet":
        return None

    social_volume = payload.get("scannedPosts")
    if (
        isinstance(social_volume, bool)
        or not isinstance(social_volume, (int, float))
        or not math.isfinite(social_volume)
        or social_volume < 0
    ):
        raise ValueError("Social telemetry must provide a non-negative scannedPosts value.")

    hashtags = payload.get("hashtags")
    if not isinstance(hashtags, list):
        raise ValueError("Social telemetry hashtags must be a list.")
    engagement_score_proxy = 0
    for hashtag in hashtags:
        if not isinstance(hashtag, dict):
            raise ValueError("Social telemetry contains a malformed hashtag record.")
        mentions = hashtag.get("latestMentions", hashtag.get("mentions", 0))
        if (
            isinstance(mentions, bool)
            or not isinstance(mentions, (int, float))
            or not math.isfinite(mentions)
            or mentions < 0
        ):
            raise ValueError("Hashtag mention counts must be non-negative finite numbers.")
        engagement_score_proxy += mentions
    return social_volume, engagement_score_proxy


def _state_for_phi(phi):
    if phi > 60:
        return "Stable Consolidation"
    if phi > 35:
        return "Latent Friction"
    if phi > 20:
        return "Accelerated Degradation"
    return "Acute Systemic Crisis"


def update_telemetry_timeline(payload, evaluated_at=None, layer2_macro=None, hansard_telemetry=None):
    """Update today's entry from one day's baseline and the latest social sample."""
    global LATEST_DUAL_ENGINE_INPUTS, LATEST_FSI_INPUTS, LATEST_HANSARD_STATUS, TELEMETRY_TIMELINE
    global TIMELINE_BASELINE, TIMELINE_BASELINE_DATE

    metrics = derive_social_metrics(payload)
    if metrics is None:
        return

    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    today = evaluated_at.astimezone(timezone.utc).date().isoformat()

    if TIMELINE_BASELINE_DATE != today:
        baseline_index = -2 if TELEMETRY_TIMELINE[-1]["date"] == today and len(TELEMETRY_TIMELINE) > 1 else -1
        baseline = TELEMETRY_TIMELINE[baseline_index]
        TIMELINE_BASELINE = {
            "phi": baseline["phi"],
            "markov_crisis_prob": baseline["markov_crisis_prob"],
        }
        TIMELINE_BASELINE_DATE = today

    prior = TIMELINE_BASELINE
    if prior is None:
        raise RuntimeError("The daily Markov/Bayesian baseline was not initialized.")
    social_volume, engagement_score_proxy = metrics
    current_phi = compute_bayesian_posterior(
        prior["phi"], social_volume, engagement_score_proxy
    )
    projected_crisis_prob = compute_markov_path_projection(
        prior["markov_crisis_prob"]
    )
    macro_stress_proxy = compute_macro_stress_proxy(layer2_macro)
    hansard_score = (
        hansard_telemetry.get("score")
        if isinstance(hansard_telemetry, dict)
        and hansard_telemetry.get("source") in ("parlzim_hansards", "parlzim_portals")
        else None
    )
    entry = {
        "date": today,
        "phi": current_phi,
        "markov_crisis_prob": projected_crisis_prob,
        "state": _state_for_phi(current_phi),
        "social_volume": social_volume,
        "engagement_score_proxy": engagement_score_proxy,
        "telemetry_source": payload.get("source", "social telemetry"),
        "updated_at": evaluated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if hansard_score is not None:
        entry["hansard_friction"] = hansard_score
    if isinstance(hansard_telemetry, dict) and hansard_telemetry.get("tracked_topics"):
        entry["tracked_topics"] = list(hansard_telemetry["tracked_topics"])
    LATEST_HANSARD_STATUS = (
        dict(hansard_telemetry)
        if isinstance(hansard_telemetry, dict)
        else {"score": None, "status": "unavailable", "source": "unavailable"}
    )

    if macro_stress_proxy is not None:
        entry["macro_volatility_proxy"] = macro_stress_proxy
        entry["fsi"] = compute_fragility_state_index(
            current_phi, projected_crisis_prob, macro_stress_proxy, hansard_friction=hansard_score
        )
        entry["warning_level"] = classify_fragility_state(entry["fsi"])
        LATEST_FSI_INPUTS = {
            "status": "available",
            "macro_stress_proxy": macro_stress_proxy,
            "macro_source": layer2_macro["source"],
            "hansard_included": hansard_score is not None,
            "updated_at": entry["updated_at"],
        }
    else:
        LATEST_FSI_INPUTS = {
            "status": "awaiting_sourced_macro_data",
            "macro_stress_proxy": None,
            "macro_source": layer2_macro.get("source") if isinstance(layer2_macro, dict) else None,
            "hansard_included": False,
            "updated_at": entry["updated_at"],
        }

    if TELEMETRY_TIMELINE[-1]["date"] == today:
        TELEMETRY_TIMELINE[-1] = entry
    else:
        TELEMETRY_TIMELINE.append(entry)
        if len(TELEMETRY_TIMELINE) > TIMELINE_WINDOW_DAYS:
            TELEMETRY_TIMELINE.pop(0)
    LATEST_DUAL_ENGINE_INPUTS = {
        "social_volume": social_volume,
        "engagement_score_proxy": engagement_score_proxy,
        "telemetry_source": entry["telemetry_source"],
        "updated_at": entry["updated_at"],
    }


def get_dual_engine_timeline():
    hansard_status = (
        dict(LATEST_HANSARD_STATUS)
        if LATEST_HANSARD_STATUS
        else {"score": None, "status": "awaiting_check", "source": "unavailable"}
    )
    return {
        "timeline": [dict(entry) for entry in TELEMETRY_TIMELINE],
        "engines": {
            "bayesian_status": "Active (sampled-post and hashtag-mention proxies)",
            "markov_status": "Active (three-state transition matrix)",
            "fsi_status": (
                "Active (World Bank macro-stress proxy)"
                if LATEST_FSI_INPUTS and LATEST_FSI_INPUTS["status"] == "available"
                else "Awaiting sourced World Bank macro data"
            ),
            "hansard_status": (
                f"Active ({hansard_status.get('accessibleSources', 1)}/{hansard_status.get('totalSources', 5)} ParlZim portals · score {hansard_status['score']})"
                if hansard_status.get("status") == "available"
                else hansard_status.get("message") or "Awaiting Parliament portal access"
            ),
        },
        "inputStatus": "updated" if LATEST_DUAL_ENGINE_INPUTS else "awaiting_social_sample",
        "latestInputs": dict(LATEST_DUAL_ENGINE_INPUTS) if LATEST_DUAL_ENGINE_INPUTS else None,
        "fsiStatus": (
            dict(LATEST_FSI_INPUTS)
            if LATEST_FSI_INPUTS
            else {"status": "awaiting_sourced_macro_data", "macro_stress_proxy": None}
        ),
        "hansardStatus": hansard_status,
        "historyNote": (
            "Seed timeline values are illustrative. Live FSI uses 40% inverse Φ, 35% "
            "Markov crisis projection, and 25% macro-stress proxy (or 35%/30%/20%/15% when "
            "live ParlZim Semantic Hansard Friction is reachable). Macro stress scaling and "
            "TF-IDF cosine weighting are experimental assumptions."
        ),
    }


def fetch_layer2_macro_telemetry(use_cache=True):
    """Fetch Layer 2 macroeconomic indicators for Zimbabwe (ZWE) with baseline fallback."""
    now = time.monotonic()
    if use_cache and LAYER2_MACRO_CACHE["data"] is not None and LAYER2_MACRO_CACHE["expires_at"] > now:
        return LAYER2_MACRO_CACHE["data"]

    indicators = {
        "GDP_Growth": "NY.GDP.MKTP.KD.ZG",
        "Inflation": "FP.CPI.TOTL.ZG",
        "Debt_GNI": "DT.DOD.DECT.GN.ZS",
    }
    fallback_values = {"GDP_Growth": 8.3, "Inflation": 5.2, "Debt_GNI": 37.9}
    layer2_telemetry = {}
    used_fallback = False

    for key, ind_code in indicators.items():
        url = f"https://api.worldbank.org/v2/country/ZWE/indicator/{ind_code}?format=json&mrv=1"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KUVHURA-Observatory/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            if isinstance(response_data, list) and len(response_data) > 1 and response_data[1]:
                latest_val = response_data[1][0].get("value")
                if latest_val is not None:
                    layer2_telemetry[key] = float(latest_val)
                    continue
            layer2_telemetry[key] = fallback_values[key]
            used_fallback = True
        except Exception as error:
            print(f"Warning: Could not fetch Layer 2 indicator {key}: {error}")
            layer2_telemetry[key] = fallback_values[key]
            used_fallback = True

    layer2_telemetry["source"] = "fallback_baseline" if used_fallback else "world_bank_v2"
    print("Layer 2 Macro Telemetry Synchronized:", layer2_telemetry)
    LAYER2_MACRO_CACHE["data"] = layer2_telemetry
    LAYER2_MACRO_CACHE["expires_at"] = now + (300 if used_fallback else LAYER2_MACRO_TTL_SECONDS)
    return layer2_telemetry


async def register(websocket):
    CONNECTED_CLIENTS.add(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client connected ({len(CONNECTED_CLIENTS)} total)")
    if LATEST_TRENDS is not None:
        await websocket.send_json(LATEST_TRENDS)
    else:
        await websocket.send_json({
            "type": "stream_status",
            "status": "loading",
            "message": "Waiting for the first Zimbabwe trending telemetry snapshot.",
        })


async def unregister(websocket):
    CONNECTED_CLIENTS.discard(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client disconnected ({len(CONNECTED_CLIENTS)} remaining)")


def fetch_trending_telemetry():
    payload = fetch_social_hashtag_trends()
    if not isinstance(payload, dict) or not isinstance(payload.get("hashtags"), list):
        raise ValueError("Social telemetry endpoint returned an unexpected response")

    layer2_macro = fetch_layer2_macro_telemetry()
    hansard_telemetry = fetch_semantic_hansard_telemetry()
    update_telemetry_timeline(payload, layer2_macro=layer2_macro, hansard_telemetry=hansard_telemetry)
    updated_at = payload.get("updatedAt") or datetime.now(timezone.utc).isoformat()
    orientation = evaluate_orientation(payload)
    state_classification = evaluate_state_classification(payload.get("orientationInputs"))
    return {
        "type": "trending_telemetry",
        "status": "available" if payload.get("available") else "no_sources",
        "updatedAt": updated_at,
        "telemetry": payload,
        "orientation": orientation,
        "stateClassification": state_classification,
        "layer2Macro": layer2_macro,
        "dualEngineTimeline": get_dual_engine_timeline(),
        **({"message": payload["message"]} if payload.get("message") else {}),
    }


async def broadcast(packet):
    for websocket in tuple(CONNECTED_CLIENTS):
        if websocket.closed:
            await unregister(websocket)
            continue
        try:
            await websocket.send_json(packet)
        except (ConnectionResetError, RuntimeError) as error:
            print(f"Telemetry delivery failed; removing disconnected client: {error}")
            await unregister(websocket)


async def refresh_trending_telemetry():
    global LATEST_TRENDS
    while True:
        try:
            LATEST_TRENDS = await asyncio.to_thread(fetch_trending_telemetry)
            print(
                f"Zimbabwe trending telemetry refreshed at "
                f"{LATEST_TRENDS['updatedAt']} ({LATEST_TRENDS['status']})"
            )
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            LATEST_TRENDS = {
                "type": "trending_telemetry",
                "status": "error",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "message": f"Zimbabwe trending telemetry could not be loaded: {error}",
                "telemetry": None,
                "orientation": evaluate_orientation({}),
                "stateClassification": evaluate_state_classification(None),
            }
            print(LATEST_TRENDS["message"])

        logger.info("orientation_evaluation %s", json.dumps(LATEST_TRENDS["orientation"], separators=(",", ":")))
        logger.info(
            "state_classification %s",
            json.dumps(LATEST_TRENDS["stateClassification"]["timelineLog"]
                       if LATEST_TRENDS["stateClassification"]["status"] == "evaluated"
                       else LATEST_TRENDS["stateClassification"], separators=(",", ":")),
        )
        await broadcast(LATEST_TRENDS)
        await asyncio.sleep(TREND_REFRESH_SECONDS)


async def health(_request):
    return web.Response(text="ok\n")


async def dual_engine_timeline(_request):
    return web.json_response(
        get_dual_engine_timeline(),
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def extraction_reports_stream(_request):
    cache_path = os.environ.get("TELEMETRY_CACHE_PATH", os.path.join(os.path.dirname(__file__), "telemetry_cache.json"))
    reports = []
    updated_at = None
    try:
        if os.path.isfile(cache_path):
            with open(cache_path, "r", encoding="utf-8") as handle:
                raw_cache = json.load(handle)
            if isinstance(raw_cache, dict):
                raw_reports = raw_cache.get("extraction_reports")
                if isinstance(raw_reports, list):
                    reports = raw_reports
                updated_at = raw_cache.get("extraction_reports_updated_at")
                if not updated_at and reports:
                    updated_at = reports[0].get("updated_at") if reports else None
    except Exception:
        reports = []
    
    response_text = "data: " + json.dumps({"reports": reports, "updatedAt": updated_at}) + "\n\n"
    return web.Response(
        text=response_text,
        content_type="text/event-stream",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


async def live_endpoint(request):
    websocket = web.WebSocketResponse()
    if not websocket.can_prepare(request).ok:
        return await health(request)

    await websocket.prepare(request)
    try:
        await register(websocket)
        async for _message in websocket:
            pass
    finally:
        await unregister(websocket)
    return websocket


def create_app():
    app = web.Application()
    app.router.add_get("/api/timeline", dual_engine_timeline)
    app.router.add_get("/api/extraction-reports/stream", extraction_reports_stream)
    app.router.add_route("*", "/", live_endpoint)
    app.router.add_route("*", "/health", health)
    return app


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = os.environ.get("STREAM_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("STREAM_PORT", "8765")))
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    trends_task = asyncio.create_task(refresh_trending_telemetry())
    try:
        print(f"KUVHURA telemetry and health server listening on {host}:{port}")
        await trends_task
    finally:
        trends_task.cancel()
        await asyncio.gather(trends_task, return_exceptions=True)
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForecast server stopped.")
