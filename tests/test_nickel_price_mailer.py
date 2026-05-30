import datetime as dt
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
