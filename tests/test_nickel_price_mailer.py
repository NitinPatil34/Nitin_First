import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock

import nickel_price_mailer as mailer


SAMPLE_HTML = """
<html>
  <head><title>Nickel Prices Chart - Shanghai Metals Market</title></head>
  <body>
    <h1>Nickel Prices</h1>
    <section>
      <span>SMM Shanghai #1 Nickel Cathode</span>
      <span>122,325</span>
      <span>+800</span>
      <span>CNY/mt</span>
      <span>May 30, 2026</span>
    </section>
    <section>
      <span>LMEselect Nickel 3 Month</span>
      <span>15,345</span>
      <span>-125</span>
      <span>USD/mt</span>
      <span>2026-05-30</span>
    </section>
  </body>
</html>
"""


class NickelPriceMailerTests(unittest.TestCase):
    def test_env_csv_uses_default_for_blank_optional_variable(self):
        with mock.patch.dict(os.environ, {"NICKEL_PRICE_URLS": ""}, clear=False):
            self.assertEqual(mailer.env_csv("NICKEL_PRICE_URLS", ("https://default.example",)), ("https://default.example",))

    def test_normalize_smtp_password_removes_gmail_app_password_spaces(self):
        password = mailer.normalize_smtp_password(
            smtp_host="smtp.gmail.com",
            smtp_username="mla770900@gmail.com",
            password="abcd efgh ijkl mnop",
        )

        self.assertEqual(password, "abcdefghijklmnop")

    def test_parse_snapshot_extracts_nickel_rows(self):
        snapshot = mailer.parse_snapshot("https://www.metal.com/nickel", SAMPLE_HTML)

        self.assertEqual(snapshot.title, "Nickel Prices Chart - Shanghai Metals Market")
        self.assertGreaterEqual(len(snapshot.rows), 2)
        first = snapshot.rows[0]
        self.assertEqual(first.label, "SMM Shanghai #1 Nickel Cathode")
        self.assertEqual(first.value, "122,325")
        self.assertEqual(first.change, "+800")
        self.assertEqual(first.unit, "CNY/mt")
        self.assertEqual(first.date, "May 30, 2026")


    def test_parse_snapshot_extracts_rows_from_metal_json_api(self):
        payload = {
            "code": 0,
            "msg": "Success",
            "data": {
                "category_list": [
                    {
                        "second_name": "Nickel",
                        "products": [
                            {
                                "product_id": "201102250239",
                                "product_code": "SMM-NI-RN-001",
                                "product_name": "SMM Shanghai 1# Nickel Cathode",
                                "unit": "USD/tonne",
                                "newest_price": {
                                    "low": "18608.58",
                                    "high": "18882.04",
                                    "average": "18745.31",
                                    "change": "153.09",
                                    "change_rate_percent": "0.82%",
                                    "renew_date": "2026-05-29",
                                },
                            }
                        ],
                    }
                ]
            },
        }

        snapshot = mailer.parse_snapshot(
            "https://platform.metal.com/spotoverseascenter/v1/prices/product_list?second_name=Nickel",
            json.dumps(payload),
        )

        self.assertEqual(snapshot.title, "metal.com nickel price API")
        self.assertEqual(len(snapshot.rows), 1)
        row = snapshot.rows[0]
        self.assertEqual(row.label, "SMM Shanghai 1# Nickel Cathode (SMM-NI-RN-001)")
        self.assertEqual(row.value, "18745.31 (18608.58-18882.04)")
        self.assertEqual(row.unit, "USD/tonne")
        self.assertEqual(row.change, "153.09 (0.82%)")
        self.assertEqual(row.date, "2026-05-29")

    def test_build_email_body_includes_source_and_rows(self):
        snapshot = mailer.PriceSnapshot(
            source_url="https://www.metal.com/nickel",
            fetched_at_utc=dt.datetime(2026, 5, 30, 12, 0, tzinfo=dt.timezone.utc),
            title="Nickel",
            rows=(mailer.PriceRow("SMM Shanghai #1 Nickel Cathode", "122,325", "CNY/mt", "+800", "May 30, 2026"),),
            raw_excerpt="",
        )

        body = mailer.build_email_body((snapshot,))

        self.assertIn("https://www.metal.com/nickel", body)
        self.assertIn("SMM Shanghai #1 Nickel Cathode", body)
        self.assertIn("122,325", body)


    def test_fetch_snapshots_returns_structured_sources_when_available(self):
        mail_config = mailer.MailConfig(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username=None,
            smtp_password=None,
            sender="nickel@example.com",
            recipients=("trader@example.com",),
            use_starttls=True,
            use_ssl=False,
        )
        config = mailer.AppConfig(
            urls=("https://api.example.test", "https://page.example.test"),
            interval_minutes=60,
            request_timeout_seconds=10,
            user_agent="test",
            state_file=None,
            send_only_on_change=False,
            mail=mail_config,
        )
        api_payload = json.dumps(
            {
                "data": {
                    "category_list": [
                        {
                            "products": [
                                {
                                    "product_name": "SMM Shanghai 1# Nickel Cathode",
                                    "unit": "USD/tonne",
                                    "newest_price": {"average": "18745.31", "renew_date": "2026-05-29"},
                                }
                            ]
                        }
                    ]
                }
            }
        )

        def fake_fetch(url, _timeout, _agent):
            if "api" in url:
                return api_payload
            return "<html><title>Nickel Prices</title><body>Nickel Prices</body></html>"

        with mock.patch.object(mailer, "fetch_page", side_effect=fake_fetch):
            snapshots = mailer.fetch_snapshots(config)

        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0].has_price_rows)

    def test_run_once_skips_unchanged_digest_when_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state")
            mail_config = mailer.MailConfig(
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username=None,
                smtp_password=None,
                sender="nickel@example.com",
                recipients=("trader@example.com",),
                use_starttls=True,
                use_ssl=False,
            )
            config = mailer.AppConfig(
                urls=("https://www.metal.com/nickel",),
                interval_minutes=60,
                request_timeout_seconds=10,
                user_agent="test",
                state_file=state_file,
                send_only_on_change=True,
                mail=mail_config,
            )
            snapshot = mailer.PriceSnapshot(
                source_url="https://www.metal.com/nickel",
                fetched_at_utc=dt.datetime(2026, 5, 30, 12, 0, tzinfo=dt.timezone.utc),
                title="Nickel",
                rows=(mailer.PriceRow("Nickel", "122,325"),),
                raw_excerpt="",
            )
            digest = mailer.combined_digest((snapshot,))
            mailer.write_digest(state_file, digest)

            with mock.patch.object(mailer, "fetch_snapshots", return_value=(snapshot,)), mock.patch.object(
                mailer, "send_email"
            ) as send_email:
                sent = mailer.run_once(config)

            self.assertFalse(sent)
            send_email.assert_not_called()


if __name__ == "__main__":
    unittest.main()
