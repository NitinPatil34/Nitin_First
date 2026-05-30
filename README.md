# Nickel Price Email Updates

This repository contains a small Python service that emails recurring nickel
price updates from [metal.com](https://www.metal.com/nickel).

The service:

- fetches metal.com's public nickel price JSON endpoint, with nickel pages as
  fallback sources;
- extracts visible nickel price rows, units, changes, and dates where present;
- sends the update through any SMTP provider;
- can run once for cron or continuously on an interval;
- uses only the Python standard library.

## Requirements

- Python 3.11 or newer
- SMTP credentials for the mailbox that will send the alerts

## Configuration

Set these environment variables before running the script:

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `NICKEL_SMTP_HOST` | yes | | SMTP server host, for example `smtp.gmail.com`. |
| `NICKEL_EMAIL_FROM` | yes | | Sender email address. |
| `NICKEL_EMAIL_TO` | yes | | Comma-separated recipient email addresses. |
| `NICKEL_SMTP_PORT` | no | `587` or `465` | SMTP port. Defaults to `465` when SSL is enabled. |
| `NICKEL_SMTP_USERNAME` | no | | SMTP username, if authentication is required. |
| `NICKEL_SMTP_PASSWORD` | no | | SMTP password or app password. |
| `NICKEL_SMTP_STARTTLS` | no | `true` | Use STARTTLS for non-SSL SMTP connections. |
| `NICKEL_SMTP_SSL` | no | `false` | Use SMTP over SSL. |
| `NICKEL_INTERVAL_MINUTES` | no | `1440` | Interval for continuous mode. |
| `NICKEL_PRICE_URLS` | no | metal.com nickel API and pages | Comma-separated source URLs to fetch. |
| `NICKEL_SEND_ONLY_ON_CHANGE` | no | `false` | Send only when extracted prices change. |
| `NICKEL_STATE_FILE` | no | `.nickel_price_mailer.state` | Digest file used for change detection. |
| `NICKEL_REQUEST_TIMEOUT_SECONDS` | no | `30` | HTTP request timeout. |

> Do not commit real SMTP credentials. Store them in your shell profile,
> secret manager, cron environment, or deployment platform secrets.

## Run once

Use this mode for a manual test or a cron schedule:

```bash
export NICKEL_SMTP_HOST="smtp.example.com"
export NICKEL_SMTP_PORT="587"
export NICKEL_SMTP_USERNAME="alerts@example.com"
export NICKEL_SMTP_PASSWORD="your-app-password"
export NICKEL_EMAIL_FROM="alerts@example.com"
export NICKEL_EMAIL_TO="you@example.com"

python3 nickel_price_mailer.py --once
```

## Run continuously

This sends one email every `NICKEL_INTERVAL_MINUTES` minutes:

```bash
export NICKEL_INTERVAL_MINUTES="360"
python3 nickel_price_mailer.py
```

## Example cron entry

To receive an update every morning at 8:00:

```cron
0 8 * * * cd /path/to/repo && /usr/bin/env bash -lc 'source .env && python3 nickel_price_mailer.py --once'
```


## Deployment

A GitHub Actions workflow is included at `.github/workflows/nickel-price-email.yml`.
After this branch is merged into `main`, add the required SMTP secrets in GitHub
repository settings, then run the workflow manually once from the Actions tab to
confirm email delivery. See `DEPLOYMENT.md` for the full checklist.

## Validate configuration

```bash
python3 nickel_price_mailer.py --print-config
```

This prints non-secret settings and confirms that required variables are present.

## Tests

```bash
python3 -m unittest discover -s tests
```
