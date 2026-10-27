from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import secret_policy


BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "Hospital AI Assistant API"
    DATABASE_URL: str = "sqlite:///./hospital_ai.db"

    # "development" (default) or "production". Production refuses to start with
    # an unsafe configuration (see app/core/secret_policy.py).
    APP_ENV: str = "development"

    # Must be set in backend/.env (>= 32 random characters). If it is empty or
    # still the old placeholder, development mode generates a random per-process
    # key (logins reset on restart) and production mode refuses to start.
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Maximum size of an uploaded knowledge-base document.
    MAX_UPLOAD_MB: int = 10

    # Comma-separated list of browser origins allowed to call the API.
    CORS_ORIGINS: str = (
        "http://127.0.0.1:5500,http://localhost:5500,"
        "http://127.0.0.1:5600,http://localhost:5600"
    )

    # In-memory rate limiting for unauthenticated endpoints (per client IP).
    # Process-local: move to Redis if you run several API workers.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_CHAT_PER_MINUTE: int = 20
    RATE_LIMIT_PUBLIC_PER_MINUTE: int = 30
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10
    # Failed phone verifications allowed per appointment / per client IP before
    # a temporary lockout (stops guessing "appointment ID + phone" pairs).
    VERIFY_MAX_FAILURES: int = 5
    VERIFY_LOCKOUT_MINUTES: int = 15
    # Only trust X-Forwarded-For when the API sits behind your own reverse proxy.
    TRUST_PROXY_HEADERS: bool = False

    # Production only: explicit opt-out that allows cancel/reschedule/status by
    # appointment ID + phone number alone (OTP not enforced). Leave False unless
    # you have accepted that risk.
    ALLOW_INSECURE_PUBLIC_ACTIONS: bool = False

    # LLM providers. Secrets stay in backend/.env, never in source code.
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-flash"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    HCN_API_KEY: str = ""
    HCN_MODEL: str = "DeepSeek-V4-Flash"
    HCN_BASE_URL: str = "https://api.hcnsec.cn/v1"

    # P0: native LLM function/tool routing. DeepSeek is tried first,
    # Gemini second; structured JSON routing remains the fallback.
    ENABLE_NATIVE_TOOL_ROUTING: bool = True

    # P1: provider circuit breaker. After an already-retried provider fails,
    # temporarily skip it so the next patient does not wait on the same outage.
    LLM_CIRCUIT_BREAKER_ENABLED: bool = True
    LLM_COOLDOWN_RATE_LIMIT_SECONDS: int = 45
    LLM_COOLDOWN_QUOTA_SECONDS: int = 900  # daily-quota exhaustion
    LLM_COOLDOWN_NETWORK_SECONDS: int = 30
    LLM_COOLDOWN_SERVER_SECONDS: int = 20
    LLM_COOLDOWN_AUTH_SECONDS: int = 300
    LLM_COOLDOWN_DEFAULT_SECONDS: int = 15

    # P1: compact context. Active workflow/draft is sent separately, so only a
    # few recent turns are needed for conversational continuity.
    CHAT_CONTEXT_TURNS: int = 6
    CHAT_CONTEXT_MAX_CHARS: int = 3200

    # RAG Core: semantic chunking + multilingual embeddings + LLM reranking.
    # No language/phrase dictionaries are required for retrieval.
    RAG_LAZY_INDEX: bool = True
    RAG_EMBEDDING_MODEL: str = "gemini-embedding-2"
    RAG_EMBEDDING_DIM: int = 768
    RAG_EMBEDDING_TIMEOUT_SECONDS: int = 30

    RAG_SOURCE_UNIT_MAX_CHARS: int = 1100
    RAG_PASSAGE_TARGET_CHARS: int = 1500
    RAG_CHUNKING_BATCH_CHARS: int = 4800
    RAG_CHUNKING_MAX_PROVIDER_FAILURES: int = 2

    RAG_VECTOR_TOP_K: int = 16
    RAG_RERANK_BATCH_SIZE: int = 8
    RAG_RERANK_MAX_CANDIDATES: int = 16
    RAG_SECOND_CHANCE_TOP_K: int = 8
    RAG_RERANK_PASSAGE_MAX_CHARS: int = 900
    RAG_MIN_RERANK_SCORE: float = 0.62
    RAG_EMBEDDING_FALLBACK_MIN_SCORE: float = 0.72
    RAG_FINAL_K: int = 3
    RAG_MAX_EVIDENCE_CHARS: int = 2200

    # RAG completion: recall fallback, telemetry and evaluation.
    # Semantic rewrite runs ONLY after normal vector + rerank retrieval fails.
    # Keep normal patient requests to one reranker call. Deep recall is
    # optional for paid/high-quota deployments and disabled by default.
    RAG_ENABLE_DEEP_RECALL_FALLBACK: bool = False
    RAG_ENABLE_SEMANTIC_REWRITE_FALLBACK: bool = False
    RAG_QUERY_REWRITE_MAX_CHARS: int = 260

    # Sanitized preview is optional operational telemetry. Set False to keep only
    # an irreversible query hash in rag_query_logs.
    RAG_STORE_SANITIZED_QUERY_PREVIEW: bool = True
    RAG_QUERY_PREVIEW_MAX_CHARS: int = 300

    # P0: OTP. Keep enforcement false until SMS/webhook delivery is configured.
    OTP_REQUIRED_FOR_SENSITIVE_ACTIONS: bool = False
    OTP_DELIVERY_MODE: str = "console"  # console | webhook
    OTP_SMS_WEBHOOK_URL: str = ""
    OTP_SMS_WEBHOOK_TOKEN: str = ""
    OTP_HASH_SECRET: str = ""
    OTP_CODE_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 5
    OTP_TOKEN_EXPIRE_MINUTES: int = 15
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_EXPOSE_CODE_IN_DEV: bool = False

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _apply_security_policy(self):
        self.SECRET_KEY = secret_policy.resolve_secret_key(
            self.SECRET_KEY, self.APP_ENV
        )

        problems = secret_policy.production_problems(
            app_env=self.APP_ENV,
            otp_required=self.OTP_REQUIRED_FOR_SENSITIVE_ACTIONS,
            otp_delivery_mode=self.OTP_DELIVERY_MODE,
            otp_webhook_url=self.OTP_SMS_WEBHOOK_URL,
            otp_expose_code_in_dev=self.OTP_EXPOSE_CODE_IN_DEV,
            allow_insecure_public_actions=self.ALLOW_INSECURE_PUBLIC_ACTIONS,
        )
        if problems:
            raise ValueError(
                "Unsafe production configuration: " + "; ".join(problems)
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in str(self.CORS_ORIGINS or "").split(",")
            if origin.strip()
        ]


settings = Settings()
