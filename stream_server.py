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
    web = None
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
    "Bill Digests": ("ZimLII Uncommenced Legislation", "https://zimlii.org/legislation/uncommenced"),
    "Enacted Acts": ("ZimLII Recent Legislation", "https://zimlii.org/legislation/recent"),
    "Policy Briefs": (
        "Parliament Oversight RSS (30d)",
        "https://news.google.com/rss/search?q=(Zimbabwe+Parliament+policy+OR+%22Public+Accounts%22+OR+%22Auditor+General%22)+when:30d&hl=en-ZW&gl=ZW&ceid=ZW:en",
    ),
    "Fact Sheets": ("ZimLII Subsidiary Legislation", "https://zimlii.org/legislation/subsidiary"),
    "Hansards": (
        "Parliament Debates RSS (30d)",
        "https://news.google.com/rss/search?q=%22Parliament+of+Zimbabwe%22+(bill+OR+budget+OR+committee+OR+amendment)+when:30d&hl=en-ZW&gl=ZW&ceid=ZW:en",
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
TELEMETRY_TIMELINE = [
    {"date": "2026-11-08", "phi": 39.50, "markov_crisis_prob": 22.0, "state": "Latent Friction"},
    {"date": "2026-11-09", "phi": 38.10, "markov_crisis_prob": 24.5, "state": "Latent Friction"},
    {"date": "2026-11-10", "phi": 36.80, "markov_crisis_prob": 27.0, "state": "Latent Friction"},
    {"date": "2026-11-11", "phi": 34.20, "markov_crisis_prob": 31.0, "state": "Accelerated Degradation"},
    {"date": "2026-11-12", "phi": 30.50, "markov_crisis_prob": 38.0, "state": "Accelerated Degradation"},
    {"date": "2026-11-13", "phi": 27.90, "markov_crisis_prob": 42.5, "state": "Acute Crisis"},
    {"date": "2026-11-14", "phi": 24.15, "markov_crisis_prob": 46.8, "state": "Acute Systemic Crisis"},
]
for _seed, _macro_proxy in zip(TELEMETRY_TIMELINE, (45.0, 48.0, 50.0, 55.0, 60.0, 62.0, 65.0)):
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
    title = " ".join(str(raw_title or "").split())
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
    iso_match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", value)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            return dt.date().isoformat()
    except Exception:
        pass
    dmy = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+(January|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})\b",
        value,
        re.IGNORECASE,
    )
    if dmy:
        day, month_name, year = int(dmy.group(1)), dmy.group(2).lower(), int(dmy.group(3))
        month = MONTH_NAME_MAP.get(month_name)
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    mdy = re.search(
        r"\b(January|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
        value,
        re.IGNORECASE,
    )
    if mdy:
        month_name, day, year = mdy.group(1).lower(), int(mdy.group(2)), int(mdy.group(3))
        month = MONTH_NAME_MAP.get(month_name)
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    my = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
        value,
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


def _extract_responsible_person(*texts, author="", source_name="", title=""):
    """Extract named sponsor, minister, committee, MP, or source desk strictly from real metadata/text."""
    raw_author = " ".join(str(author or "").split())
    if raw_author and "@" not in raw_author and len(raw_author) >= 3:
        return raw_author[:120]

    combined = " ".join(t for t in (title, *texts) if t)
    minister_match = re.search(
        r"\b(Minister of [A-Z][A-Za-z,&/\- ]{3,75}?)(?=\)|\]|;|\s+Notice\b|\s+Regulations\b|\s+Bill\b|\s+Act\b|,?\s+20\d{2}|$)",
        combined,
    )
    if minister_match:
        return " ".join(minister_match.group(1).split()).rstrip(".,;:- ")

    submit_match = re.search(
        r"\b(?:tabled by|submitted by|presented by|moved by|sponsored by|prepared by|authored by)\s+([A-Z][A-Za-z.'\- ]{2,65}?)(?=[;,\n]|(?:\.(?!\s*[A-Z]))|$)",
        combined,
        re.IGNORECASE,
    )
    if submit_match:
        return " ".join(submit_match.group(1).split()).rstrip(".,;:- ")

    hon_match = re.search(
        r"\b((?:Hon\.?|Honourable|Sen\.?|Senator)\s+[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3})\b",
        combined,
    )
    if hon_match:
        return " ".join(hon_match.group(1).split())

    committee_match = re.search(
        r"\b((?:(?:[Pp]arliamentary|[Jj]oint|[Ss]tanding|[Pp]ortfolio|[Tt]hematic|[Pp]ublic\s+[Aa]ccounts)\s+)*[Cc]ommittee(?:\s+[Oo]n\s+[A-Z][A-Za-z,&/\-]+(?:\s+(?:and|of|for|&|[A-Z][A-Za-z,&/\-]+)){0,5})?)\b",
        combined,
    )
    if committee_match:
        candidate_committee = " ".join(committee_match.group(1).split()).rstrip(".,;:- ")
        if candidate_committee.lower() != "committee":
            return candidate_committee

    institution_match = re.search(
        r"\b(Office of the Auditor[\s\-]General|Auditor[\s\-]General|Reserve Bank of Zimbabwe|Constitutional Court|ZIMRA|Parliament of Zimbabwe)\b",
        combined,
        re.IGNORECASE,
    )
    if institution_match:
        return " ".join(institution_match.group(1).split())

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
            "topic": title[:160],
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
            for key, alias in (("/Author", "author"), ("author", "author"), ("/CreationDate", "creation_date"), ("creation_date", "creation_date"), ("/ModDate", "mod_date"), ("mod_date", "mod_date")):
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


def extract_pdf_metadata_and_text(pdf_bytes, max_pages=None, pdf_url=""):
    """Extract complete page text, submission date, responsible body/person, and 1200-char summary from PDF bytes."""
    info, full_structured, flat_text, page_count = _read_pdf_info_and_text(pdf_bytes, max_pages=max_pages)
    if not flat_text:
        info_date = _parse_pdf_info_date(info.get("creation_date") or info.get("mod_date"))
        fallback_date = info_date or _extract_submission_date(url=pdf_url)
        return fallback_date, "Not stated in PDF", "", ""
    head_text = flat_text[:4000]
    submission_date = _extract_submission_date(head_text)
    if not submission_date:
        submission_date = _parse_pdf_info_date(info.get("creation_date") or info.get("mod_date"))
    if not submission_date:
        submission_date = _extract_submission_date(url=pdf_url)

    raw_pdf_author = info.get("author", "")
    if re.search(r"microsoft|adobe|libreoffice|writer|pypdf|unknown|admin|user", raw_pdf_author, re.IGNORECASE):
        raw_pdf_author = ""
    responsible_person = _extract_responsible_person(head_text)
    if responsible_person == "Not stated in portal index":
        responsible_person = raw_pdf_author[:120] if raw_pdf_author and "@" not in raw_pdf_author and len(raw_pdf_author) >= 3 else "Not stated in PDF"
    summary = flat_text[:1200].rstrip() + ("..." if len(flat_text) > 1200 else "")
    full_payload = full_structured[:60000] + ("\n\n[Truncated after 60,000 characters]" if len(full_structured) > 60000 else "")
    if page_count:
        info["page_count"] = page_count
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
            anchors = [(a.get("href", ""), a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)]
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


def fetch_pdf_document_metadata(pdf_url, timeout=12):
    """Download PDF binary and return (submission_date, responsible_person, summary, full_text) using pypdf."""
    if PdfReader is None or not pdf_url:
        return None, "Not stated in PDF", "", ""
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
        return extract_pdf_metadata_and_text(raw_bytes, max_pages=None, pdf_url=pdf_url)

    if os.environ.get("FLARESOLVERR_URL", FLARESOLVERR_URL).strip():
        solved = _fetch_via_flaresolverr(pdf_url, timeout=max(timeout, 20))
        if solved is not None:
            status_code, solved_body, _headers, _transport = solved
            if status_code == 200 and solved_body:
                solved_text = _strip_html(solved_body)
                return (
                    _extract_submission_date(solved_text[:2500], url=pdf_url),
                    _extract_responsible_person(solved_text[:2500]),
                    solved_text[:280],
                    solved_text,
                )
    return None, "Not stated in PDF", "", ""


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

        is_rss = body.lstrip().startswith("<?xml") or "<rss" in body[:300].lower()
        pdf_count = 0
        if is_rss:
            topics, rss_text = _extract_rss_topics(body, category, selected_url)
            stripped_text = rss_text
        else:
            stripped_text = _strip_html(body)
            topics = extract_legislative_topics(body, category, selected_url)
            if status_code == 200 and PdfReader is not None and not _is_pdf_payload(selected_url, resp_headers, None):
                pdf_links = extract_pdf_links(body, selected_url, limit=4)
                pdf_topics = []
                pdf_text_chunks = []
                for pdf_link in pdf_links:
                    pdf_date, pdf_person, raw_pdf_summary, pdf_text = fetch_pdf_document_metadata(
                        pdf_link["url"], timeout=12
                    )
                    if len(pdf_text) >= 80:
                        pdf_count += 1
                        flat_pdf_body = " ".join(re.sub(r"---\s*Page\s+\d+\s*---", " ", pdf_text).split())
                        pdf_score = score_hansard_text(flat_pdf_body)
                        pdf_text_chunks.append(flat_pdf_body)
                        if not pdf_date:
                            pdf_date = _extract_submission_date(pdf_link["title"], url=pdf_link["url"])
                        if not pdf_person or pdf_person in ("Not stated in PDF", "Not stated in portal index"):
                            pdf_person = _extract_responsible_person(pdf_link["title"], title=pdf_link["title"])
                        computed_summary, pdf_excerpt = _build_issue_summary_and_excerpt(
                            pdf_link["title"],
                            category,
                            "PDF Downloaded & Ingested",
                            raw_snippet=flat_pdf_body[:900],
                            url=pdf_link["url"],
                            submission_date=pdf_date,
                        )
                        page_markers = len(re.findall(r"---\s*Page\s+\d+\s*---", pdf_text))
                        topic_item = {
                            "topic": pdf_link["title"],
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
                    topics = pdf_topics + [t for t in topics if t.get("url") not in seen_pdf_urls]

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
        tracked_topics.extend(topics)
        entry_status = {
            "category": category,
            "url": selected_url,
            "status": "available",
            "httpStatus": status_code,
            "score": cat_score,
            "charCount": len(stripped_text),
            "topicCount": len(topics),
            "pdfCount": pdf_count,
            "transport": transport,
        }
        if via_fallback:
            entry_status["viaFallbackMirror"] = True
            entry_status["mirrorLabel"] = mirror_label
            entry_status["primaryUrl"] = portal_url
            entry_status["primaryStatus"] = primary_http_status
            entry_status["primaryBlockedByCloudflare"] = primary_blocked_cf
        sources_status.append(entry_status)

    total_sources = len(sources_status)
    accessible_sources = len(scores)
    if accessible_sources > 0:
        avg_score = round(sum(scores) / accessible_sources, 2)
        hansard_ok = any(s["category"] == "Hansards" and s["status"] == "available" for s in sources_status)
        result = {
            "score": avg_score,
            "status": "available",
            "source": "parlzim_hansards" if hansard_ok else "parlzim_portals",
            "httpStatus": 200,
            "charCount": total_chars,
            "accessibleSources": accessible_sources,
            "totalSources": total_sources,
            "sources": sources_status,
            "tracked_topics": _enrich_and_rank_topics(tracked_topics)[:20],
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
    result = {
        "score": None,
        "status": "blocked_by_cloudflare" if all_cf else "unavailable",
        "source": "unavailable",
        "httpStatus": 403 if all_cf else None,
        "accessibleSources": 0,
        "totalSources": total_sources,
        "sources": sources_status,
        "tracked_topics": [],
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
            hydrated["tracked_topics"] = _enrich_and_rank_topics(hydrated.get("tracked_topics") or [])[:20]
            hydrated["fromCache"] = True
            hydrated["cacheUpdatedAt"] = raw.get("updated_at") or raw.get("timestamp") or snapshot.get("captured_at")
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
        return {
            "score": round(float(flat_score), 2),
            "status": "available",
            "source": "parlzim_portals",
            "httpStatus": 200,
            "accessibleSources": flat_accessible,
            "totalSources": raw.get("total_sources", 5),
            "sources": [],
            "tracked_topics": topics,
            "fromCache": True,
            "cacheUpdatedAt": raw.get("timestamp") or raw.get("updated_at"),
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
        if len(TELEMETRY_TIMELINE) > 14:
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
