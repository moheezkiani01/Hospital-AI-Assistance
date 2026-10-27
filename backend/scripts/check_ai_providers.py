"""Safe Gemini / DeepSeek / custom-provider smoke checks for Hospital AI Assistant.

Run from backend/: 
    python scripts/check_ai_providers.py
    python scripts/check_ai_providers.py --live --provider gemini
    python scripts/check_ai_providers.py --live --provider all
    python scripts/check_ai_providers.py --live --provider deepseek --kind both
    python scripts/check_ai_providers.py --live-fallback

Default checks are offline. Live mode uses only synthetic prompts, may incur API
charges, and never writes to the application database or changes OTP/settings.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import llm_service as llm  # noqa: E402


JSON_PROMPT = (
    'This is a synthetic connectivity test. Reply with valid JSON only: '
    '{"test":"ok"}. Do not add other keys or explanations.'
)
TEXT_PROMPT = (
    'This is a synthetic connectivity test. Reply with just the word READY.'
)


def safe_error(value: str) -> str:
    """Return only a non-sensitive error classification, never raw provider text."""
    raw = str(value or "")
    match = re.search(r"\bHTTP\s+([1-5][0-9]{2})\b", raw, re.I)
    if match:
        return f"HTTP {match.group(1)}"
    lowered = raw.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "not configured" in lowered or "api key" in lowered:
        return "configuration/key error"
    if "connection" in lowered or "resolve" in lowered:
        return "network error"
    if "invalid" in lowered or "json" in lowered:
        return "invalid response"
    return "provider error"


def configured() -> tuple[list[str], dict]:
    status = llm.brain_configuration_status()
    chain = list(llm._configured_providers())
    return chain, status


def has_credentials(name: str, status: dict) -> bool:
    return bool(status.get({
        "gemini": "gemini_configured",
        "deepseek": "deepseek_configured",
        "custom": "hcn_configured",
        "hcn": "hcn_configured",
        "openai": "openai_configured",
    }.get(name, "no_credentials")))


def offline_checks() -> int:
    """Exercise real call_brain_* routing with mocked providers (zero API requests)."""
    passed = 0
    tests = (
        ("503 -> JSON fallback", "json", {"gemini": "PROVIDER_ERROR: Gemini HTTP 503", "deepseek": '{"test":"ok"}'}, False, True),
        ("invalid JSON -> fallback", "json", {"gemini": "not a json object", "deepseek": '{"test":"ok"}'}, False, True),
        ("open circuit -> fallback", "json", {"gemini": '{"test":"ok"}', "deepseek": '{"test":"ok"}'}, True, True),
        ("503 -> text fallback", "text", {"gemini": "PROVIDER_ERROR: Gemini HTTP 503", "deepseek": "READY"}, False, True),
        ("all providers fail safely", "json", {"gemini": "PROVIDER_ERROR: Gemini HTTP 503", "deepseek": "PROVIDER_ERROR: DeepSeek HTTP 503"}, False, False),
    )
    for label, kind, outputs, skip_primary, expect_success in tests:
        attempted = []

        def provider_factory(name):
            def fake(_prompt):
                attempted.append(name)
                return outputs[name]
            return fake

        def choose(name):
            return provider_factory(name)

        def should_skip(name):
            return skip_primary and name == "gemini"

        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(llm, "_configured_providers", return_value=iter(("gemini", "deepseek"))))
                stack.enter_context(patch.object(llm, "_json_provider", side_effect=choose))
                stack.enter_context(patch.object(llm, "_text_provider", side_effect=choose))
                stack.enter_context(patch.object(llm, "_provider_is_temporarily_unavailable", side_effect=should_skip))
                stack.enter_context(patch.object(llm.llm_monitor_service, "record_llm_call", return_value=None))
                stack.enter_context(patch.object(llm.provider_health_service, "record_success", return_value=None))
                stack.enter_context(patch.object(llm.provider_health_service, "record_failure", return_value={"category": "server", "cooldown_seconds": 20}))
                # Suppress the app's normal diagnostic prints: synthetic test details only.
                with contextlib.redirect_stdout(io.StringIO()):
                    result = llm.call_brain_json(JSON_PROMPT) if kind == "json" else llm.call_brain_ai(TEXT_PROMPT)
            success = (isinstance(result, dict) if kind == "json" else result == "READY")
            ok = (success == expect_success and attempted[-1:] == ["deepseek"])
        except Exception:
            ok = False
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        passed += int(ok)
    # Verify the *actual* Gemini adapter fails fast on a simulated HTTP 503.
    # This does not call Google or use an actual credential.
    fake_response = SimpleNamespace(
        status_code=503,
        headers={},
        json=lambda: {"error": {"message": "synthetic overload"}},
        text="synthetic overload",
    )
    try:
        with patch.object(llm, "GEMINI_API_KEY", "synthetic-test-key"):
            with patch.object(llm.requests, "post", return_value=fake_response) as request_mock:
                result = llm.call_gemini_json(JSON_PROMPT)
        ok = "HTTP 503" in str(result) and request_mock.call_count == 1
    except Exception:
        ok = False
    print(f"{'PASS' if ok else 'FAIL'}  Gemini adapter: HTTP 503 causes a single request")
    passed += int(ok)
    total = len(tests) + 1
    print(f"\nOffline provider tests: {passed}/{total} passed; no network or database writes.")
    return 0 if passed == total else 1


def bounded_http_post(timeout: float):
    """Context manager that caps HTTP timeout without modifying production files."""
    original_post = llm.requests.post

    def bounded_post(*args, **kwargs):
        existing = kwargs.get("timeout", timeout)
        if isinstance(existing, (tuple, list)) and len(existing) == 2:
            kwargs["timeout"] = tuple(min(float(part), timeout) for part in existing)
        else:
            kwargs["timeout"] = min(float(existing), timeout)
        return original_post(*args, **kwargs)

    return patch.object(llm.requests, "post", side_effect=bounded_post)


def live_fallback(timeout: float) -> int:
    """Force synthetic primary 503, then make one real secondary provider JSON call.

    No primary network call, monitoring DB write, or patient data is involved.
    """
    chain, status = configured()
    if len(chain) < 2:
        print("FAIL  Set at least two distinct providers in the fallback chain first.")
        return 1
    primary, secondary = chain[:2]
    if not has_credentials(secondary, status):
        print(f"FAIL  Secondary provider {secondary} has no configured credentials.")
        return 1
    secondary_json = llm._json_provider(secondary)
    if secondary_json is None:
        print(f"FAIL  Secondary provider {secondary} has no supported JSON adapter.")
        return 1

    def select_provider(name):
        if name == primary:
            return lambda _prompt: f"PROVIDER_ERROR: {primary} HTTP 503: synthetic overload"
        return secondary_json

    print(f"Live fallback test: simulated {primary} HTTP 503 -> actual {secondary} JSON API")
    print("Only the secondary API will be called. Synthetic prompt; possible API charge.")
    started = perf_counter()
    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(bounded_http_post(timeout))
            stack.enter_context(patch.object(llm, "_configured_providers", return_value=iter((primary, secondary))))
            stack.enter_context(patch.object(llm, "_json_provider", side_effect=select_provider))
            stack.enter_context(patch.object(llm, "_provider_is_temporarily_unavailable", return_value=False))
            stack.enter_context(patch.object(llm.llm_monitor_service, "record_llm_call", return_value=None))
            stack.enter_context(patch.object(llm.provider_health_service, "record_failure", return_value={"cooldown_seconds": 20, "category": "server"}))
            stack.enter_context(patch.object(llm.provider_health_service, "record_success", return_value=None))
            with contextlib.redirect_stdout(io.StringIO()):
                result = llm.call_brain_json(JSON_PROMPT)
        valid = isinstance(result, dict) and str(result.get("test", "")).lower() == "ok"
    except Exception:
        valid = False
    print(f"{'PASS' if valid else 'FAIL'}  Secondary handled fallback in {perf_counter()-started:.1f}s")
    return 0 if valid else 1


def live_checks(target: str, kind: str, timeout: float) -> int:
    chain, status = configured()
    if target == "all":
        names = chain
    else:
        names = [target]
    if not names:
        print("FAIL  No provider names are configured.")
        return 1

    print("Live probe: synthetic messages only; potential API usage charges.")
    print("Configured fallback order:", " -> ".join(chain) or "none")
    print("This checks provider adapters individually; offline tests verify routing.")

    failures = 0
    with bounded_http_post(timeout):
        for name in names:
            if not has_credentials(name, status):
                print(f"SKIP  {name}: credentials not configured")
                failures += 1
                continue
            for mode in (["json", "text"] if kind == "both" else [kind]):
                fn = llm._json_provider(name) if mode == "json" else llm._text_provider(name)
                if fn is None:
                    print(f"FAIL  {name} {mode}: unsupported provider")
                    failures += 1
                    continue
                start = perf_counter()
                try:
                    # Never print the raw generated message, an HTTP body, or an API key.
                    with contextlib.redirect_stdout(io.StringIO()):
                        raw = fn(JSON_PROMPT if mode == "json" else TEXT_PROMPT)
                    if llm.is_failure_text(raw):
                        valid, detail = False, safe_error(raw)
                    elif mode == "json":
                        payload = llm.extract_json_from_text(raw)
                        valid = isinstance(payload, dict) and str(payload.get("test", "")).lower() == "ok"
                        detail = "JSON validated" if valid else "unexpected JSON"
                    else:
                        valid = bool(raw) and "ready" in str(raw).lower()
                        detail = "text validated" if valid else "unexpected text"
                except Exception as exc:
                    valid, detail = False, safe_error(type(exc).__name__)
                elapsed = perf_counter() - start
                print(f"{'PASS' if valid else 'FAIL'}  {name} {mode}: {detail}; {elapsed:.1f}s")
                failures += int(not valid)
    print("\nLive result:", "all requested probes passed" if failures == 0 else f"{failures} probe(s) failed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hospital AI Assistant provider validation")
    parser.add_argument("--live", action="store_true", help="Make actual API calls using the local backend/.env")
    parser.add_argument("--live-fallback", action="store_true", help="Simulate primary 503 and call real secondary provider once")
    parser.add_argument("--provider", choices=("all", "gemini", "deepseek", "custom", "hcn", "openai"), default="gemini")
    parser.add_argument("--kind", choices=("json", "text", "both"), default="json")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per HTTP request timeout, 5 to 30 seconds")
    args = parser.parse_args()
    args.timeout = max(5.0, min(30.0, args.timeout))
    chain, status = configured()
    print("Provider chain:", " -> ".join(chain) or "none")
    for name in dict.fromkeys(chain):
        print(f"  {name}: {'credentials configured' if has_credentials(name, status) else 'missing credentials'}")
    if args.live_fallback:
        return live_fallback(args.timeout)
    if args.live:
        return live_checks(args.provider, args.kind, args.timeout)
    print("No live provider calls requested.\n")
    return offline_checks()


if __name__ == "__main__":
    raise SystemExit(main())
