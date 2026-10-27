# Change log: hardening and setup pass

This file lists every change made to the project you uploaded, why it was made, and what was
actually run to check it. Nothing here touches your `.env`, your database or your uploads.

## What was and was not executed

The sandbox this work was done in could not install Python packages (the package index was
blocked), so the backend could not be started and the full test suite could not be run there.

| Check | Result |
|---|---|
| `py_compile` on every backend `.py` file | Run, passes |
| `test_security_policy.py` (39 cases, standard library only) | Run, passes |
| `test_provider_cooldowns.py` (4 cases, with a stub config) | Run, passes |
| Strict phone matching (old vs new behaviour, exercised directly) | Run; the old code accepted 5-7 digit suffixes, the new code does not |
| Orphan-passage purge SQL, on a copy of your SQLite database | Run, removes only passages whose document is gone |
| `node --check` on both frontends | Run, passes |
| `test_phone_verification`, `test_public_verification_lockout`, `test_rag_document_lifecycle`, `test_gemini_key_not_in_url`, `test_config_policy` | Written and compile-checked only (they need the real dependencies) |
| Existing tests, the live API, `scripts/smoke_test.py`, `docker compose build` | **Not run** |
| bcrypt check of whether the stored admin password is still `admin123` | **Not run** (bcrypt unavailable); the new startup check does it at runtime |

Please run `pytest` and `scripts/smoke_test.py` on your machine before relying on any of this.

## Security fixes

| Problem found | Change |
|---|---|
| `SECRET_KEY` defaulted to a public string, so anyone could forge an admin token | `SECRET_KEY` has no default. Development generates a random per-process key and warns; production refuses to start without a 32+ character key. New `app/core/secret_policy.py`, wired into `app/core/config.py`. |
| Default admin login `admin123` documented in the repo | Removed. `backend/scripts/create_admin.py` creates admins with a prompted password. Passwords must be 10+ characters and not common (`auth_service.create_user`). On startup the API checks active admins for well-known weak passwords (`app/core/startup_checks.py`). |
| Cancel / reschedule / status needed only appointment ID + phone, and the phone match accepted very short suffixes | `chat_service.phone_matches` now needs an exact digit match, or the last 10 digits when both numbers have at least 10. |
| Appointment ID + phone could be guessed without limit | Failed verifications are counted per patient (chat) and per appointment (public forms); 5 failures lock that target for 15 minutes (`VERIFY_MAX_FAILURES`, `VERIFY_LOCKOUT_MINUTES`). Comparison uses `hmac.compare_digest`. |
| No rate limiting on unauthenticated endpoints | Per-IP limits on chat, feedback, patient leads, OTP, login and all public booking routes (`app/core/rate_limit.py`, `app/api/rate_limit_deps.py`). Returns HTTP 429 with `Retry-After`. |
| OTP off by default and the production path unsafe | Development default unchanged. In production the API refuses to start unless OTP with a webhook is configured, or `ALLOW_INSECURE_PUBLIC_ACTIONS=true` is set on purpose. |
| Gemini key sent in the URL query string (ends up in logs and error text) | Sent in the `x-goog-api-key` header (`llm_service._gemini_headers`). |
| Provider errors stored with keys in them | `app/core/redact.py` masks keys and tokens before anything is written to `llm_call_logs` or the circuit-breaker state. |
| CORS origins hard-coded | `CORS_ORIGINS` setting. |
| Uploads unbounded | `MAX_UPLOAD_MB` (default 10), checked while copying; partial files are removed. |
| Admin dashboard built inline JavaScript from user text and printed raw server messages | Quotes escaped in the FAQ shortcut; server `detail` text passed through `escapeHTML`. |

## Knowledge base (RAG) integrity

- Deleting a document now also deletes its embedded passages. Before, the bot could keep
  answering from a file the admin had deleted.
- Retrieval ignores any passage whose document no longer exists for that hospital.
- `rag_index_service.purge_orphan_passages` and `scripts/purge_orphan_passages.py` clean up
  passages left behind by earlier deletions. Run the script once on your existing database.

## LLM reliability

- A daily-quota 429 with no retry delay now puts the provider in a 15 minute cooldown
  (`LLM_COOLDOWN_QUOTA_SECONDS`) instead of failing on every message.
- New admin route `GET /api/v1/observability/llm-providers` shows which providers are being skipped.
- Model names were not changed.

## Setup and operations

- New: `GET /health` (checks the database), `backend/.env.example`, `backend/requirements-dev.txt`,
  `backend/pytest.ini`, `docker/backend.Dockerfile`, `docker-compose.yml`, `.dockerignore`,
  `scripts/smoke_test.py`, `sample_data/` (the demo PDF the RAG evaluation uses), `README.md`.
- `requirements.txt` cleaned: removed `google-genai` and `alembic` (not imported anywhere) and a
  duplicate `python-dotenv`; the `passlib==1.7.4` / `bcrypt==4.0.1` pins are kept because newer
  bcrypt breaks passlib.
- Both frontends read `config.js` for the API URL and hospital id instead of a hard-coded address.
- `codehttp.txt` rewritten without credentials.
- `.gitignore` extended (`.pytest_cache`, `backend/data`, evaluation output files).
- Test fix: `test_new_booking_separation.py` used a stale hard-coded date and a slot format
  (`HH:MM`) the code does not produce (`HH:MM:SS`). The test was wrong, not the product code.

## Things deliberately left alone

- `chat_service.py` is large and was patched, not refactored.
- The OTP default stays off in development, because console delivery cannot reach a patient.
- DeepSeek (no balance) and Gemini (quota) account problems are yours to fix.
- The RAG reports in the repo were produced while Gemini was quota-limited (14 of 20 cases had no
  rerank score), so they understate quality. Re-run them with a healthy quota.

## Known limits

- The lockout is per patient or appointment, so a determined attacker can lock a real patient out
  of self-service for 15 minutes. Reception can still help them.
- The rate limiter and lockout counters live in process memory. With more than one worker use Redis.
- The public appointment lookup still says whether the appointment ID exists or the phone is wrong
  (kept for usability); OTP removes the need for that distinction.
- `document_service.py` still imports `shutil`, which is no longer used.

## What you need to do

1. Rotate the DeepSeek, Gemini and HCN keys that were in the zip you shared.
2. Copy your own `.env` into `backend/`, add `SECRET_KEY` (see README for the one-liner) and the new
   settings you want from `.env.example`.
3. Run `python scripts/create_admin.py ...` and move to a strong admin password. Your existing
   admin may still be `admin123`; the API will log a critical warning at startup if so.
4. Run `python scripts/purge_orphan_passages.py` once on your existing database.
5. Run `pytest`, start the API, then `python scripts/smoke_test.py`.
6. For production, set `APP_ENV=production`, configure OTP with an SMS webhook (or consciously set
   `ALLOW_INSECURE_PUBLIC_ACTIONS=true`), and restrict `CORS_ORIGINS` to your real domains.
