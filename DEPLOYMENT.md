# Deployment

The recommended deployment for this repository is GitHub Actions. It runs the
mailer on a schedule, so you do not need to maintain a server.

## GitHub Actions deployment

1. Merge the nickel price email updater branch into `main`.
2. In GitHub, open the repository settings.
3. Go to **Secrets and variables** -> **Actions**.
4. For the default Gmail deployment in this repository, add one repository secret:

   | Secret | Example | Notes |
   | --- | --- | --- |
   | `NICKEL` | Gmail app password | Used as the Gmail SMTP app password for `mla770900@gmail.com`. |

   Advanced deployments may override the defaults with these optional secrets:

   | Secret | Default | Notes |
   | --- | --- | --- |
   | `NICKEL_SMTP_HOST` | `smtp.gmail.com` | SMTP server host. |
   | `NICKEL_SMTP_PORT` | `587` | SMTP port. |
   | `NICKEL_SMTP_USERNAME` | `mla770900@gmail.com` | SMTP username. |
   | `NICKEL_SMTP_PASSWORD` | `NICKEL` secret | SMTP password or app password. |
   | `NICKEL_EMAIL_FROM` | `mla770900@gmail.com` | Sender email address. |
   | `NICKEL_EMAIL_TO` | `mla770900@gmail.com` | Recipient email address. |

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
3. Store that app password as the repository secret `NICKEL`.

Typical Gmail settings:

```text
NICKEL_SMTP_HOST=smtp.gmail.com
NICKEL_SMTP_PORT=587
NICKEL_SMTP_USERNAME=mla770900@gmail.com
NICKEL_EMAIL_FROM=mla770900@gmail.com
NICKEL_EMAIL_TO=mla770900@gmail.com
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
