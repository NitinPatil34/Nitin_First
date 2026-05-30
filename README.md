# Nickel Price Updates

This repository contains a small Python service that records recurring nickel
price updates from [metal.com](https://www.metal.com/nickel). It can append rows
to Google Sheets and can also send email when SMTP is configured.

The service:

- fetches metal.com's public nickel price JSON endpoint, with nickel pages as
  fallback sources;
- extracts nickel price rows, units, changes, and dates where present;
- appends the update to Google Sheets through a Google Apps Script webhook;
- optionally sends the update through any SMTP provider;
- can run once for GitHub Actions/cron or continuously on an interval;
- uses only the Python standard library.

## Requirements

- Python 3.11 or newer
- For Google Sheets: a Google Sheet with the Apps Script in
  `google_sheets_app_script.gs` deployed as a web app
- Optional: SMTP credentials if email delivery is also needed

## Configuration

Configure at least one destination: Google Sheets or email.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `NICKEL_SHEETS_WEBHOOK_URL` | for Sheets | | Google Apps Script web app URL. |
| `NICKEL_SHEETS_SHARED_SECRET` | no | | Optional shared secret checked by Apps Script. |
| `NICKEL_DISABLE_EMAIL` | no | `false` | Set to `true` for Sheets-only runs. |
| `NICKEL_SMTP_HOST` | for email | | SMTP server host, for example `smtp.gmail.com`. |
| `NICKEL_EMAIL_FROM` | for email | | Sender email address. |
| `NICKEL_EMAIL_TO` | for email | | Comma-separated recipient email addresses. |
| `NICKEL_SMTP_PORT` | no | `587` or `465` | SMTP port. Defaults to `465` when SSL is enabled. |
| `NICKEL_SMTP_USERNAME` | no | | SMTP username, if authentication is required. |
| `NICKEL_SMTP_PASSWORD` | no | | SMTP password or app password. |
| `NICKEL_SMTP_STARTTLS` | no | `true` | Use STARTTLS for non-SSL SMTP connections. |
| `NICKEL_SMTP_SSL` | no | `false` | Use SMTP over SSL. |
| `NICKEL_INTERVAL_MINUTES` | no | `1440` | Interval for continuous mode. |
| `NICKEL_PRICE_URLS` | no | metal.com nickel API and pages | Comma-separated source URLs to fetch. |
| `NICKEL_SEND_ONLY_ON_CHANGE` | no | `false` | Update destinations only when extracted prices change. |
| `NICKEL_STATE_FILE` | no | `.nickel_price_mailer.state` | Digest file used for change detection. |
| `NICKEL_REQUEST_TIMEOUT_SECONDS` | no | `30` | HTTP request timeout. |

> Do not commit real credentials or webhook URLs. Store them in GitHub Actions
> secrets, your shell profile, cron environment, or deployment platform secrets.

## Google Sheets setup

1. Create/open the Google Sheet where you want nickel prices stored.
2. Open **Extensions** -> **Apps Script**.
3. Paste the contents of `google_sheets_app_script.gs`.
4. Save the script. If you changed an existing deployment, click **Deploy** -> **Manage deployments** -> **Edit** and select **New version** before deploying again.
5. Optional but recommended: add a Script Property named
   `NICKEL_SHEETS_SHARED_SECRET` with any random value.
6. Deploy as a **Web app** with access set to **Anyone with the link**.
7. Save the web app URL as the GitHub Actions repository secret
   `NICKEL_SHEETS_WEBHOOK_URL`.
8. If you used a shared secret, save the same value as
   `NICKEL_SHEETS_SHARED_SECRET`.

## Run once

Sheets-only local example:

```bash
export NICKEL_DISABLE_EMAIL=true
export NICKEL_SHEETS_WEBHOOK_URL="https://script.google.com/macros/s/.../exec"
export NICKEL_SHEETS_SHARED_SECRET="your-random-secret"

python3 nickel_price_mailer.py --once
```

Email can also be enabled by adding SMTP variables.

## Run continuously

This updates configured destinations every `NICKEL_INTERVAL_MINUTES` minutes:

```bash
export NICKEL_INTERVAL_MINUTES="360"
python3 nickel_price_mailer.py
```

## Deployment

A GitHub Actions workflow is included at `.github/workflows/nickel-price-email.yml`.
It is configured for daily Google Sheets updates by default. After this branch is
merged into `main`, add the Google Sheets webhook secrets in GitHub repository
settings, then run the workflow manually once from the Actions tab to confirm
rows are appended. See `DEPLOYMENT.md` for the full checklist.

## Validate configuration

```bash
python3 nickel_price_mailer.py --print-config
```

This prints non-secret settings and confirms that required variables are present.

## Tests

```bash
python3 -m unittest discover -s tests
```
