import json
import unittest
from unittest.mock import MagicMock, patch

from aiohttp.test_utils import TestClient, TestServer

import stream_server


class StreamServerTests(unittest.TestCase):
    def test_bayesian_phi_uses_strict_signal_thresholds(self):
        self.assertEqual(stream_server.compute_bayesian_posterior(40, 80, 1200), 73.53)
        self.assertEqual(stream_server.compute_bayesian_posterior(40, 81, 0), 16.89)
        self.assertEqual(stream_server.compute_bayesian_posterior(40, 0, 1201), 16.89)

    def test_engines_reject_invalid_inputs(self):
        with self.assertRaises(ValueError):
            stream_server.compute_bayesian_posterior(101, 0, 0)
        with self.assertRaises(ValueError):
            stream_server.compute_bayesian_posterior(50, -1, 0)
        with self.assertRaises(ValueError):
            stream_server.compute_markov_path_projection(float("nan"))
        with self.assertRaises(ValueError):
            stream_server.compute_fragility_state_index(50, 40, 101)

    def test_fragility_index_formula_and_warning_bands(self):
        self.assertEqual(stream_server.compute_fragility_state_index(40, 45, 40), 49.75)
        self.assertEqual(stream_server.compute_fragility_state_index(40, 45, 40, hansard_friction=70), 53.0)
        cases = (
            (25, "Stable Consolidation"),
            (25.01, "Latent Friction"),
            (50, "Latent Friction"),
            (50.01, "Accelerated Degradation"),
            (75, "Accelerated Degradation"),
            (75.01, "Acute Systemic Crisis"),
        )
        for fsi, expected in cases:
            with self.subTest(fsi=fsi):
                self.assertEqual(stream_server.classify_fragility_state(fsi), expected)

    def test_hansard_tfidf_scoring_and_cloudflare_challenge_handling(self):
        high_friction = stream_server.score_hansard_text(
            "Parliament debated corruption tender embezzlement, inflation parallel market depreciation, "
            "budget deficit unauthorized expenditure audit discrepancy, and a parliamentary walkout standoff."
        )
        low_friction = stream_server.score_hansard_text(
            "The honorable committee approved routine agricultural irrigation maintenance minutes for rural schools."
        )
        self.assertIsNotNone(high_friction)
        self.assertIsNotNone(low_friction)
        self.assertGreater(high_friction, low_friction)
        self.assertGreaterEqual(low_friction, 40.0)
        self.assertLessEqual(high_friction, 100.0)

        cf_error = stream_server.urllib.error.HTTPError(
            "https://e-portal.parlzim.gov.zw/",
            403,
            "Forbidden",
            {"cf-mitigated": "challenge", "server": "cloudflare"},
            None,
        )
        with (
            patch.dict("os.environ", {"TELEMETRY_CACHE_PATH": "/tmp/nonexistent_kuvhura_cache.json"}),
            patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
            patch.object(stream_server, "cureq", None),
            patch("stream_server.urllib.request.urlopen", side_effect=cf_error),
        ):
            blocked = stream_server.fetch_semantic_hansard_telemetry(use_cache=False)
        self.assertIsNone(blocked["score"])
        self.assertEqual(blocked["status"], "blocked_by_cloudflare")
        self.assertEqual(blocked["source"], "unavailable")
        self.assertEqual(blocked["totalSources"], 5)
        self.assertEqual(blocked["accessibleSources"], 0)
        self.assertEqual(blocked["tracked_topics"], [])
        self.assertEqual(len(blocked["sources"]), 5)

    def test_parliamentary_policy_tracker_extracts_real_topics_across_mixed_portals(self):
        bill_html = """
        <html><body>
          <h2>Public Procurement Corruption Amendment Bill</h2>
          <p>Committee debate on corruption, tender embezzlement, and illicit financial flows accountability.</p>
          <a href="/bill-digest/exchange-rate-stability">Exchange Rate Currency Stabilization Digest 2026</a>
        </body></html>
        """.encode("utf-8")
        hansard_html = """
        <html><body>
          <h3>Parliamentary Order Paper: Rural Irrigation Maintenance Motion</h3>
          <p>The honorable committee approved routine agricultural irrigation maintenance minutes for rural schools.</p>
        </body></html>
        """.encode("utf-8")

        def fake_urlopen(request, timeout=5):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "bill-digest" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.read.return_value = bill_html
                cm.__exit__.return_value = False
                return cm
            if "e-portal.parlzim.gov.zw" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.read.return_value = hansard_html
                cm.__exit__.return_value = False
                return cm
            raise stream_server.urllib.error.HTTPError(
                url, 403, "Forbidden", {"cf-mitigated": "challenge", "server": "cloudflare"}, None
            )

        with patch.object(stream_server, "cureq", None), patch("stream_server.urllib.request.urlopen", side_effect=fake_urlopen):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False)

        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["source"], "parlzim_hansards")
        self.assertEqual(tracker["accessibleSources"], 2)
        self.assertEqual(tracker["totalSources"], 5)
        self.assertEqual(len(tracker["sources"]), 5)
        self.assertIsNotNone(tracker["score"])
        topics = [t["topic"] for t in tracker["tracked_topics"]]
        self.assertIn("Public Procurement Corruption Amendment Bill", topics)
        self.assertNotIn("National Energy & Power Amendment Bill", topics)

    def test_parliamentary_policy_tracker_uses_curl_cffi_chrome_impersonation(self):
        fake_cureq = MagicMock()

        def fake_get(url, impersonate=None, timeout=None):
            self.assertEqual(impersonate, "chrome")
            self.assertEqual(timeout, 10)
            resp = MagicMock()
            if "e-portal.parlzim.gov.zw" in url:
                resp.status_code = 200
                resp.headers = {"content-type": "text/html"}
                resp.text = (
                    "<html><body><h2>Audit Discrepancy & Public Funds Committee Report</h2>"
                    "<p>Parliament reviewed audit discrepancy, tender embezzlement, and currency depreciation.</p>"
                    "</body></html>"
                )
            else:
                resp.status_code = 403
                resp.headers = {"cf-mitigated": "challenge", "server": "cloudflare"}
                resp.text = "Just a moment..."
            return resp

        fake_cureq.get.side_effect = fake_get
        with patch.object(stream_server, "cureq", fake_cureq):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False, allow_mirror_fallback=False)

        self.assertEqual(fake_cureq.get.call_count, 5)
        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["accessibleSources"], 1)
        self.assertEqual(tracker["totalSources"], 5)
        self.assertEqual(tracker["sources"][-1]["transport"], "curl_cffi_chrome")
        self.assertEqual(tracker["tracked_topics"][0]["topic"], "Audit Discrepancy & Public Funds Committee Report")

    def test_cloudflare_403_fails_over_to_zimlii_and_parliament_rss_mirrors(self):
        zimlii_html = """
        <html><body>
          <a href="/akn/zw/act/si/2026/9/eng@2026-01-12">Public Procurement and Disposal of Public Assets (Amendment) Regulations, 2026</a>
          <p>Regulations addressing tender audit discrepancy, public funds accountability, and procurement transparency across ministries.</p>
        </body></html>
        """.encode("utf-8")
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Parliament Debates</title>
          <item>
            <title>Parliament portfolio committee debates 2027 National Budget and audit discrepancies</title>
            <link>https://news.google.com/articles/zimbabwe-parliament-budget</link>
            <description>Parliamentary committee oversight on expenditure, debt, and exchange rate friction.</description>
          </item>
        </channel></rss>
        """.encode("utf-8")

        def fake_urlopen(request, timeout=8):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "zimlii.org" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.headers = {}
                cm.__enter__.return_value.read.return_value = zimlii_html
                cm.__exit__.return_value = False
                return cm
            if "news.google.com" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.headers = {}
                cm.__enter__.return_value.read.return_value = rss_xml
                cm.__exit__.return_value = False
                return cm
            raise stream_server.urllib.error.HTTPError(
                url, 403, "Forbidden", {"cf-mitigated": "challenge", "server": "cloudflare"}, None
            )

        with (
            patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
            patch.object(stream_server, "cureq", None),
            patch("stream_server.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False, allow_mirror_fallback=True)

        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["accessibleSources"], 5)
        self.assertTrue(all(src.get("viaFallbackMirror") for src in tracker["sources"]))
        self.assertTrue(all(src.get("primaryBlockedByCloudflare") for src in tracker["sources"]))
        topic_titles = [t["topic"] for t in tracker["tracked_topics"]]
        self.assertIn("Public Procurement and Disposal of Public Assets (Amendment) Regulations, 2026", topic_titles)
        self.assertIn("Parliament portfolio committee debates 2027 National Budget and audit discrepancies", topic_titles)

    def test_pypdf_extraction_handles_pdf_responses(self):
        fake_page = MagicMock()
        fake_page.extract_text.return_value = (
            "Parliamentary Public Accounts Committee Audit Report on tender embezzlement, "
            "unauthorized expenditure, and currency depreciation across state enterprises."
        )
        fake_reader_cls = MagicMock()
        fake_reader_cls.return_value.pages = [fake_page]

        with patch.object(stream_server, "PdfReader", fake_reader_cls):
            extracted = stream_server.extract_pdf_text(b"%PDF-1.7 mock binary")
            self.assertIn("Public Accounts Committee Audit Report", extracted)

            cm = MagicMock()
            cm.__enter__.return_value.status = 200
            cm.__enter__.return_value.headers = {"Content-Type": "application/pdf"}
            cm.__enter__.return_value.read.return_value = b"%PDF-1.7 mock binary"
            cm.__exit__.return_value = False
            with (
                patch.object(stream_server, "cureq", None),
                patch("stream_server.urllib.request.urlopen", return_value=cm),
            ):
                status_code, body, _hdrs, _transport = stream_server._fetch_portal_response(
                    "https://www.parlzim.gov.zw/docs/audit-brief.pdf"
                )
        self.assertEqual(status_code, 200)
        self.assertIn("Audit Report on tender embezzlement", body)
        self.assertGreater(stream_server.score_hansard_text(body), 42.0)

    def test_scraperapi_bypass_and_html_pdf_link_ingestion(self):
        import os

        html_with_pdf = (
            "<html><body><main>"
            "<h1>Parliament of Zimbabwe Hansard Portal</h1>"
            "<p>Routine session index listing official parliamentary debate transcripts for November 2026.</p>"
            "<a href='/uploads/hansard-november-2026-debate.pdf'>National Assembly Hansard Vol 53 Debate</a>"
            "</main></body></html>"
        )
        fake_page = MagicMock()
        fake_page.extract_text.return_value = (
            "Parliamentary debate regarding unauthorized expenditures, audit discrepancies, "
            "currency depreciation, and tender embezzlement across public procurement agencies."
        )
        fake_reader_cls = MagicMock()
        fake_reader_cls.return_value.pages = [fake_page]

        def fake_cureq_get(url, **kwargs):
            resp = MagicMock()
            if url == "https://api.scraperapi.com/":
                target = (kwargs.get("params") or {}).get("url", "")
                self.assertEqual((kwargs.get("params") or {}).get("api_key"), "test_scraper_key")
                if target.endswith(".pdf"):
                    resp.status_code = 200
                    resp.headers = {"Content-Type": "application/pdf"}
                    resp.content = b"%PDF-1.7 proxied pdf"
                    return resp
                resp.status_code = 200
                resp.headers = {"Content-Type": "text/html"}
                resp.content = html_with_pdf.encode("utf-8")
                resp.text = html_with_pdf
                return resp

            resp.status_code = 403
            resp.headers = {"cf-mitigated": "challenge", "server": "cloudflare"}
            resp.content = b"Just a moment..."
            resp.text = "Just a moment..."
            return resp

        fake_cureq = MagicMock()
        fake_cureq.get.side_effect = fake_cureq_get

        with (
            patch.dict(os.environ, {"SCRAPER_API_KEY": "test_scraper_key"}),
            patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
            patch.object(stream_server, "PARLZIM_STATIC_PORTALS", (("Hansards", "https://e-portal.parlzim.gov.zw/"),)),
            patch.object(stream_server, "_get_parlzim_portals", return_value=(("Hansards", "https://e-portal.parlzim.gov.zw/"),)),
            patch.object(stream_server, "PdfReader", fake_reader_cls),
            patch.object(stream_server, "cureq", fake_cureq),
        ):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False, allow_mirror_fallback=False)

        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["accessibleSources"], 1)
        self.assertEqual(tracker["sources"][0]["transport"], "scraperapi")
        self.assertEqual(tracker["sources"][0]["pdfCount"], 1)
        pdf_topic = tracker["tracked_topics"][0]
        self.assertEqual(pdf_topic["topic"], "National Assembly Hansard Vol 53 Debate")
        self.assertEqual(pdf_topic["status"], "PDF Downloaded & Ingested")
        self.assertEqual(pdf_topic["url"], "https://e-portal.parlzim.gov.zw/uploads/hansard-november-2026-debate.pdf")
        self.assertGreater(pdf_topic["friction"], 45.0)

    def test_flaresolverr_normalizes_v1_and_bypasses_cloudflare_403(self):
        import os

        self.assertEqual(
            stream_server._normalize_flaresolverr_endpoint("http://localhost:8191"),
            "http://localhost:8191/v1",
        )
        self.assertEqual(
            stream_server._normalize_flaresolverr_endpoint("http://localhost:8191/v1/"),
            "http://localhost:8191/v1",
        )

        solved_html = (
            "<html><body>"
            "<h1>Finance Bill Digest 2026</h1>"
            "<p>Parliament reviewed audit discrepancies, public debt ceilings, and currency depreciation.</p>"
            "<a href='https://www.parlzim.gov.zw/bill-digest/finance-2026'>Finance Amendment Bill Digest 2026</a>"
            "</body></html>"
        )
        fake_cureq = MagicMock()
        cf_resp = MagicMock()
        cf_resp.status_code = 403
        cf_resp.headers = {"cf-mitigated": "challenge", "server": "cloudflare"}
        cf_resp.content = b"Just a moment..."
        cf_resp.text = "Just a moment..."
        fake_cureq.get.return_value = cf_resp

        fs_payload = json.dumps({
            "status": "ok",
            "solution": {
                "status": 200,
                "headers": {"Content-Type": "text/html"},
                "response": solved_html,
            },
        }).encode("utf-8")

        captured_urls = []

        def fake_urlopen(req, timeout=25):
            captured_urls.append(getattr(req, "full_url", str(req)))
            cm = MagicMock()
            cm.__enter__.return_value.read.return_value = fs_payload
            cm.__exit__.return_value = False
            return cm

        with (
            patch.dict(os.environ, {"FLARESOLVERR_URL": "http://localhost:8191", "SCRAPER_API_KEY": ""}),
            patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
            patch.object(stream_server, "_get_parlzim_portals", return_value=(("Bill Digests", "https://www.parlzim.gov.zw/bill-digest/"),)),
            patch.object(stream_server, "cureq", fake_cureq),
            patch("stream_server.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False, allow_mirror_fallback=False)

        self.assertEqual(captured_urls, ["http://localhost:8191/v1"])
        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["sources"][0]["transport"], "flaresolverr")
        self.assertIn("Finance Bill Digest 2026", [t["topic"] for t in tracker["tracked_topics"]])

    def test_tracked_issues_include_dates_summaries_responsible_persons_and_ranks(self):
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
          <channel>
            <item>
              <title>Parliament Public Accounts Committee probes tender embezzlement</title>
              <link>https://news.example.zw/pac-audit</link>
              <pubDate>Tue, 10 Nov 2026 09:30:00 GMT</pubDate>
              <dc:creator>Hon. Charlton Hwende</dc:creator>
              <description>Tabled oversight findings on audit discrepancies and unauthorized procurement expenditure.</description>
            </item>
          </channel>
        </rss>"""
        rss_items, _ = stream_server._extract_rss_topics(rss_xml, "Hansards", "https://e-portal.parlzim.gov.zw/")
        self.assertEqual(len(rss_items), 1)
        self.assertEqual(rss_items[0]["submission_date"], "2026-11-10")
        self.assertEqual(rss_items[0]["responsible_person"], "Hon. Charlton Hwende")
        self.assertIn("audit discrepancies", rss_items[0]["content_excerpt"])
        self.assertTrue(rss_items[0]["summary"])

        raw_topics = [
            {
                "topic": "Toll Roads (Forbes Border Post Modernisation) Regulations, 2026",
                "category": "Bill Digests",
                "status": "Legislative Pipeline",
                "friction": 42.0,
                "url": "https://zimlii.org/akn/zw/act/si/2026/179/eng@2026-11-06",
            },
            {
                "topic": "Assignment of Functions (Minister of Lands, Agriculture, Fisheries, Water and Rural Development) Notice, 2026",
                "category": "Enacted Acts",
                "status": "Enacted / Gazetted",
                "friction": 49.02,
                "url": "https://zimlii.org/akn/zw/act/si/2026/96/eng@2026-06-04",
            },
            rss_items[0],
        ]
        ranked = stream_server._enrich_and_rank_topics(raw_topics)
        self.assertEqual([item["rank"] for item in ranked], [1, 2, 3])
        self.assertGreaterEqual(ranked[0]["friction"], ranked[1]["friction"])
        self.assertGreaterEqual(ranked[1]["friction"], ranked[2]["friction"])

        si_notice = next(t for t in ranked if "Assignment of Functions" in t["topic"])
        self.assertEqual(si_notice["submission_date"], "2026-06-04")
        self.assertEqual(
            si_notice["responsible_person"],
            "Minister of Lands, Agriculture, Fisheries, Water and Rural Development",
        )
        self.assertIn("Statutory Instrument 96 of 2026", si_notice["summary"])
        self.assertIn("Statutory Instrument 96 of 2026", si_notice["content_excerpt"])

        toll_reg = next(t for t in ranked if "Forbes Border Post" in t["topic"])
        self.assertEqual(toll_reg["submission_date"], "2026-11-06")
        self.assertEqual(toll_reg["responsible_person"], "Not stated in portal index")

    def test_nav_chrome_filtering_title_cleanup_and_deep_pdf_metadata(self):
        noisy_html = """
        <html><body>
          <header><nav>
            <a href="https://www.parlzim.gov.zw/policy-briefs/">Policy Briefs</a>
            <a href="https://www.parlzim.gov.zw/office-of-the-speaker/">Office of the Hon Speaker</a>
            <a href="https://www.parlzim.gov.zw/president-of-senate/">Office of the Hon President of Senate</a>
            <a href="https://www.parlzim.gov.zw/deputy-speaker-of-parliament/">Office of the Hon Deputy Speaker</a>
            <a href="https://maps.app.goo.gl/QnVP8bmyp2bpZt4j7">Parliament Building Mt Hampden.</a>
          </nav></header>
          <main>
            <p>Official Parliamentary Portfolio Committee submissions and fact-finding reports on public accountability.</p>
            <a href="https://www.parlzim.gov.zw/wp-content/uploads/2025/06/Report_on_Command_Agriculture_fact_finding_Public_Hearing.pdf">Report_on_Command_Agriculture_fact_finding_Public_Hearing</a>
          </main>
          <footer><a href="https://maps.app.goo.gl/QnVP8bmyp2bpZt4j7">Parliament Building Mt Hampden.</a></footer>
        </body></html>
        """
        extracted = stream_server.extract_legislative_topics(
            noisy_html, "Policy Briefs", "https://www.parlzim.gov.zw/policy-briefs/"
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0]["topic"],
            "Report on Command Agriculture fact finding Public Hearing",
        )
        self.assertEqual(extracted[0]["submission_date"], "2025-06")

        filtered_cache = stream_server._enrich_and_rank_topics([
            {
                "topic": "Parliament Building Mt Hampden.",
                "category": "Bill Digests",
                "status": "Legislative Pipeline",
                "friction": 42.0,
                "url": "https://maps.app.goo.gl/QnVP8bmyp2bpZt4j7",
            },
            {
                "topic": "Office of the Hon Speaker",
                "category": "Enacted Acts",
                "status": "Enacted / Gazetted",
                "friction": 48.52,
                "url": "https://www.parlzim.gov.zw/office-of-the-speaker/",
            },
            {
                "topic": "PUBLIC_BODIES_PRIVATE_BILL_PROCEDURE_ACT_2_09",
                "category": "Enacted Acts",
                "status": "PDF Downloaded & Ingested",
                "friction": 52.7,
                "url": "https://www.parlzim.gov.zw/wp-content/uploads/2025/06/PUBLIC_BODIES_PRIVATE_BILL_PROCEDURE_ACT_2_09.pdf",
            },
            {
                "topic": "Zimbabwes-GBV-Crisis-2020–2024-Prevalence-Laws-and-Gaps-in-Response",
                "category": "Fact Sheets",
                "status": "PDF Downloaded & Ingested",
                "friction": 47.97,
                "url": "https://www.parlzim.gov.zw/wp-content/uploads/2026/02/Zimbabwes-GBV-Crisis-2020–2024-Prevalence-Laws-and-Gaps-in-Response.pdf",
            },
        ])
        self.assertEqual(len(filtered_cache), 2)
        self.assertEqual(filtered_cache[0]["topic"], "Public Bodies Private Bill Procedure Act 2 09")
        self.assertEqual(filtered_cache[0]["submission_date"], "2025-06")
        self.assertEqual(filtered_cache[0]["rank"], 1)
        self.assertEqual(
            filtered_cache[1]["topic"],
            "Zimbabwes GBV Crisis 2020–2024 Prevalence Laws and Gaps in Response",
        )
        self.assertEqual(filtered_cache[1]["submission_date"], "2026-02")
        self.assertEqual(filtered_cache[1]["rank"], 2)

        fake_page = MagicMock()
        fake_page.extract_text.return_value = (
            "18 September 2025 Report submitted by Hon. Josiah Hungwe, Portfolio Committee on Budget, "
            "regarding audit discrepancies and unauthorized public expenditure."
        )
        fake_reader = MagicMock()
        fake_reader.return_value.pages = [fake_page]
        with patch.object(stream_server, "PdfReader", fake_reader):
            pdf_date, pdf_person, pdf_summary, pdf_full = stream_server.extract_pdf_metadata_and_text(
                b"%PDF-1.7 test",
                pdf_url="https://www.parlzim.gov.zw/wp-content/uploads/2025/09/budget-audit.pdf",
            )
        self.assertEqual(pdf_date, "2025-09-18")
        self.assertIn("Hon. Josiah Hungwe", pdf_person)
        self.assertIn("audit discrepancies", pdf_summary)
        self.assertIn("unauthorized public expenditure", pdf_full)

    def test_telemetry_cache_fallback_only_uses_verified_available_snapshots(self):
        import os
        import tempfile

        cf_error = stream_server.urllib.error.HTTPError(
            "https://e-portal.parlzim.gov.zw/",
            403,
            "Forbidden",
            {"cf-mitigated": "challenge", "server": "cloudflare"},
            None,
        )
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
            cache_file = tf.name
            json.dump({
                "updated_at": "2026-11-15T06:00:00Z",
                "parlzim": {
                    "score": None,
                    "status": "blocked_by_cloudflare",
                    "source": "unavailable",
                    "accessibleSources": 0,
                    "totalSources": 5,
                    "tracked_topics": [],
                },
                "last_available_parlzim": {
                    "score": 61.5,
                    "status": "available",
                    "source": "parlzim_portals",
                    "accessibleSources": 2,
                    "totalSources": 5,
                    "sources": [],
                    "tracked_topics": [{"topic": "Verified Cached Finance Bill", "category": "Bill Digests", "status": "Legislative Pipeline", "friction": 61.5}],
                },
            }, tf)

        try:
            with (
                patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file}),
                patch.object(stream_server, "cureq", None),
                patch("stream_server.urllib.request.urlopen", side_effect=cf_error),
            ):
                fallback = stream_server.fetch_parliamentary_policy_tracker(use_cache=False)
            self.assertEqual(fallback["status"], "available")
            self.assertEqual(fallback["score"], 61.5)
            self.assertTrue(fallback["fromCache"])
            self.assertEqual(fallback["cacheUpdatedAt"], "2026-11-15T06:00:00Z")
            self.assertEqual(fallback["tracked_topics"][0]["topic"], "Verified Cached Finance Bill")

            with open(cache_file, "w", encoding="utf-8") as wf:
                json.dump({
                    "timestamp": "2026-11-15T06:00:00Z",
                    "accessible_sources": 0,
                    "total_sources": 5,
                    "hansard_friction": 58.0,
                    "tracked_topics": [],
                    "status": "Live Crawl Attempted via Actions",
                }, wf)

            with (
                patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file}),
                patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
                patch.object(stream_server, "cureq", None),
                patch("stream_server.urllib.request.urlopen", side_effect=cf_error),
            ):
                blocked = stream_server.fetch_parliamentary_policy_tracker(use_cache=False)
            self.assertEqual(blocked["status"], "blocked_by_cloudflare")
            self.assertIsNone(blocked["score"])

            with open(cache_file, "w", encoding="utf-8") as wf:
                json.dump({
                    "timestamp": "2026-11-15T06:00:00Z",
                    "accessible_sources": 3,
                    "total_sources": 5,
                    "hansard_friction": 64.25,
                    "tracked_topics": [{"topic": "Cached Treasury Oversight Brief", "category": "Policy Briefs", "status": "Policy Review", "friction": 64.25}],
                    "status": "Live Crawl Attempted via Actions",
                }, wf)

            with (
                patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file}),
                patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
                patch("stream_server.urllib.request.urlopen", side_effect=AssertionError("Should read disk cache first")),
            ):
                cache_first = stream_server.fetch_parliamentary_policy_tracker(use_cache=True)
                tuple_result = stream_server.load_telemetry_cache()
            self.assertEqual(cache_first["score"], 64.25)
            self.assertEqual(cache_first["accessibleSources"], 3)
            self.assertTrue(cache_first["fromCache"])
            self.assertEqual(cache_first["tracked_topics"][0]["topic"], "Cached Treasury Oversight Brief")
            self.assertEqual(tuple_result[0], 64.25)
            self.assertEqual(tuple_result[2], 3)
            self.assertEqual(tuple_result[1][0]["topic"], "Cached Treasury Oversight Brief")
        finally:
            os.remove(cache_file)

        with patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file + ".missing"}):
            self.assertEqual(stream_server.load_telemetry_cache(), (None, [], 0))

    def test_macro_stress_proxy_requires_sourced_world_bank_data(self):
        macro = {
            "GDP_Growth": 5.3,
            "Inflation": 104.2,
            "Debt_GNI": 44.1,
            "source": "world_bank_v2",
        }
        self.assertEqual(stream_server.compute_macro_stress_proxy(macro), 43.98)
        macro["source"] = "fallback_baseline"
        self.assertIsNone(stream_server.compute_macro_stress_proxy(macro))

    def test_markov_projection_and_social_proxy_derivation(self):
        self.assertEqual(stream_server.compute_markov_path_projection(46.8), 41.9)
        self.assertEqual(
            stream_server.derive_social_metrics({
                "available": True,
                "scannedPosts": 120,
                "hashtags": [
                    {"latestMentions": 12},
                    {"latestMentions": 8},
                    {"mentions": 5},
                ],
            }),
            (120, 25),
        )
        self.assertIsNone(stream_server.derive_social_metrics({
            "available": True,
            "sampleType": "rss-sheet",
            "scannedPosts": 0,
            "hashtags": [{"mentions": 40}],
        }))

    def test_timeline_refresh_recalculates_from_daily_baseline(self):
        seed_timeline = [
            {"date": "2026-11-14", "phi": 40.0, "markov_crisis_prob": 35.0, "state": "Latent Friction"}
        ]
        with (
            patch.object(stream_server, "TELEMETRY_TIMELINE", seed_timeline),
            patch.object(stream_server, "TIMELINE_BASELINE_DATE", None),
            patch.object(stream_server, "TIMELINE_BASELINE", None),
            patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None),
            patch.object(stream_server, "LATEST_FSI_INPUTS", None),
            patch.object(stream_server, "LATEST_HANSARD_STATUS", None),
        ):
            evaluated_at = stream_server.datetime(2026, 11, 15, tzinfo=stream_server.timezone.utc)
            stream_server.update_telemetry_timeline({
                "available": True,
                "scannedPosts": 100,
                "hashtags": [{"latestMentions": 12}],
            }, evaluated_at)
            high_signal_phi = seed_timeline[-1]["phi"]
            self.assertEqual(high_signal_phi, 16.89)

            stream_server.update_telemetry_timeline({
                "available": True,
                "scannedPosts": 10,
                "hashtags": [{"latestMentions": 2}],
            }, evaluated_at)

            self.assertEqual(seed_timeline[-1]["phi"], 73.53)
            self.assertEqual(len(seed_timeline), 2)

    def test_timeline_fsi_uses_live_macro_proxy_and_withholds_fallback(self):
        seed_timeline = [
            {"date": "2026-11-14", "phi": 40.0, "markov_crisis_prob": 35.0, "state": "Latent Friction"}
        ]
        social_payload = {
            "available": True,
            "scannedPosts": 10,
            "hashtags": [{"latestMentions": 2}],
        }
        live_macro = {
            "GDP_Growth": 5.3,
            "Inflation": 104.2,
            "Debt_GNI": 44.1,
            "source": "world_bank_v2",
        }
        evaluated_at = stream_server.datetime(2026, 11, 15, tzinfo=stream_server.timezone.utc)
        with (
            patch.object(stream_server, "TELEMETRY_TIMELINE", seed_timeline),
            patch.object(stream_server, "TIMELINE_BASELINE_DATE", None),
            patch.object(stream_server, "TIMELINE_BASELINE", None),
            patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None),
            patch.object(stream_server, "LATEST_FSI_INPUTS", None),
            patch.object(stream_server, "LATEST_HANSARD_STATUS", None),
        ):
            stream_server.update_telemetry_timeline(
                social_payload, evaluated_at, layer2_macro=live_macro
            )
            entry = seed_timeline[-1]
            self.assertEqual(entry["macro_volatility_proxy"], 43.98)
            self.assertEqual(
                entry["fsi"],
                stream_server.compute_fragility_state_index(
                    entry["phi"], entry["markov_crisis_prob"], 43.98
                ),
            )
            self.assertEqual(entry["warning_level"], stream_server.classify_fragility_state(entry["fsi"]))

            stream_server.update_telemetry_timeline(
                social_payload,
                evaluated_at,
                layer2_macro={**live_macro, "source": "fallback_baseline"},
            )
            self.assertNotIn("fsi", seed_timeline[-1])
            self.assertEqual(
                stream_server.get_dual_engine_timeline()["fsiStatus"]["status"],
                "awaiting_sourced_macro_data",
            )

    @patch.object(stream_server, "fetch_semantic_hansard_telemetry")
    @patch.object(stream_server, "fetch_layer2_macro_telemetry")
    @patch.object(stream_server, "fetch_social_hashtag_trends")
    def test_stream_uses_local_social_telemetry_collector(self, fetch_trends, fetch_macro, fetch_hansard):
        payload = {
            "available": True,
            "updatedAt": "2026-11-08T12:00:00Z",
            "scannedPosts": 4,
            "hashtags": [{"tag": "#ZimResources", "mentions": 4, "latestMentions": 4}],
            "orientationInputs": None,
        }
        macro_payload = {"GDP_Growth": 5.3, "Inflation": 104.2, "Debt_GNI": 44.1, "source": "world_bank_v2"}
        hansard_payload = {"score": 68.4, "status": "available", "source": "parlzim_hansards"}
        fetch_trends.return_value = payload
        fetch_macro.return_value = macro_payload
        fetch_hansard.return_value = hansard_payload

        with (
            patch.object(stream_server, "TELEMETRY_TIMELINE", [
                {"date": "2026-11-07", "phi": 50.0, "markov_crisis_prob": 35.0, "state": "Latent Friction"}
            ]),
            patch.object(stream_server, "TIMELINE_BASELINE_DATE", None),
            patch.object(stream_server, "TIMELINE_BASELINE", None),
            patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None),
            patch.object(stream_server, "LATEST_FSI_INPUTS", None),
            patch.object(stream_server, "LATEST_HANSARD_STATUS", None),
        ):
            result = stream_server.fetch_trending_telemetry()

        fetch_trends.assert_called_once_with()
        fetch_macro.assert_called_once_with()
        fetch_hansard.assert_called_once_with()
        self.assertEqual(result["status"], "available")
        self.assertIs(result["telemetry"], payload)
        self.assertEqual(result["telemetry"]["hashtags"][0]["tag"], "#ZimResources")
        self.assertEqual(result["layer2Macro"], macro_payload)
        self.assertEqual(result["dualEngineTimeline"]["inputStatus"], "updated")
        self.assertEqual(result["dualEngineTimeline"]["fsiStatus"]["status"], "available")
        self.assertTrue(result["dualEngineTimeline"]["fsiStatus"]["hansard_included"])
        self.assertEqual(result["dualEngineTimeline"]["hansardStatus"]["score"], 68.4)

    @patch("stream_server.urllib.request.urlopen")
    def test_fetch_layer2_macro_telemetry_parses_world_bank_values(self, mock_urlopen):
        responses = [
            json.dumps([{}, [{"value": 6.1}]]).encode("utf-8"),
            json.dumps([{}, [{"value": 4.8}]]).encode("utf-8"),
            json.dumps([{}, [{"value": 39.2}]]).encode("utf-8"),
        ]
        side_effects = []
        for raw in responses:
            cm = MagicMock()
            cm.__enter__.return_value.read.return_value = raw
            cm.__exit__.return_value = False
            side_effects.append(cm)
        mock_urlopen.side_effect = side_effects

        result = stream_server.fetch_layer2_macro_telemetry(use_cache=False)

        self.assertEqual(result["GDP_Growth"], 6.1)
        self.assertEqual(result["Inflation"], 4.8)
        self.assertEqual(result["Debt_GNI"], 39.2)
        self.assertEqual(result["source"], "world_bank_v2")

    @patch("stream_server.urllib.request.urlopen", side_effect=TimeoutError("timed out"))
    def test_fetch_layer2_macro_telemetry_falls_back_to_baseline_on_error(self, _mock_urlopen):
        result = stream_server.fetch_layer2_macro_telemetry(use_cache=False)

        self.assertEqual(result["GDP_Growth"], 8.3)
        self.assertEqual(result["Inflation"], 5.2)
        self.assertEqual(result["Debt_GNI"], 37.9)
        self.assertEqual(result["source"], "fallback_baseline")


class TimelineApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeline_endpoint_returns_seed_history_and_cors(self):
        client = TestClient(TestServer(stream_server.create_app()))
        with patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None):
            await client.start_server()
            try:
                response = await client.get("/api/timeline")
                payload = await response.json()
            finally:
                await client.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(payload["inputStatus"], "awaiting_social_sample")
        self.assertEqual(payload["timeline"][-1]["date"], "2026-11-14")
        self.assertEqual(payload["timeline"][-1]["fsi"], 62.97)


if __name__ == "__main__":
    unittest.main()
