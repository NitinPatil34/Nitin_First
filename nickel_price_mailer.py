"""Send recurring email updates for nickel prices from metal.com.

The script is intentionally dependency-free so it can run from cron, systemd,
or a simple container without additional package installation.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_URLS = (
    "https://platform.metal.com/spotoverseascenter/v1/prices/product_list?second_name=Nickel&page=1&page_size=50",
    "https://www.metal.com/nickel",
    "https://price.metal.com/Nickel",
)
DEFAULT_INTERVAL_MINUTES = 24 * 60
DEFAULT_TARGET_LABEL = "SMM Shanghai 1# Nickel Cathode (SMM-NI-RN-001)"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) NickelPriceMailer/1.0"
)

PRICE_TOKEN_RE = re.compile(
    r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d{4,}|\d+(?:\.\d+)?)(?:-\d{1,3}(?:,\d{3})*|\.\d+)?%?$"
)
DATE_TOKEN_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}",
    re.IGNORECASE,
)
UNIT_RE = re.compile(
    r"(?:CNY|USD|RMB|\$|¥)\s*/?\s*(?:mt|t|ton|lb)?|yuan/mt|usd/mt|cny/mt",
    re.IGNORECASE,
)


class ConfigError(RuntimeError):
    """Raised when required environment configuration is missing."""


class FetchError(RuntimeError):
    """Raised when a metal.com page cannot be fetched."""


class SheetsError(RuntimeError):
    """Raised when Google Sheets cannot be updated."""


@dataclasses.dataclass(frozen=True)
class PriceRow:
    """A price-like line extracted from a metal.com page."""

    label: str
    value: str | None = None
    unit: str | None = None
    change: str | None = None
    date: str | None = None

    def as_text(self) -> str:
        parts = [self.label]
        if self.value:
            parts.append(f"price/avg: {self.value}")
        if self.unit:
            parts.append(f"unit: {self.unit}")
        if self.change:
            parts.append(f"change: {self.change}")
        if self.date:
            parts.append(f"date: {self.date}")
        return " | ".join(parts)


@dataclasses.dataclass(frozen=True)
class PriceSnapshot:
    """Extracted data and metadata for one source URL."""

    source_url: str
    fetched_at_utc: dt.datetime
    title: str | None
    rows: tuple[PriceRow, ...]
    raw_excerpt: str

    @property
    def has_price_rows(self) -> bool:
        return bool(self.rows)

    def digest(self) -> str:
        relevant_text = "\n".join(row.as_text() for row in self.rows) or self.raw_excerpt
        return hashlib.sha256(relevant_text.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class MailConfig:
    smtp_host: str
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    sender: str
    recipients: tuple[str, ...]
    use_starttls: bool
    use_ssl: bool


@dataclasses.dataclass(frozen=True)
class SheetsConfig:
    webhook_url: str
    shared_secret: str | None


@dataclasses.dataclass(frozen=True)
class AppConfig:
    urls: tuple[str, ...]
    interval_minutes: int
    request_timeout_seconds: int
    user_agent: str
    state_file: str | None
    send_only_on_change: bool
    target_label: str | None
    mail: MailConfig | None
    sheets: SheetsConfig | None


class TextExtractor(HTMLParser):
    """Collect human-visible text from HTML while ignoring noisy elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = normalize_space(html.unescape(data))
        if text:
            self._parts.append(text)

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self._parts)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


def env_csv(name: str, default: Iterable[str] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    values = raw.split(",") if raw is not None and raw.strip() else list(default)
    return tuple(item.strip() for item in values if item.strip())


def normalize_smtp_password(smtp_host: str, smtp_username: str | None, password: str | None) -> str | None:
    if not password:
        return password
    # Gmail displays app passwords in groups with spaces, but SMTP expects the
    # compact 16-character value. Preserve spaces for non-Gmail providers.
    host = smtp_host.lower()
    username = (smtp_username or "").lower()
    if host.endswith("gmail.com") or username.endswith("@gmail.com"):
        return re.sub(r"\s+", "", password)
    return password


def load_mail_config() -> MailConfig | None:
    if env_bool("NICKEL_DISABLE_EMAIL", False):
        return None
    recipients = env_csv("NICKEL_EMAIL_TO")
    smtp_host = os.getenv("NICKEL_SMTP_HOST", "").strip()
    sender = os.getenv("NICKEL_EMAIL_FROM", "").strip()
    if not smtp_host and not sender and not recipients:
        return None

    missing = []
    if not smtp_host:
        missing.append("NICKEL_SMTP_HOST")
    if not sender:
        missing.append("NICKEL_EMAIL_FROM")
    if not recipients:
        missing.append("NICKEL_EMAIL_TO")
    if missing:
        raise ConfigError("Missing email environment variables: " + ", ".join(missing))

    use_ssl = env_bool("NICKEL_SMTP_SSL", False)
    default_port = 465 if use_ssl else 587
    smtp_username = os.getenv("NICKEL_SMTP_USERNAME") or None
    smtp_password = normalize_smtp_password(
        smtp_host=smtp_host,
        smtp_username=smtp_username,
        password=os.getenv("NICKEL_SMTP_PASSWORD") or None,
    )
    return MailConfig(
        smtp_host=smtp_host,
        smtp_port=env_int("NICKEL_SMTP_PORT", default_port),
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        sender=sender,
        recipients=recipients,
        use_starttls=env_bool("NICKEL_SMTP_STARTTLS", not use_ssl),
        use_ssl=use_ssl,
    )


def load_sheets_config() -> SheetsConfig | None:
    webhook_url = os.getenv("NICKEL_SHEETS_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return None
    return SheetsConfig(
        webhook_url=webhook_url,
        shared_secret=os.getenv("NICKEL_SHEETS_SHARED_SECRET") or None,
    )


def load_config() -> AppConfig:
    mail = load_mail_config()
    sheets = load_sheets_config()
    if not mail and not sheets:
        raise ConfigError(
            "Configure at least one destination: email SMTP variables or NICKEL_SHEETS_WEBHOOK_URL"
        )

    return AppConfig(
        urls=env_csv("NICKEL_PRICE_URLS", DEFAULT_URLS),
        interval_minutes=env_int("NICKEL_INTERVAL_MINUTES", DEFAULT_INTERVAL_MINUTES),
        request_timeout_seconds=env_int("NICKEL_REQUEST_TIMEOUT_SECONDS", 30),
        user_agent=os.getenv("NICKEL_USER_AGENT", DEFAULT_USER_AGENT),
        state_file=os.getenv("NICKEL_STATE_FILE") or ".nickel_price_mailer.state",
        send_only_on_change=env_bool("NICKEL_SEND_ONLY_ON_CHANGE", False),
        target_label=os.getenv("NICKEL_TARGET_LABEL", DEFAULT_TARGET_LABEL).strip() or None,
        mail=mail,
        sheets=sheets,
    )


def fetch_page(url: str, timeout_seconds: int, user_agent: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.metal.com",
            "Referer": "https://www.metal.com/nickel",
            "Source-Type": "pc",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise FetchError(f"Unable to fetch {url}: {exc}") from exc


def extract_title(page_html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return normalize_space(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))))


def extract_text_parts(page_html: str) -> tuple[str, ...]:
    parser = TextExtractor()
    parser.feed(page_html)
    return tuple(part for part in parser.parts if part)


def is_price_token(token: str) -> bool:
    cleaned = token.strip().strip(",:;()[]")
    if not PRICE_TOKEN_RE.match(cleaned):
        return False
    if cleaned.endswith("%"):
        return False
    numeric = cleaned.replace(",", "").lstrip("+-")
    if numeric.isdigit() and 1900 <= int(numeric) <= 2100:
        return False
    if numeric.isdigit() and int(numeric) < 100 and "," not in cleaned and "." not in cleaned and "-" not in cleaned:
        return False
    return True


def first_matching(pattern: re.Pattern[str], values: Iterable[str]) -> str | None:
    for value in values:
        match = pattern.search(value)
        if match:
            return normalize_space(match.group(0))
    return None


def find_price_value(values: Iterable[str]) -> str | None:
    for value in values:
        if DATE_TOKEN_RE.search(value):
            continue
        for token in re.split(r"\s+", value):
            cleaned = token.strip().strip(",:;()[]")
            if is_price_token(cleaned):
                return cleaned
    return None


def find_change(values: Iterable[str]) -> str | None:
    for value in values:
        for token in re.split(r"\s+", value):
            cleaned = token.strip().strip(",:;()[]")
            if cleaned.startswith(("+", "-")) and PRICE_TOKEN_RE.match(cleaned):
                return cleaned
    return None


def collapse_label(parts: Iterable[str]) -> str:
    label = " ".join(normalize_space(part) for part in parts if normalize_space(part))
    label = re.sub(r"\s+Price Description\b", "", label, flags=re.IGNORECASE)
    return label[:140].strip(" -|")


def extract_price_rows(parts: tuple[str, ...]) -> tuple[PriceRow, ...]:
    rows: list[PriceRow] = []
    seen: set[str] = set()

    for index, part in enumerate(parts):
        lowered = part.lower()
        if "nickel" not in lowered or "http" in lowered:
            continue
        if (
            lowered in {"nickel prices", "nickel price", "nickel price chart"}
            or lowered.startswith("nickel prices chart")
            or lowered.startswith("nickel price chart")
            or lowered.startswith("[smm")
            or "market flash" in lowered
            or "price of nickel per" in lowered
        ):
            continue
        if len(part) > 180:
            continue

        window = parts[index : index + 12]
        value = find_price_value(window[1:]) or find_price_value([part])
        unit = first_matching(UNIT_RE, window)
        change = find_change(window[1:])
        date = first_matching(DATE_TOKEN_RE, window)

        if not value and not unit and not date:
            continue

        label_parts = [part]
        if len(part) < 45 and index + 1 < len(parts) and not is_price_token(parts[index + 1]):
            next_part = parts[index + 1]
            if "nickel" in next_part.lower() and len(next_part) < 100:
                label_parts.append(next_part)
        label = collapse_label(label_parts)
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(PriceRow(label=label, value=value, unit=unit, change=change, date=date))
        if len(rows) >= 12:
            break

    return tuple(rows)


def make_raw_excerpt(parts: tuple[str, ...]) -> str:
    nickel_parts = [part for part in parts if "nickel" in part.lower()]
    selected = nickel_parts[:8] if nickel_parts else parts[:12]
    return "\n".join(selected)[:2_000]


def iter_products(node: object) -> Iterable[dict[str, object]]:
    if isinstance(node, dict):
        products = node.get("products")
        if isinstance(products, list):
            for product in products:
                if isinstance(product, dict):
                    yield product
        for value in node.values():
            yield from iter_products(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_products(item)


def pick_price_value(price: dict[str, object]) -> str | None:
    average = stringify(price.get("average"))
    low = stringify(price.get("low"))
    high = stringify(price.get("high"))
    if average and low and high:
        return f"{average} ({low}-{high})"
    if average:
        return average
    for key in ("mid_rate", "rate", "last", "close", "price", "sell", "buy"):
        value = stringify(price.get(key))
        if value:
            return value
    if low and high:
        return f"{low}-{high}"
    return None


def stringify(value: object) -> str | None:
    if value is None:
        return None
    text = normalize_space(str(value))
    return text or None


def product_to_price_row(product: dict[str, object]) -> PriceRow | None:
    name = stringify(product.get("product_name"))
    if not name or "nickel" not in name.lower():
        return None

    price = product.get("newest_price")
    if not isinstance(price, dict):
        return None

    product_code = stringify(product.get("product_code"))
    label = name if not product_code else f"{name} ({product_code})"
    value = pick_price_value(price)
    unit = stringify(product.get("unit")) or stringify(product.get("unit_origin"))
    change = stringify(price.get("change"))
    change_percent = stringify(price.get("change_rate_percent"))
    if change and change_percent:
        change = f"{change} ({change_percent})"
    elif change_percent:
        change = change_percent
    date = stringify(price.get("renew_date"))
    renew_time = stringify(price.get("renew_time"))
    if date and renew_time:
        date = f"{date} {renew_time}"

    if not value and not change and not date:
        return None
    return PriceRow(label=label, value=value, unit=unit, change=change, date=date)


def parse_json_snapshot(source_url: str, response_text: str) -> PriceSnapshot:
    payload = json.loads(response_text)
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    rows: list[PriceRow] = []
    seen: set[str] = set()
    for product in iter_products(data):
        row = product_to_price_row(product)
        if not row or row.label.lower() in seen:
            continue
        seen.add(row.label.lower())
        rows.append(row)
        if len(rows) >= 20:
            break

    excerpt_source = [row.as_text() for row in rows] or [response_text[:2_000]]
    return PriceSnapshot(
        source_url=source_url,
        fetched_at_utc=dt.datetime.now(dt.timezone.utc),
        title="metal.com nickel price API",
        rows=tuple(rows),
        raw_excerpt="\n".join(excerpt_source)[:2_000],
    )


def parse_snapshot(source_url: str, page_html: str) -> PriceSnapshot:
    stripped = page_html.lstrip()
    if stripped.startswith(("{", "[")):
        return parse_json_snapshot(source_url, page_html)

    parts = extract_text_parts(page_html)
    return PriceSnapshot(
        source_url=source_url,
        fetched_at_utc=dt.datetime.now(dt.timezone.utc),
        title=extract_title(page_html),
        rows=extract_price_rows(parts),
        raw_excerpt=make_raw_excerpt(parts),
    )


def filter_snapshots_by_target(
    snapshots: Iterable[PriceSnapshot], target_label: str | None
) -> tuple[PriceSnapshot, ...]:
    if not target_label:
        return tuple(snapshots)

    filtered: list[PriceSnapshot] = []
    for snapshot in snapshots:
        rows = tuple(row for row in snapshot.rows if row.label == target_label)
        if rows:
            filtered.append(dataclasses.replace(snapshot, rows=rows))
    if not filtered:
        raise FetchError(f"Target nickel row not found: {target_label}")
    return tuple(filtered)


def fetch_snapshots(config: AppConfig) -> tuple[PriceSnapshot, ...]:
    snapshots: list[PriceSnapshot] = []
    errors: list[str] = []
    for url in config.urls:
        try:
            page_html = fetch_page(url, config.request_timeout_seconds, config.user_agent)
            snapshots.append(parse_snapshot(url, page_html))
        except FetchError as exc:
            errors.append(str(exc))
    if not snapshots:
        raise FetchError("; ".join(errors) if errors else "No price sources configured")
    snapshots_with_rows = tuple(snapshot for snapshot in snapshots if snapshot.has_price_rows)
    return snapshots_with_rows or tuple(snapshots)


def build_email_body(snapshots: Iterable[PriceSnapshot]) -> str:
    lines = [
        "Nickel price update from metal.com",
        "",
        f"Generated at: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
    ]
    for snapshot in snapshots:
        lines.extend(
            [
                f"Source: {snapshot.source_url}",
                f"Fetched at: {snapshot.fetched_at_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            ]
        )
        if snapshot.title:
            lines.append(f"Page title: {snapshot.title}")
        if snapshot.rows:
            lines.append("Extracted price rows:")
            lines.extend(f"- {row.as_text()}" for row in snapshot.rows)
        else:
            lines.extend(
                [
                    "No structured price rows were extracted. Page excerpt:",
                    snapshot.raw_excerpt or "(empty page text)",
                ]
            )
        lines.append("")

    lines.append("This email was generated automatically by nickel_price_mailer.py.")
    return "\n".join(lines)


def build_subject(snapshots: Iterable[PriceSnapshot]) -> str:
    for snapshot in snapshots:
        for row in snapshot.rows:
            if row.value:
                label = row.label[:60]
                return f"Nickel price update: {label} {row.value}"
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    return f"Nickel price update - {today}"


def google_sheet_rows(snapshots: Iterable[PriceSnapshot]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for snapshot in snapshots:
        fetched_at = snapshot.fetched_at_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        for row in snapshot.rows:
            rows.append(
                {
                    "fetched_at_utc": fetched_at,
                    "value": row.value or "",
                    "unit": row.unit or "",
                    "price_date": row.date or "",
                }
            )
    return rows


def post_to_google_sheets(config: SheetsConfig, snapshots: Iterable[PriceSnapshot], timeout_seconds: int) -> int:
    rows = google_sheet_rows(snapshots)
    if not rows:
        raise SheetsError("No nickel price rows available to write to Google Sheets")

    payload = {
        "secret": config.shared_secret,
        "rows": rows,
    }
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        config.webhook_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                raise SheetsError(f"Google Sheets webhook failed with HTTP {response.status}: {body}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SheetsError(f"Unable to update Google Sheets: {exc}") from exc
    return len(rows)


def send_email(mail: MailConfig, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail.sender
    message["To"] = ", ".join(mail.recipients)
    message.set_content(body)

    if mail.use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(mail.smtp_host, mail.smtp_port, context=context) as server:
            login_if_configured(server, mail)
            server.send_message(message)
        return

    with smtplib.SMTP(mail.smtp_host, mail.smtp_port) as server:
        if mail.use_starttls:
            server.starttls(context=ssl.create_default_context())
        login_if_configured(server, mail)
        server.send_message(message)


def login_if_configured(server: smtplib.SMTP, mail: MailConfig) -> None:
    if mail.smtp_username and mail.smtp_password:
        server.login(mail.smtp_username, mail.smtp_password)


def combined_digest(snapshots: Iterable[PriceSnapshot]) -> str:
    digest = hashlib.sha256()
    for snapshot in snapshots:
        digest.update(snapshot.source_url.encode("utf-8"))
        digest.update(snapshot.digest().encode("utf-8"))
    return digest.hexdigest()


def read_previous_digest(state_file: str | None) -> str | None:
    if not state_file:
        return None
    try:
        with open(state_file, "r", encoding="utf-8") as handle:
            return handle.read().strip() or None
    except FileNotFoundError:
        return None


def write_digest(state_file: str | None, digest: str) -> None:
    if not state_file:
        return
    with open(state_file, "w", encoding="utf-8") as handle:
        handle.write(digest + "\n")


def run_once(config: AppConfig) -> bool:
    """Fetch prices and update every configured destination."""

    snapshots = filter_snapshots_by_target(fetch_snapshots(config), config.target_label)
    digest = combined_digest(snapshots)
    if config.send_only_on_change and digest == read_previous_digest(config.state_file):
        print("No nickel price change detected; destinations not updated.", flush=True)
        return False

    actions: list[str] = []
    if config.sheets:
        row_count = post_to_google_sheets(config.sheets, snapshots, config.request_timeout_seconds)
        actions.append(f"Google Sheets updated with {row_count} rows")
    if config.mail:
        send_email(config.mail, build_subject(snapshots), build_email_body(snapshots))
        actions.append("email sent")

    write_digest(config.state_file, digest)
    print("Nickel price update complete: " + "; ".join(actions) + ".", flush=True)
    return True


def run_forever(config: AppConfig) -> None:
    while True:
        try:
            run_once(config)
        except Exception as exc:  # noqa: BLE001 - keep unattended scheduler alive.
            print(f"Nickel price update failed: {exc}", file=sys.stderr, flush=True)
        time.sleep(config.interval_minutes * 60)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send recurring nickel price updates from metal.com.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="send one update to configured destinations and exit; useful for cron or manual testing",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="validate environment variables and print non-secret configuration",
    )
    return parser


def print_config(config: AppConfig) -> None:
    print("Nickel price updater configuration:")
    print(f"  URLs: {', '.join(config.urls)}")
    print(f"  Interval minutes: {config.interval_minutes}")
    print(f"  Request timeout seconds: {config.request_timeout_seconds}")
    print(f"  Send only on change: {config.send_only_on_change}")
    print(f"  Target label: {config.target_label or 'all nickel rows'}")
    print(f"  State file: {config.state_file}")
    print(f"  Google Sheets configured: {bool(config.sheets)}")
    if config.sheets:
        print(f"  Google Sheets shared secret configured: {bool(config.sheets.shared_secret)}")
    print(f"  Email configured: {bool(config.mail)}")
    if config.mail:
        print(f"  SMTP host: {config.mail.smtp_host}:{config.mail.smtp_port}")
        print(f"  SMTP SSL: {config.mail.use_ssl}")
        print(f"  SMTP STARTTLS: {config.mail.use_starttls}")
        print(f"  SMTP username configured: {bool(config.mail.smtp_username)}")
        print(f"  Sender: {config.mail.sender}")
        print(f"  Recipients: {', '.join(config.mail.recipients)}")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        config = load_config()
        if args.print_config:
            print_config(config)
            return 0
        if args.once or env_bool("NICKEL_RUN_ONCE", False):
            run_once(config)
            return 0
        run_forever(config)
        return 0
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except FetchError as exc:
        print(f"Fetch error: {exc}", file=sys.stderr)
        return 3
    except smtplib.SMTPException as exc:
        print(f"Email error: {exc}", file=sys.stderr)
        return 4
    except SheetsError as exc:
        print(f"Google Sheets error: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
