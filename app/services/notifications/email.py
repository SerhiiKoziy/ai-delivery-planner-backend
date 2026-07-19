"""Email sending via Resend (https://resend.com).

Falls back to a log-only stub when RESEND_API_KEY isn't configured, so local
dev/tests keep working without a real provider — the verification token just
shows up in the logs instead of an inbox.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("app.notifications.email")

RESEND_API_URL = "https://api.resend.com/emails"


def _verification_email_html(verification_url: str) -> str:
    return (
        "<p>Welcome to AI Delivery Planner!</p>"
        f'<p><a href="{verification_url}">Click here to verify your email address</a>.</p>'
        "<p>This link expires in 24 hours.</p>"
    )


async def send_verification_email(email: str, token: str) -> None:
    """Send an email-verification link via Resend.

    Best-effort: a missing API key or a provider-side failure is logged, not
    raised — registration must not 500 just because the email provider is
    unavailable, consistent with how the rest of this project treats
    third-party API failures (see services/geocoding/client.py).
    """
    settings = get_settings()
    verification_url = f"{settings.FRONTEND_BASE_URL}/verify-email?token={token}"

    if not settings.RESEND_API_KEY:
        logger.info("Verification email for %s — token=%s", email, token)
        return

    payload = {
        "from": settings.EMAIL_FROM,
        "to": [email],
        "subject": "Verify your email address",
        "html": _verification_email_html(verification_url),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                RESEND_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            )
    except httpx.HTTPError:
        logger.exception("Failed to send verification email to %s", email)
        return

    if response.status_code >= 300:
        logger.error(
            "Resend rejected verification email to %s: %s %s",
            email,
            response.status_code,
            response.text,
        )
