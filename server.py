#!/usr/bin/env python3
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
from urllib.parse import urlparse
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
HASHTAG_PATTERN = re.compile(r"(?<![\w])#[\w][\w-]*", re.UNICODE)


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
    return " ".join(parser.parts)


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

    web_app_url = os.environ.get("GOOGLE_SHEETS_WEB_APP_URL")
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
    with ThreadPoolExecutor(max_workers=len(SOCIAL_FEEDS)) as executor:
        futures = [executor.submit(_fetch_social_source, feed) for feed in SOCIAL_FEEDS]
        for feed, future in zip(SOCIAL_FEEDS, futures):
            source = feed[0]
            try:
                fetched_posts.append(future.result())
            except Exception as exc:
                LOGGER.warning("Social feed %s failed: %s", source, exc)
                failed_sources.append(source)

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
    }
    if not parsed_posts:
        result["message"] = "No matching public posts could be retrieved from Bluesky or Mastodon feeds."

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

        public_files = {
            "/index.html",
            "/structural-telemetry.html",
            "/api-config.js",
            "/political-economy-timeseries.js",
            "/manifest.json",
            "/service-worker.js",
            "/icon.svg",
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
