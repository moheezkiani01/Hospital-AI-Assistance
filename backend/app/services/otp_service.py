import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.otp_challenge import OTPChallenge


ALLOWED_PURPOSES = {
    "appointment_status",
    "cancel_appointment",
    "reschedule_appointment",
    "patient_data_change",
}


def normalize_phone(phone: str) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def _secret() -> bytes:
    value = str(getattr(settings, "OTP_HASH_SECRET", "") or settings.SECRET_KEY)
    return value.encode("utf-8")


def _hash_value(value: str) -> str:
    return hmac.new(_secret(), str(value).encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_code() -> str:
    digits = max(4, min(8, int(getattr(settings, "OTP_CODE_LENGTH", 6))))
    upper = 10 ** digits
    return str(secrets.randbelow(upper)).zfill(digits)


def _deliver_code(phone: str, code: str, purpose: str):
    mode = str(getattr(settings, "OTP_DELIVERY_MODE", "console") or "console").lower()
    message = f"Your hospital verification code is {code}. It expires soon. Do not share it."

    if mode == "console":
        print(f"[OTP] phone=***{phone[-4:]} purpose={purpose} code={code}")
        return

    if mode == "webhook":
        url = str(getattr(settings, "OTP_SMS_WEBHOOK_URL", "") or "").strip()
        if not url:
            raise ValueError("OTP_SMS_WEBHOOK_URL is not configured")

        token = str(getattr(settings, "OTP_SMS_WEBHOOK_TOKEN", "") or "").strip()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.post(
            url,
            headers=headers,
            json={"phone": phone, "message": message, "purpose": purpose},
            timeout=15,
        )
        if response.status_code >= 400:
            raise ValueError(f"OTP delivery failed with HTTP {response.status_code}")
        return

    raise ValueError(f"Unsupported OTP_DELIVERY_MODE: {mode}")


def request_otp(
    db: Session,
    *,
    hospital_id: int,
    phone: str,
    purpose: str,
    session_id: Optional[str] = None,
    appointment_id: Optional[int] = None,
):
    purpose = str(purpose or "").strip().lower()
    if purpose not in ALLOWED_PURPOSES:
        raise ValueError("Unsupported OTP purpose")

    clean_phone = normalize_phone(phone)
    if not (7 <= len(clean_phone) <= 15):
        raise ValueError("A valid phone number is required")

    now = datetime.utcnow()
    cooldown_seconds = int(getattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 60))

    recent = (
        db.query(OTPChallenge)
        .filter(
            OTPChallenge.hospital_id == hospital_id,
            OTPChallenge.phone == clean_phone,
            OTPChallenge.purpose == purpose,
        )
        .order_by(OTPChallenge.created_at.desc())
        .first()
    )
    if recent and recent.created_at and (now - recent.created_at).total_seconds() < cooldown_seconds:
        wait = cooldown_seconds - int((now - recent.created_at).total_seconds())
        raise ValueError(f"Please wait {max(1, wait)} seconds before requesting another code")

    code = _generate_code()
    challenge = OTPChallenge(
        hospital_id=hospital_id,
        session_id=(str(session_id)[:150] if session_id else None),
        appointment_id=appointment_id,
        phone=clean_phone,
        purpose=purpose,
        code_hash=_hash_value(code),
        attempts=0,
        max_attempts=int(getattr(settings, "OTP_MAX_ATTEMPTS", 5)),
        expires_at=now + timedelta(minutes=int(getattr(settings, "OTP_EXPIRE_MINUTES", 5))),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    try:
        _deliver_code(clean_phone, code, purpose)
    except Exception:
        db.delete(challenge)
        db.commit()
        raise

    result = {
        "challenge_id": challenge.id,
        "expires_in_seconds": int(getattr(settings, "OTP_EXPIRE_MINUTES", 5)) * 60,
        "delivery": str(getattr(settings, "OTP_DELIVERY_MODE", "console") or "console"),
        "message": "Verification code sent",
    }

    # Development convenience only. Never enable this in production.
    if bool(getattr(settings, "OTP_EXPOSE_CODE_IN_DEV", False)):
        result["debug_code"] = code

    return result


def verify_otp(db: Session, *, challenge_id: int, code: str):
    challenge = db.query(OTPChallenge).filter(OTPChallenge.id == challenge_id).first()
    if not challenge:
        raise ValueError("Verification challenge not found")

    now = datetime.utcnow()
    if challenge.is_verified:
        raise ValueError("This verification code has already been used")
    if challenge.expires_at < now:
        raise ValueError("Verification code has expired")
    if challenge.attempts >= challenge.max_attempts:
        raise ValueError("Too many verification attempts")

    challenge.attempts += 1
    if not hmac.compare_digest(challenge.code_hash, _hash_value(str(code or "").strip())):
        db.commit()
        remaining = max(0, challenge.max_attempts - challenge.attempts)
        raise ValueError(f"Invalid verification code. {remaining} attempt(s) remaining")

    token = secrets.token_urlsafe(32)
    challenge.verification_token_hash = _hash_value(token)
    challenge.is_verified = True
    challenge.verified_at = now
    challenge.token_expires_at = now + timedelta(minutes=int(getattr(settings, "OTP_TOKEN_EXPIRE_MINUTES", 15)))
    db.commit()

    return {
        "verification_token": token,
        "purpose": challenge.purpose,
        "expires_in_seconds": int(getattr(settings, "OTP_TOKEN_EXPIRE_MINUTES", 15)) * 60,
    }


def validate_verification_token(
    db: Session,
    *,
    token: str,
    hospital_id: int,
    phone: str,
    purpose: str,
    appointment_id: Optional[int] = None,
    consume: bool = False,
) -> OTPChallenge:
    if not token:
        raise ValueError("OTP verification is required")

    clean_phone = normalize_phone(phone)
    token_hash = _hash_value(token)
    now = datetime.utcnow()

    challenge = (
        db.query(OTPChallenge)
        .filter(
            OTPChallenge.hospital_id == hospital_id,
            OTPChallenge.phone == clean_phone,
            OTPChallenge.purpose == purpose,
            OTPChallenge.verification_token_hash == token_hash,
            OTPChallenge.is_verified == True,
        )
        .order_by(OTPChallenge.verified_at.desc())
        .first()
    )

    if not challenge:
        raise ValueError("OTP verification token is invalid")
    if not challenge.token_expires_at or challenge.token_expires_at < now:
        raise ValueError("OTP verification token has expired")
    if challenge.used_at is not None:
        raise ValueError("OTP verification token has already been used")
    if appointment_id is not None and challenge.appointment_id not in {None, appointment_id}:
        raise ValueError("OTP verification does not match this appointment")

    if consume:
        challenge.used_at = now
        db.commit()

    return challenge
