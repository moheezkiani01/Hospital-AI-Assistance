"""Read-only preflight checks for Hospital AI Assistant's FastAPI backend.

Usage from backend/:
    python scripts/backend_preflight.py
    python scripts/backend_preflight.py --api-url http://127.0.0.1:8000
    python scripts/backend_preflight.py --db path/to/hospital_ai.db

Does not send messages, create appointments, modify settings, change OTP, or
contact LLM providers. Never prints keys, tokens, names or patient records.

Exit code: 0 = no blocking failures, 1 = at least one blocking failure.
Warnings are not a declaration that production is safe.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


@dataclass
class Check:
    status: str  # PASS | WARN | FAIL
    title: str
    detail: str


class Reporter:
    def __init__(self):
        self.results: list[Check] = []

    def add(self, status: str, title: str, detail: str):
        self.results.append(Check(status, title, detail))

    def print_results(self) -> int:
        for check in self.results:
            print(f"{check.status:4}  {check.title}: {check.detail}")
        counts = {kind: sum(r.status == kind for r in self.results) for kind in ("PASS", "WARN", "FAIL")}
        print("\nResults: " + ", ".join(f"{k.lower()}={v}" for k, v in counts.items()))
        if counts["FAIL"]:
            print("Status: NOT ready. Resolve blocking failures before a public deployment.")
        else:
            print("Status: No blocking preflight failures found; live integration and security review remain necessary.")
        return 1 if counts["FAIL"] else 0


def dotenv_values(path: Path) -> dict[str, str]:
    """Minimal .env reader for diagnostics; no variables are executed or printed."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "").isalnum():
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value[-1:] == value[:1]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[name] = value
    return values


def setting(values: dict[str, str], name: str, fallback: str = "") -> str:
    return os.environ.get(name, values.get(name, fallback)).strip()


def enabled(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


def valid_secret(value: str) -> bool:
    placeholders = {
        "", "changeme", "change-me", "change-this-secret-key-later",
        "secret", "your-secret-key", "replace-me",
    }
    return len(value.strip()) >= 32 and value.strip().lower() not in placeholders


def check_config(values: dict[str, str], report: Reporter):
    env = setting(values, "APP_ENV", "development").lower()
    production = env in ("prod", "production")
    report.add("PASS" if not production else "WARN", "Application mode",
               "development (not production)" if not production else "production; additional deployment review required")

    secret = setting(values, "SECRET_KEY")
    report.add("PASS" if valid_secret(secret) else "FAIL", "Stable JWT secret",
               "at least 32 characters, non-placeholder (value not displayed)" if valid_secret(secret) else
               "missing/short/placeholder; admin sessions may reset after restart")

    rate_limit = enabled(setting(values, "RATE_LIMIT_ENABLED", "true"))
    report.add("PASS" if rate_limit else "FAIL", "Rate limiting",
               "enabled" if rate_limit else "disabled")

    cors = [x.strip() for x in setting(values, "CORS_ORIGINS", "").split(",") if x.strip()]
    if not cors:
        report.add("WARN", "CORS origins", "not specified in .env; inspect application defaults")
    elif "*" in cors or any(x == "null" for x in cors):
        report.add("FAIL", "CORS origins", "wildcard or null origin configured")
    else:
        report.add("PASS", "CORS origins", f"{len(cors)} explicit origin(s)")

    active_providers = []
    key_for = {"gemini": "GEMINI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "custom": "HCN_API_KEY"}
    for provider, key in key_for.items():
        if setting(values, key):
            active_providers.append(provider)
    report.add("PASS" if active_providers else "FAIL", "AI credentials",
               "configured for: " + ", ".join(active_providers) if active_providers else
               "no configured AI provider key")
    priority = [setting(values, name).lower() for name in
                ("LLM_PRIMARY_PROVIDER", "LLM_SECONDARY_PROVIDER", "LLM_TERTIARY_PROVIDER")]
    priority = [name for name in priority if name]
    missing = [name for name in priority if name not in key_for or not setting(values, key_for.get(name, ""))]
    if missing:
        report.add("WARN", "AI fallback configuration",
                   "provider priority includes an unconfigured/unknown provider: " + ", ".join(missing))
    elif len(active_providers) < 2:
        report.add("WARN", "AI fallback configuration",
                   "fewer than two configured independent providers; outages may interrupt chat")
    else:
        report.add("PASS", "AI fallback configuration", "multiple providers have credentials (live access unverified)")

    if production:
        # OTP implementation is intentionally not changed by this checker.
        verified = enabled(setting(values, "OTP_REQUIRED_FOR_SENSITIVE_ACTIONS", "false"))
        if not verified:
            report.add("FAIL", "Patient identity protection",
                       "OTP not required; do not expose sensitive appointment actions publicly")
        else:
            report.add("WARN", "Patient identity protection",
                       "OTP marked enabled; verify actual delivery and complete authorization flow")
        if enabled(setting(values, "ALLOW_INSECURE_PUBLIC_ACTIONS", "false")):
            report.add("FAIL", "Insecure public actions",
                       "explicit bypass is enabled; disable before handling real patients")
        if enabled(setting(values, "TRUST_PROXY_HEADERS", "false")):
            report.add("WARN", "Proxy trust", "confirm only a trusted reverse proxy can reach the API")
    else:
        report.add("WARN", "Patient identity protection",
                   "OTP is postponed; test with synthetic data only, not real patient records")


def readonly_sqlite(db_path: Path):
    uri = db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.execute("PRAGMA query_only=ON")
    return connection


def existing_tables(db: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}


def check_database(path: Path, report: Reporter):
    if not path.is_file():
        report.add("FAIL", "Database file", "SQLite file not found (verify DATABASE_URL and working directory)")
        return
    try:
        with closing(readonly_sqlite(path)) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                report.add("FAIL", "SQLite integrity", "database reported integrity problems")
                return
            report.add("PASS", "SQLite integrity", "integrity_check = ok")
            fk_errors = db.execute("PRAGMA foreign_key_check").fetchall()
            report.add("FAIL" if fk_errors else "PASS", "Foreign key integrity",
                       f"{len(fk_errors)} violation(s)" if fk_errors else "no violations")

            tables = existing_tables(db)
            essential = {"appointments", "patients", "doctors", "hospitals", "users"}
            missing = sorted(essential - tables)
            if missing:
                report.add("FAIL", "Core tables", "missing: " + ", ".join(missing))
                return
            report.add("PASS", "Core tables", "required tables are present")

            indexes = {str(row[0]) for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='appointments'"
            )}
            required = {"uq_active_appointment_slot", "uq_active_patient_doctor_day"}
            absent = sorted(required - indexes)
            report.add("FAIL" if absent else "PASS", "Booking uniqueness indexes",
                       "missing: " + ", ".join(absent) if absent else "both database constraints exist")

            for title, grouping in (
                ("Occupied-slot duplicates", "hospital_id, doctor_id, appointment_date, appointment_time"),
                ("Same-patient/day duplicates", "hospital_id, patient_id, doctor_id, appointment_date"),
            ):
                sql = f"""SELECT COUNT(*) FROM (
                    SELECT 1 FROM appointments
                    WHERE status IN ('booked', 'confirmed')
                    GROUP BY {grouping}
                    HAVING COUNT(*) > 1
                )"""
                count = int(db.execute(sql).fetchone()[0])
                report.add("FAIL" if count else "PASS", title,
                           f"{count} duplicate group(s)" if count else "none")
    except (sqlite3.Error, OSError) as exc:
        report.add("FAIL", "Database inspection",
                   f"could not complete read-only inspection ({type(exc).__name__})")


def check_backup(folder: Path, report: Reporter, days: int = 7):
    if not folder.is_dir():
        report.add("WARN", "Database backups", "backup directory not found")
        return
    candidates = sorted((p for p in folder.glob("*.sqlite3") if p.is_file()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        report.add("WARN", "Database backups", "no .sqlite3 backup files found")
        return
    latest = candidates[0]
    age_days = (datetime.now(timezone.utc).timestamp() - latest.stat().st_mtime) / 86400
    try:
        with closing(readonly_sqlite(latest)) as db:
            result = db.execute("PRAGMA integrity_check").fetchone()
            ok = bool(result and result[0] == "ok")
            tables = existing_tables(db) if ok else set()
            ok = ok and "appointments" in tables
        report.add("PASS" if ok and age_days <= days else "WARN", "Latest database backup",
                   ("verified; " if ok else "invalid/unreadable schema; ") +
                   f"age {max(0, age_days):.1f} days (filename: {latest.name})")
    except (sqlite3.Error, OSError):
        report.add("FAIL", "Latest database backup", "could not open backup")


def check_live_api(url: str, report: Reporter):
    base = url.rstrip("/")
    if urlparse(base).scheme not in {"http", "https"}:
        report.add("FAIL", "Live API", "--api-url must start with http:// or https://")
        return
    try:
        req = Request(base + "/health", headers={"User-Agent": "hospital-ai-preflight/1.0"})
        with urlopen(req, timeout=8) as response:
            healthy = response.status == 200
            report.add("PASS" if healthy else "FAIL", "Live API health",
                       f"HTTP {response.status}")
        req = Request(base + "/api/v1/auth/users", headers={"User-Agent": "hospital-ai-preflight/1.0"})
        try:
            with urlopen(req, timeout=8) as response:
                status = response.status
        except HTTPError as exc:
            status = exc.code
        report.add("PASS" if status in (401, 403) else "FAIL", "Unauthenticated admin access",
                   f"HTTP {status}; expected 401 or 403")
    except (HTTPError, URLError, TimeoutError, OSError):
        report.add("FAIL", "Live API", "could not contact API or health request failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="Override SQLite database file")
    parser.add_argument("--api-url", help="Optional running FastAPI URL (GET checks only)")
    parser.add_argument("--backups", type=Path, help="Backup directory (default: backend/backups)")
    args = parser.parse_args(argv)
    backend = Path(__file__).resolve().parents[1]
    values = dotenv_values(backend / ".env")
    report = Reporter()
    report.add("PASS" if (backend / ".env").is_file() else "WARN", "Environment file",
               "found" if (backend / ".env").is_file() else "missing; checking process environment/defaults")
    check_config(values, report)
    configured = setting(values, "DATABASE_URL", "sqlite:///./hospital_ai.db")
    if args.db:
        db_path = args.db if args.db.is_absolute() else backend / args.db
    elif configured.startswith("sqlite:///"):
        raw = configured.removeprefix("sqlite:///")
        db_path = Path(raw)
        if not db_path.is_absolute():
            db_path = backend / db_path
    else:
        report.add("WARN", "Database inspection", "non-SQLite database: use your database vendor's integrity tooling")
        db_path = None
    if db_path is not None:
        check_database(db_path.resolve(), report)
        backup_dir = args.backups or backend / "backups"
        if not backup_dir.is_absolute():
            backup_dir = backend / backup_dir
        check_backup(backup_dir, report)
    if args.api_url:
        check_live_api(args.api_url, report)
    return report.print_results()


if __name__ == "__main__":
    sys.exit(main())
