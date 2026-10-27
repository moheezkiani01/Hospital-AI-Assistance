
"""Public chat transport boundary, independent of OTP verification."""

from app.schemas.chat import ChatMessageRequest


def sanitize_public_chat_request(request_data: ChatMessageRequest) -> ChatMessageRequest:
    """Treat public API messages as website messages, not authenticated WhatsApp.

    Only a verified WhatsApp webhook may populate trusted sender identity.
    A browser/client posting to the public chat endpoint is never such a webhook.
    """

    if str(request_data.source or "website").strip().lower() == "whatsapp":
        raise ValueError(
            "WhatsApp identity cannot be supplied through the public chat endpoint"
        )

    if request_data.whatsapp_number:
        raise ValueError(
            "WhatsApp identity cannot be supplied through the public chat endpoint"
        )

    return request_data.model_copy(
        update={
            "source": "website",
            "whatsapp_number": None
        }
    )
