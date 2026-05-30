# Deployment

The recommended deployment for this repository is GitHub Actions. It runs the
updater on a schedule, so you do not need to maintain a server. The default
deployment writes nickel prices to Google Sheets and does not require email.

## Google Sheets deployment

The sheet columns are `Fetched At UTC`, `Value`, `Cell Price %`, `Unit`, and `Price Date`. The percentage column uses `=((value * 0.013 * 10^-3) / 1.45) * 100`.


1. Create/open the Google Sheet where nickel prices should be stored.
2. Open **Extensions** -> **Apps Script**.
3. Paste the contents of `google_sheets_app_script.gs`.
4. Save the script. If you changed an existing deployment, click **Deploy** -> **Manage deployments** -> **Edit** and select **New version** before deploying again.
5. Optional but recommended: in Apps Script, open **Project Settings** ->
   **Script properties** and add:

   ```text
   NICKEL_SHEETS_SHARED_SECRET=<any random value you choose>
   ```

6. Click **Deploy** -> **New deployment**.
7. Choose type **Web app**.
8. Set **Execute as** to yourself.
9. Set **Who has access** to **Anyone with the link**. The optional shared
   secret prevents unauthorized writes.
10. Deploy and copy the web app URL.

## GitHub Actions setup

1. Merge the nickel price updater branch into `main`.
2. In GitHub, open the repository settings.
3. Go to **Secrets and variables** -> **Actions**.
4. Add these repository secrets:

   | Secret | Required | Notes |
   | --- | --- | --- |
   | `NICKEL_SHEETS_WEBHOOK_URL` | yes | Google Apps Script web app URL. |
   | `NICKEL_SHEETS_SHARED_SECRET` | if configured in Apps Script | Must match the Apps Script property. |

5. Open the **Actions** tab and choose **Nickel price update**.
6. Select **Run workflow** to append a test set of rows immediately.

The workflow is scheduled for 02:30 UTC every day. To change the schedule, edit
`.github/workflows/nickel-price-email.yml`.

## Optional email delivery

Email is disabled by default in the GitHub Actions workflow with
`NICKEL_DISABLE_EMAIL=true`. If you later want email too, set repository variable
`NICKEL_DISABLE_EMAIL=false` and add these repository secrets:

| Secret | Example | Notes |
| --- | --- | --- |
| `NICKEL_SMTP_HOST` | `smtp.gmail.com` | SMTP server host. |
| `NICKEL_SMTP_PORT` | `587` | SMTP port. |
| `NICKEL_SMTP_USERNAME` | sender email | SMTP username. |
| `NICKEL_SMTP_PASSWORD` | app password | SMTP password or app password. |
| `NICKEL_EMAIL_FROM` | sender email | Sender email address. |
| `NICKEL_EMAIL_TO` | recipient email | Comma-separated recipients. |

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
