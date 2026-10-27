"""Chat-side phone verification: strict matching + lockout after repeated guesses."""
from types import SimpleNamespace

import pytest

from app.core.rate_limit import verification_failures
from app.services import chat_service


@pytest.fixture(autouse=True)
def _clean_lockouts():
    verification_failures.reset()
    yield
    verification_failures.reset()


def _patient(phone="03001234567", patient_id=1):
    return SimpleNamespace(id=patient_id, hospital_id=1, phone=phone, name="Test Patient")


@pytest.mark.parametrize(
    "given",
    ["03001234567", "+92 300 1234567", "923001234567", "3001234567", "0300-1234567"],
)
def test_same_number_in_different_formats_matches(given):
    assert chat_service.phone_matches("03001234567", given)


@pytest.mark.parametrize("given", ["1234567", "01234567", "234567", "34567", "03111234567", "", None])
def test_short_suffix_or_other_number_does_not_match(given):
    # Regression: the old matcher accepted ANY suffix, so the last 5-7 digits were
    # enough to cancel or reschedule someone else's appointment.
    assert not chat_service.phone_matches("03001234567", given)


def test_short_stored_numbers_still_require_an_exact_match():
    assert chat_service.phone_matches("12345", "12345")
    assert not chat_service.phone_matches("12345", "345")


def test_website_verification_locks_after_repeated_wrong_phones():
    patient = _patient()
    max_failures = chat_service.settings.VERIFY_MAX_FAILURES

    for guess in range(max_failures):
        ok, _, _ = chat_service.verify_patient_phone_for_action(
            "website", None, patient, f"my number is 0311000{guess:04d}", None
        )
        assert ok is False

    # Even the CORRECT number is refused now.
    ok, _, message = chat_service.verify_patient_phone_for_action(
        "website", None, patient, "03001234567", None
    )
    assert ok is False
    assert message == chat_service.PHONE_VERIFICATION_LOCKED_MESSAGE


def test_correct_phone_before_lockout_resets_the_counter():
    patient = _patient()

    for _ in range(chat_service.settings.VERIFY_MAX_FAILURES - 1):
        chat_service.verify_patient_phone_for_action("website", None, patient, "03110000000", None)

    ok, _, _ = chat_service.verify_patient_phone_for_action(
        "website", None, patient, "03001234567", None
    )
    assert ok is True

    # The counter was cleared, so one more wrong guess does not lock the record.
    chat_service.verify_patient_phone_for_action("website", None, patient, "03110000000", None)
    assert not chat_service.verification_is_locked(patient)


def test_lockout_is_per_patient():
    attacked, bystander = _patient(patient_id=1), _patient(patient_id=2)

    for guess in range(chat_service.settings.VERIFY_MAX_FAILURES):
        chat_service.verify_patient_phone_for_action(
            "website", None, attacked, f"0311000{guess:04d}", None
        )

    assert chat_service.verification_is_locked(attacked)
    assert not chat_service.verification_is_locked(bystander)


def test_correction_verifier_counts_one_failure_per_message_and_locks():
    patient = _patient()

    for _ in range(chat_service.settings.VERIFY_MAX_FAILURES):
        ok, _, _ = chat_service.verify_patient_phone_for_correction(
            "website", None, patient, "03110000000 and 03120000000", None
        )
        assert ok is False

    ok, _, message = chat_service.verify_patient_phone_for_correction(
        "website", None, patient, "03001234567", None
    )
    assert ok is False
    assert message == chat_service.PHONE_VERIFICATION_LOCKED_MESSAGE
