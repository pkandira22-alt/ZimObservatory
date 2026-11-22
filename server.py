#!/usr/bin/env python3
import html as html_lib
import json
import logging
import os
import re
import sqlite3
from http.client import HTTPException
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from threading import Lock
from datetime import datetime, timezone
try:
    from cgi import FieldStorage
except ModuleNotFoundError:  # Python 3.13+ removed cgi
    FieldStorage = None
import mimetypes
from email.parser import BytesParser
from email.policy import default

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
INDEX_PATH = os.path.join(BASE_DIR, "index.html")
ENV_PATH = os.path.join(BASE_DIR, ".env")
GEMINI_MODELS = ("gemini-3.8-flash", "gemini-3.1-flash-lite")
SOCIAL_CACHE = {"expires_at": 0, "payload": None}
SOCIAL_CACHE_LOCK = Lock()
YOUTUBE_CACHE = {"expires_at": 0, "result": None}
YOUTUBE_CACHE_TTL_SECONDS = 900
HASHTAG_PATTERN = re.compile(r"(?<![\w&])#(?:[A-Za-z][\w-]*|[0-9]+[A-Za-z][\w-]*)", re.UNICODE)
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def _is_placeholder_key(value):
    if not value:
        return True
    trimmed = value.strip()
    return (
        not trimmed
        or trimmed in ("MY_GEMINI_API_KEY", "your_gemini_api_key", "your_api_key_here")
        or "placeholder" in trimmed.lower()
        or trimmed.startswith("TODO")
    )


def get_gemini_api_key():
    if os.path.isfile(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        continue
                    k, v = stripped.split("=", 1)
                    if k.strip() in ("GEMINI_API_KEY", "GEMINIKEY"):
                        val = v.strip().strip('"').strip("'")
                        if not _is_placeholder_key(val):
                            return val
        except OSError:
            pass
    for env_name in ("GEMINI_API_KEY", "GEMINIKEY"):
        val = os.environ.get(env_name, "").strip()
        if not _is_placeholder_key(val):
            return val
    return None


def get_youtube_api_key():
    for env_name in ("YOUTUBE_API_KEY", "YOUTUBE_DATA_API_KEY"):
        val = os.environ.get(env_name, "").strip()
        if not _is_placeholder_key(val):
            return val
    if os.path.isfile(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        continue
                    k, v = stripped.split("=", 1)
                    if k.strip() in ("YOUTUBE_API_KEY", "YOUTUBE_DATA_API_KEY"):
                        val = v.strip().strip('"').strip("'")
                        if not _is_placeholder_key(val):
                            return val
        except OSError:
            pass
    return None


def check_gemini_status():
    api_key = get_gemini_api_key()
    if not api_key:
        return 200, {"configured": False, "available": False}
    req = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODELS[0]}",
        headers={"x-goog-api-key": api_key},
    )
    try:
        with urlopen(req, timeout=8) as response:
            if response.status == 200:
                return 200, {"configured": True, "available": True}
            return 502, {
                "configured": True,
                "available": False,
                "error": f"Gemini rejected the model availability check (HTTP {response.status}).",
            }
    except HTTPError as err:
        return 502, {
            "configured": True,
            "available": False,
            "error": f"Gemini rejected the model availability check (HTTP {err.code}).",
        }
    except (URLError, OSError, TimeoutError):
        return 502, {
            "configured": True,
            "available": False,
            "error": "Gemini could not be reached from the backend.",
        }


def query_gemini_model(prompt):
    api_key = get_gemini_api_key()
    if not api_key:
        return 503, {"error": "Gemini is not configured on this app host."}
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}]}).encode("utf-8")
    last_error = "Gemini could not complete the request."
    for model in GEMINI_MODELS:
        req = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=body,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
                parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                answer = "".join(part.get("text", "") for part in parts)
                if answer:
                    return 200, {"answer": answer, "model": model}
                last_error = "Gemini returned no response."
        except HTTPError as err:
            try:
                err_body = json.loads(err.read().decode("utf-8"))
                last_error = err_body.get("error", {}).get("message") or f"Gemini HTTP {err.code}"
            except Exception:
                last_error = f"Gemini HTTP {err.code}"
            if err.code in (429, 503) or err.code >= 500:
                continue
            return 502, {"error": last_error}
        except (URLError, OSError, TimeoutError, ValueError) as err:
            last_error = str(err)
    return 502, {"error": last_error}
SOCIAL_FEEDS = (
    (
        "Bluesky",
        "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=Zimbabwe&sort=latest&limit=100",
    ),
    (
        "Mastodon (mastodon.social)",
        "https://mastodon.social/api/v1/timelines/tag/Zimbabwe?limit=40",
    ),
    (
        "Mastodon (mastodon.online)",
        "https://mastodon.online/api/v1/timelines/tag/Zimbabwe?limit=40",
    ),
    (
        "Mastodon (mas.to)",
        "https://mas.to/api/v1/timelines/tag/Zimbabwe?limit=40",
    ),
)
LOGGER = logging.getLogger(__name__)


class _HTMLTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain_text(html):
    parser = _HTMLTextParser()
    parser.feed(html or "")
    return re.sub(r"\s+", " ", html_lib.unescape(" ".join(parser.parts))).strip()


def _sanitize_youtube_video_id(raw_id):
    value = str(raw_id or "").strip()
    return value if YOUTUBE_VIDEO_ID_PATTERN.match(value) else ""


def _parse_non_negative_int(value):
    try:
        num = int(value)
        return num if num >= 0 else 0
    except (TypeError, ValueError):
        return 0


def _redact_api_key(message):
    return re.sub(r"key=[^&\s]+", "key=[REDACTED]", str(message or ""), flags=re.IGNORECASE)


def _fetch_youtube_source(api_key, now_ts):
    if YOUTUBE_CACHE["result"] is not None and YOUTUBE_CACHE["expires_at"] > now_ts:
        return YOUTUBE_CACHE["result"]

    search_qs = urlencode({
        "part": "snippet",
        "type": "video",
        "order": "date",
        "maxResults": "50",
        "q": "Zimbabwe",
        "key": api_key,
    })
    search_url = f"https://www.googleapis.com/youtube/v3/search?{search_qs}"
    request = Request(
        search_url,
        headers={"Accept": "application/json", "User-Agent": "KUVHURA-Observatory/1.0"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        reason = ""
        try:
            err_body = json.loads(err.read().decode("utf-8"))
            reason = str(
                (err_body.get("error", {}).get("errors") or [{}])[0].get("reason")
                or err_body.get("error", {}).get("status")
                or ""
            ).strip()
        except Exception:
            reason = ""
        detail = f"{reason} (HTTP {err.code})" if reason else f"HTTP {err.code}"
        raise RuntimeError(f"YouTube Data API v3 error: {detail}") from None
    except Exception as exc:
        raise RuntimeError(_redact_api_key(exc)) from None

    search_items = payload.get("items") or []
    video_ids = []
    seen_ids = set()
    for item in search_items:
        vid = _sanitize_youtube_video_id((item.get("id") or {}).get("videoId"))
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            video_ids.append(vid)
    video_ids = video_ids[:50]

    details_by_id = {}
    if video_ids:
        try:
            details_qs = urlencode({
                "part": "snippet,statistics",
                "id": ",".join(video_ids),
                "key": api_key,
            })
            details_req = Request(
                f"https://www.googleapis.com/youtube/v3/videos?{details_qs}",
                headers={"Accept": "application/json", "User-Agent": "KUVHURA-Observatory/1.0"},
            )
            with urlopen(details_req, timeout=10) as d_resp:
                details_payload = json.loads(d_resp.read().decode("utf-8"))
                for d_item in details_payload.get("items") or []:
                    vid = _sanitize_youtube_video_id(d_item.get("id"))
                    if vid:
                        details_by_id[vid] = d_item
        except Exception:
            pass

    posts = []
    videos = []
    channels = set()
    total_views = 0
    total_likes = 0
    total_comments = 0
    for item in search_items:
        vid = _sanitize_youtube_video_id((item.get("id") or {}).get("videoId"))
        detail = details_by_id.get(vid) if vid else None
        snippet = (detail or {}).get("snippet") or item.get("snippet") or {}
        stats = (detail or {}).get("statistics") or {}
        title = re.sub(r"\s+", " ", html_lib.unescape(snippet.get("title") or "")).strip()
        description = re.sub(r"\s+", " ", html_lib.unescape(snippet.get("description") or "")).strip()
        channel = re.sub(r"\s+", " ", html_lib.unescape(snippet.get("channelTitle") or "")).strip()
        published_at = snippet.get("publishedAt") or (item.get("snippet") or {}).get("publishedAt")
        url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
        combined = f"{title} {description}".strip()
        views = _parse_non_negative_int(stats.get("viewCount"))
        likes = _parse_non_negative_int(stats.get("likeCount"))
        comments = _parse_non_negative_int(stats.get("commentCount"))
        total_views += views
        total_likes += likes
        total_comments += comments
        if channel:
            channels.add(channel)
        posts.append({
            "text": combined,
            "created_at": published_at,
            "url": url,
        })
        if vid and title:
            videos.append({
                "videoId": vid,
                "title": title,
                "channelTitle": channel or "YouTube Channel",
                "publishedAt": published_at,
                "url": url,
                "viewCount": views,
                "likeCount": likes,
                "commentCount": comments,
                "hashtags": list(dict.fromkeys(HASHTAG_PATTERN.findall(combined)))[:6],
            })

    videos.sort(
        key=lambda v: (
            v["viewCount"] + v["likeCount"] * 5 + v["commentCount"] * 10,
            v["publishedAt"] or "",
        ),
        reverse=True,
    )
    meta = {
        "configured": True,
        "status": "connected",
        "videosSampled": len(videos),
        "enrichedWithStats": bool(details_by_id),
        "uniqueChannels": len(channels),
        "totalViews": total_views,
        "totalLikes": total_likes,
        "totalComments": total_comments,
        "topVideos": videos[:8],
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "refreshIntervalSeconds": YOUTUBE_CACHE_TTL_SECONDS,
        "message": None,
    }
    result = ("YouTube", posts, meta)
    YOUTUBE_CACHE["result"] = result
    YOUTUBE_CACHE["expires_at"] = now_ts + YOUTUBE_CACHE_TTL_SECONDS
    return result


def _fetch_social_source(feed):
    source, url = feed
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "KUVHURA-Observatory/1.0"},
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    posts = []
    if source == "Bluesky":
        for item in payload.get("posts", []):
            record = item.get("record", {})
            posts.append({
                "text": record.get("text", ""),
                "created_at": record.get("createdAt"),
                "url": item.get("uri"),
            })
    else:
        if not isinstance(payload, list):
            raise ValueError("Mastodon returned an invalid status list")
        for item in payload:
            posts.append({
                "text": _plain_text(item.get("content", "")),
                "created_at": item.get("created_at"),
                "url": item.get("url"),
            })
    return source, posts


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            period TEXT,
            locality TEXT,
            entity TEXT,
            category TEXT,
            typology TEXT,
            narrative TEXT,
            evidence TEXT,
            amount REAL,
            praxisLink TEXT,
            status TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            filename TEXT,
            summary TEXT,
            report_id TEXT,
            created_at TEXT,
            content BLOB
        )
        """
    )
    conn.commit()
    conn.close()


def parse_report_from_payload(payload):
    return {
        "id": payload.get("id") or f"BE-{int(datetime.utcnow().timestamp()*1000)}",
        "period": payload.get("period") or "Live Backend",
        "locality": payload.get("locality") or "Unspecified locality",
        "entity": payload.get("entity") or "Backend flagged report",
        "category": payload.get("category") or "Municipal",
        "typology": payload.get("typology") or "Backend flagged corruption",
        "narrative": payload.get("narrative") or "Reported via backend ingestion pipeline",
        "evidence": payload.get("evidence") or "Live backend submission",
        "amount": float(payload.get("amount") or 0),
        "praxisLink": payload.get("praxisLink") or "Power Asymmetry (P)",
        "status": payload.get("status") or "Live Backend",
    }


def store_report(report):
    conn = connect_db()
    conn.execute(
        """
        INSERT OR REPLACE INTO reports (id, period, locality, entity, category, typology, narrative, evidence, amount, praxisLink, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report["id"],
            report["period"],
            report["locality"],
            report["entity"],
            report["category"],
            report["typology"],
            report["narrative"],
            report["evidence"],
            float(report["amount"]),
            report["praxisLink"],
            report["status"],
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def fetch_reports():
    conn = connect_db()
    rows = conn.execute(
        "SELECT * FROM reports ORDER BY created_at DESC, id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calculate_risk_weight(category, amount):
    category_weights = {
        "Syndicate": 2000,
        "Police": 1500,
        "Judicial": 1400,
        "Traditional": 1100,
        "Municipal": 700,
        "Line Ministry": 900,
        "Other": 500,
    }
    return (float(amount) or 0) + category_weights.get(category, 500)


def fetch_risk_hotspots():
    reports = fetch_reports()
    risk = {}
    for item in reports:
        locality = (item.get("locality") or "Unspecified locality").strip()
        risk[locality] = risk.get(locality, 0) + calculate_risk_weight(item.get("category"), item.get("amount"))
    rankings = [
        {"locality": key, "score": int(value)}
        for key, value in sorted(risk.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]
    return rankings


def fetch_social_hashtag_trends():
    now = datetime.now(timezone.utc)
    with SOCIAL_CACHE_LOCK:
        if SOCIAL_CACHE["payload"] and SOCIAL_CACHE["expires_at"] > now.timestamp():
            return SOCIAL_CACHE["payload"]

    web_app_url = (os.environ.get("GOOGLE_SHEETS_WEB_APP_URL") or "").strip()
    if web_app_url:
        try:
            result = fetch_sheet_social_hashtag_trends(web_app_url)
        except (HTTPException, OSError, URLError, ValueError) as exc:
            LOGGER.warning("Google Sheets social telemetry failed: %s", exc)
            result = {
                "available": False,
                "source": "Google Sheets RSS bridge",
                "sources": ["Google Sheets RSS bridge"],
                "sampleType": "rss-sheet",
                "updatedAt": now.isoformat(timespec="seconds"),
                "scannedPosts": 0,
                "hashtags": [],
                "message": f"Google Sheets telemetry is unavailable: {exc}",
            }
        with SOCIAL_CACHE_LOCK:
            SOCIAL_CACHE["payload"] = result
            SOCIAL_CACHE["expires_at"] = now.timestamp() + (120 if result["available"] else 30)
        return result

    fetched_posts = []
    failed_sources = []
    youtube_api_key = get_youtube_api_key()
    youtube_meta = {
        "configured": bool(youtube_api_key),
        "status": "not_configured",
        "videosSampled": 0,
        "enrichedWithStats": False,
        "uniqueChannels": 0,
        "totalViews": 0,
        "totalLikes": 0,
        "totalComments": 0,
        "topVideos": [],
        "updatedAt": now.isoformat(timespec="seconds"),
        "refreshIntervalSeconds": YOUTUBE_CACHE_TTL_SECONDS,
        "message": "Set YOUTUBE_API_KEY with YouTube Data API v3 access to include recent videos.",
    }
    max_workers = len(SOCIAL_FEEDS) + (1 if youtube_api_key else 0)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_social_source, feed) for feed in SOCIAL_FEEDS]
        yt_future = (
            executor.submit(_fetch_youtube_source, youtube_api_key, now.timestamp())
            if youtube_api_key
            else None
        )
        for feed, future in zip(SOCIAL_FEEDS, futures):
            source = feed[0]
            try:
                fetched_posts.append(future.result())
            except Exception as exc:
                LOGGER.warning("Social feed %s failed: %s", source, exc)
                failed_sources.append(source)
        if yt_future is not None:
            try:
                yt_source, yt_posts, youtube_meta = yt_future.result()
                fetched_posts.append((yt_source, yt_posts))
            except Exception as exc:
                safe_err = _redact_api_key(exc)
                LOGGER.warning("Social feed YouTube failed: %s", safe_err)
                failed_sources.append("YouTube")
                youtube_meta = {
                    **youtube_meta,
                    "configured": True,
                    "status": "unavailable",
                    "message": safe_err,
                }

    parsed_posts = []
    seen_posts = set()
    for source, posts in fetched_posts:
        for item in posts:
            identity = item["url"] or (source, item["text"], item["created_at"])
            if identity in seen_posts:
                continue
            seen_posts.add(identity)
            created_at = item["created_at"]
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None
                if created and created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                created = None
            parsed_posts.append({
                "text": item["text"],
                "created": created,
                "source": source,
            })

    parsed_posts.sort(
        key=lambda post: post["created"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    split_at = (len(parsed_posts) + 1) // 2
    latest_sample = parsed_posts[:split_at]
    earlier_sample = parsed_posts[split_at:]
    tag_counts = {}
    for sample_name, sample in (("latest", latest_sample), ("earlier", earlier_sample)):
        for post in sample:
            for tag in HASHTAG_PATTERN.findall(post["text"]):
                key = tag.casefold()
                if key not in tag_counts:
                    tag_counts[key] = {"tag": tag, "latestMentions": 0, "earlierMentions": 0}
                field = "latestMentions" if sample_name == "latest" else "earlierMentions"
                tag_counts[key][field] += 1

    trends = []
    for item in tag_counts.values():
        latest_count = item["latestMentions"]
        earlier_count = item["earlierMentions"]
        if earlier_count == 0:
            trajectory = "new" if latest_count else "no baseline"
            change_pct = None
        else:
            latest_rate = latest_count / max(1, len(latest_sample))
            earlier_rate = earlier_count / max(1, len(earlier_sample))
            change_pct = round(((latest_rate - earlier_rate) / earlier_rate) * 100)
            trajectory = "rising" if change_pct >= 20 else "falling" if change_pct <= -20 else "steady"
        trends.append({
            "tag": item["tag"],
            "mentions": latest_count + earlier_count,
            "latestMentions": latest_count,
            "earlierMentions": earlier_count,
            "changePct": change_pct,
            "trajectory": trajectory,
        })
    trends.sort(key=lambda item: (item["latestMentions"], item["mentions"]), reverse=True)

    available_sources = list(dict.fromkeys(post["source"] for post in parsed_posts))
    valid_dates = [post["created"] for post in parsed_posts if post["created"]]
    result = {
        "available": bool(parsed_posts),
        "source": " + ".join(available_sources) if available_sources else "Bluesky and Mastodon public feeds",
        "sources": available_sources,
        "failedSources": failed_sources,
        "query": "Zimbabwe",
        "updatedAt": now.isoformat(timespec="seconds"),
        "scannedPosts": len(parsed_posts),
        "latestSamplePosts": len(latest_sample),
        "earlierSamplePosts": len(earlier_sample),
        "coverageStart": min(valid_dates).isoformat(timespec="seconds") if valid_dates else None,
        "coverageEnd": max(valid_dates).isoformat(timespec="seconds") if valid_dates else None,
        "hashtags": trends[:8],
        "youtube": youtube_meta,
    }
    if not parsed_posts:
        result["message"] = "No matching public posts could be retrieved from Bluesky, Mastodon, or YouTube feeds."

    with SOCIAL_CACHE_LOCK:
        SOCIAL_CACHE["payload"] = result
        SOCIAL_CACHE["expires_at"] = now.timestamp() + (120 if result["available"] else 30)
    return result


def fetch_sheet_social_hashtag_trends(web_app_url):
    request = Request(
        web_app_url,
        headers={"Accept": "application/json", "User-Agent": "KUVHURA-Observatory/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("Google Apps Script returned an invalid telemetry response")

    trends = []
    for row in payload["rows"]:
        if not isinstance(row, list) or len(row) < 5:
            raise ValueError("Google Sheets contains a malformed telemetry row")
        timestamp, hashtag, mentions, velocity, polarization = row[:5]
        if not isinstance(hashtag, str) or not hashtag.strip():
            raise ValueError("Google Sheets contains a telemetry row without a hashtag")
        try:
            mentions = int(float(mentions))
            velocity = float(velocity)
            polarization = float(polarization)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Google Sheets contains non-numeric telemetry metrics") from exc

        trends.append({
            "tag": hashtag.strip(),
            "mentions": mentions,
            "latestMentions": mentions,
            "earlierMentions": 0,
            "changePct": None,
            "trajectory": "estimated",
            "narrativeVelocity": velocity,
            "polarizationIndex": polarization,
            "timestamp": timestamp,
        })

    trends.sort(key=lambda item: item["mentions"], reverse=True)
    updated_at = payload.get("updatedAt") or (trends[0]["timestamp"] if trends else None)
    return {
        "available": bool(trends),
        "source": "Google Sheets RSS bridge",
        "sources": ["Google Sheets RSS bridge"],
        "sampleType": "rss-sheet",
        "updatedAt": updated_at,
        "scannedPosts": 0,
        "hashtags": trends[:8],
        "message": None if trends else "The SocialTelemetry sheet does not contain a telemetry sample yet.",
    }


def respond_json(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def parse_multipart_form(body, content_type):
    if not content_type or "multipart/form-data" not in content_type:
        return {}

    boundary = content_type.split("boundary=")[-1].strip("\"") if "boundary=" in content_type else None
    if not boundary:
        return {}

    chunks = body.split(f"--{boundary}".encode("utf-8"))
    results = {}
    for chunk in chunks[1:-1]:
        if not chunk.strip():
            continue
        if chunk.startswith(b"--"):
            continue
        chunk = chunk.lstrip(b"\r\n")
        if b"\r\n\r\n" in chunk:
            header_bytes, value_bytes = chunk.split(b"\r\n\r\n", 1)
        elif b"\n\n" in chunk:
            header_bytes, value_bytes = chunk.split(b"\n\n", 1)
        else:
            continue
        value_bytes = value_bytes.rstrip(b"\r\n")
        headers = BytesParser(policy=default).parsebytes(header_bytes + b"\r\n\r\n")
        disposition = headers.get("Content-Disposition", "")
        name = None
        filename = None
        if "name=" in disposition:
            name = disposition.split("name=")[1].split(";")[0].strip('"')
        if "filename=" in disposition:
            filename = disposition.split("filename=")[1].split(";")[0].strip('"')
        if name:
            if filename:
                results[name] = {"filename": filename, "content": value_bytes}
            else:
                results[name] = value_bytes.decode("utf-8", errors="ignore")
    return results


def serve_file(handler, file_path):
    if not os.path.exists(file_path):
        handler.send_error(404)
        return
    with open(file_path, "rb") as f:
        content = f.read()
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "application/octet-stream"
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


def serve_file_head(handler, file_path):
    if not os.path.exists(file_path):
        handler.send_error(404)
        return
    with open(file_path, "rb") as f:
        content = f.read()
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "application/octet-stream"
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()


class AppHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/api/health":
            respond_json(self, 200, {"status": "ok"})
            return

        if path in ("/", "/index.html"):
            serve_file_head(self, INDEX_PATH)
            return

        file_path = os.path.join(BASE_DIR, path.lstrip("/"))
        if os.path.isfile(file_path):
            serve_file_head(self, file_path)
            return

        self.send_error(404)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/api/reports":
            respond_json(self, 200, fetch_reports())
            return

        if path == "/api/risk":
            respond_json(self, 200, fetch_risk_hotspots())
            return

        if path == "/api/social/hashtags":
            respond_json(self, 200, fetch_social_hashtag_trends())
            return

        if path == "/api/ai/status":
            status_code, payload = check_gemini_status()
            respond_json(self, status_code, payload)
            return

        if path == "/api/health":
            respond_json(self, 200, {"status": "ok"})
            return

        if path in ("/", "/index.html"):
            serve_file(self, INDEX_PATH)
            return

        if path in (
            "/public/assets/aistudio/Code_Generated_Image_eb225bc7.png",
            "/assets/aistudio/Code_Generated_Image_eb225bc7.png",
        ):
            asset_path = os.path.join(BASE_DIR, "public", "assets", "aistudio", "Code_Generated_Image_eb225bc7.png")
            if os.path.isfile(asset_path):
                serve_file(self, asset_path)
                return

        public_files = {
            "/index.html",
            "/structural-telemetry.html",
            "/systemic-risk.html",
            "/api-config.js",
            "/political-economy-timeseries.js",
            "/manifest.json",
            "/service-worker.js",
            "/icon.svg",
            "/pwa-192x192.png",
            "/pwa-512x512.png",
            "/pwa-maskable-512x512.png",
            "/apple-touch-icon.png",
            "/favicon.ico",
        }
        if path in public_files:
            file_path = os.path.join(BASE_DIR, path.lstrip("/"))
            if os.path.isfile(file_path):
                serve_file(self, file_path)
                return

        self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path

        if path == "/api/ai/query":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                respond_json(self, 400, {"error": "Invalid JSON body"})
                return
            prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt.strip()) > 12000:
                respond_json(self, 400, {"error": "A prompt of 1–12,000 characters is required."})
                return
            status_code, result = query_gemini_model(prompt.strip())
            respond_json(self, status_code, result)
            return

        if path == "/api/reports":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                respond_json(self, 400, {"error": "Invalid JSON body"})
                return

            report = parse_report_from_payload(payload)
            store_report(report)
            respond_json(self, 201, {"message": "Report saved", "report": report})
            return

        if path == "/api/attachments":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            if FieldStorage is not None:
                form = FieldStorage(
                    fp=BytesIO(raw),
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": content_type,
                        "CONTENT_LENGTH": str(length),
                    },
                )
                uploaded_file = form["file"] if "file" in form else None
                if uploaded_file is None or not hasattr(uploaded_file, "filename") or not uploaded_file.filename:
                    respond_json(self, 400, {"error": "No file uploaded"})
                    return
                file_bytes = uploaded_file.file.read()
                file_name = uploaded_file.filename
            else:
                parsed = parse_multipart_form(raw, content_type)
                file_entry = parsed.get("file")
                if not isinstance(file_entry, dict) or not file_entry.get("filename"):
                    respond_json(self, 400, {"error": "No file uploaded"})
                    return
                file_name = file_entry["filename"]
                file_bytes = file_entry["content"]
            text_preview = ""
            try:
                text_preview = file_bytes.decode("utf-8", errors="ignore")
            except Exception:
                text_preview = ""

            summary = text_preview[:500] or f"Attachment: {file_name} was received and stored for backend review."
            report = {
                "id": f"ATT-{int(datetime.utcnow().timestamp()*1000)}",
                "period": "Live Backend",
                "locality": "Unspecified locality",
                "entity": "Attachment Ingestion",
                "category": "Municipal",
                "typology": "Attachment-derived corruption signal",
                "narrative": summary,
                "evidence": "File Attachment / Backend Ingestion",
                "amount": 0,
                "praxisLink": "Power Asymmetry (P)",
                "status": "Live Backend",
            }
            store_report(report)

            conn = connect_db()
            conn.execute(
                "INSERT INTO attachments (id, filename, summary, report_id, created_at, content) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report["id"],
                    file_name,
                    summary,
                    report["id"],
                    datetime.utcnow().isoformat(timespec="seconds"),
                    file_bytes,
                ),
            )
            conn.commit()
            conn.close()

            respond_json(self, 201, {"message": "Attachment saved", "report": report})
            return

        respond_json(self, 404, {"error": "Not found"})


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"KUVHURA backend running on http://{HOST}:{PORT}")
    server.serve_forever()
