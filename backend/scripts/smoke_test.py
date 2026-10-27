"""End-to-end smoke test against a RUNNING API. Run this after starting the server.

    python scripts/smoke_test.py                       # http://127.0.0.1:8000
    python scripts/smoke_test.py --base-url https://api.example.org
    SMOKE_ADMIN_EMAIL=... SMOKE_ADMIN_PASSWORD=... python scripts/smoke_test.py   # also tests admin login

It sends a handful of harmless requests (one chat message, one wrong login) and prints
PASS / FAIL / SKIP for each check. Exit code is 1 if anything FAILED.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

import requests

results = []


def check(name, ok, detail=""):
    results.append((name, "PASS" if ok else "FAIL", detail))


def skip(name, detail=""):
    results.append((name, "SKIP", detail))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--hospital-id", type=int, default=1)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    api = f"{base}/api/v1"
    http = requests.Session()
    http.headers["User-Agent"] = "hospital-ai-smoke-test"

    # 1. server + database up
    try:
        r = http.get(f"{base}/health", timeout=10)
        check("health endpoint", r.status_code == 200 and r.json().get("status") == "ok", f"HTTP {r.status_code}")
    except requests.RequestException as exc:
        check("health endpoint", False, type(exc).__name__)
        report()
        return 1

    # 2. public read
    r = http.get(f"{api}/public/doctors", params={"hospital_id": args.hospital_id}, timeout=10)
    doctors = r.json() if r.ok else []
    check("public doctors list", r.ok and isinstance(doctors, list), f"HTTP {r.status_code}, {len(doctors)} doctor(s)")

    # 3. auth: wrong password must be rejected, protected route must need a token
    r = http.post(f"{api}/auth/login", json={"email": "nobody@example.invalid", "password": "wrong-password"}, timeout=10)
    check("wrong login is rejected", r.status_code == 401, f"HTTP {r.status_code}")

    r = http.get(f"{api}/auth/users", timeout=10)
    check("protected route needs a token", r.status_code in (401, 403), f"HTTP {r.status_code}")

    # 4. forged token signed with the OLD default secret must not work
    forged = _forged_token_with_old_default_secret()
    if forged:
        r = http.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {forged}"}, timeout=10)
        check("token signed with the old default secret is rejected", r.status_code in (401, 403), f"HTTP {r.status_code}")
    else:
        skip("old-default-secret token", "PyJWT not installed")

    # 5. chat (needs an LLM key; a polite 'unavailable' answer still proves the pipeline runs)
    r = http.post(
        f"{api}/chat/message",
        json={"hospital_id": args.hospital_id, "message": "What are the hospital timings?", "session_id": f"smoke_{uuid.uuid4().hex[:10]}"},
        timeout=90,
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check("chat answers", r.status_code == 200 and bool(body.get("answer")), f"HTTP {r.status_code}, intent={body.get('intent')}")

    # 6. optional: real admin login
    email, password = os.environ.get("SMOKE_ADMIN_EMAIL"), os.environ.get("SMOKE_ADMIN_PASSWORD")
    if email and password:
        r = http.post(f"{api}/auth/login", json={"email": email, "password": password}, timeout=10)
        if r.ok:
            token = r.json().get("access_token", "")
            me = http.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
            check("admin login + /auth/me", me.ok and me.json().get("role") == "admin", f"HTTP {me.status_code}")
        else:
            check("admin login + /auth/me", False, f"login HTTP {r.status_code}")
    else:
        skip("admin login + /auth/me", "set SMOKE_ADMIN_EMAIL / SMOKE_ADMIN_PASSWORD to enable")

    # 7. rate limit on login (runs LAST: it deliberately exhausts the login bucket for ~1 minute)
    codes = [
        http.post(f"{api}/auth/login", json={"email": "x@example.invalid", "password": "x"}, timeout=10).status_code
        for _ in range(15)
    ]
    check("login is rate limited", 429 in codes, f"status codes seen: {sorted(set(codes))}")

    return report()


def _forged_token_with_old_default_secret():
    try:
        import time
        import jwt  # PyJWT

        return jwt.encode(
            {"sub": "1", "role": "admin", "hospital_id": None, "exp": int(time.time()) + 600},
            "change-this-secret-key-later",
            algorithm="HS256",
        )
    except Exception:
        return None


def report() -> int:
    width = max(len(name) for name, _, _ in results)
    for name, status, detail in results:
        print(f"{status:<5} {name:<{width}}  {detail}")
    failed = [n for n, s, _ in results if s == "FAIL"]
    print(f"\n{len(failed)} failed" if failed else "\nAll checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
