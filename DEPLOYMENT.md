# Deployment

The recommended deployment for this repository is GitHub Actions. It runs the
mailer on a schedule, so you do not need to maintain a server.

## GitHub Actions deployment

1. Merge the nickel price email updater branch into `main`.
2. In GitHub, open the repository settings.
3. Go to **Secrets and variables** -> **Actions**.
4. Add these repository secrets:

   | Secret | Example | Notes |
   | --- | --- | --- |
   | `NICKEL_SMTP_HOST` | `smtp.gmail.com` | Required. |
   | `NICKEL_SMTP_PORT` | `587` | Optional, defaults to `587`. |
   | `NICKEL_SMTP_USERNAME` | `alerts@example.com` | Required for most providers. |
   | `NICKEL_SMTP_PASSWORD` | app password | Required for most providers. |
   | `NICKEL_EMAIL_FROM` | `alerts@example.com` | Required. |
   | `NICKEL_EMAIL_TO` | `you@example.com` | Required. Use commas for multiple recipients. |

5. Optional repository variables:

   | Variable | Default | Notes |
   | --- | --- | --- |
   | `NICKEL_SMTP_STARTTLS` | `true` | Use STARTTLS, typically port `587`. |
   | `NICKEL_SMTP_SSL` | `false` | Use SSL, typically port `465`. |
   | `NICKEL_REQUEST_TIMEOUT_SECONDS` | `30` | HTTP timeout for metal.com requests. |
   | `NICKEL_PRICE_URLS` | built-in metal.com nickel API and fallbacks | Override source URLs only if needed. |

6. Open the **Actions** tab and choose **Nickel price email update**.
7. Select **Run workflow** to send a test email immediately.

The workflow is scheduled for 08:00 UTC every day. To change the schedule, edit
`.github/workflows/nickel-price-email.yml`.

## Gmail note

If you use Gmail, create an app password instead of using your account password:

1. Enable 2-Step Verification on the Google account.
2. Create an app password for mail.
3. Store that app password as `NICKEL_SMTP_PASSWORD`.

Typical Gmail settings:

```text
NICKEL_SMTP_HOST=smtp.gmail.com
NICKEL_SMTP_PORT=587
NICKEL_SMTP_USERNAME=your-address@gmail.com
NICKEL_EMAIL_FROM=your-address@gmail.com
NICKEL_SMTP_STARTTLS=true
NICKEL_SMTP_SSL=false
```

## Local/server deployment

For a server, copy `.env.example` to `.env`, fill in values, and run:

```bash
set -a
source .env
set +a
python3 nickel_price_mailer.py
```

For cron, use one-shot mode:

```cron
0 8 * * * cd /path/to/repo && /usr/bin/env bash -lc 'set -a; source .env; set +a; python3 nickel_price_mailer.py --once'
```
