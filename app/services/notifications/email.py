"""Email sending via Gmail SMTP.

Falls back to a log-only stub when GMAIL_ADDRESS/GMAIL_APP_PASSWORD aren't
configured, so local dev/tests keep working without a real provider — the
verification / password-reset token just shows up in the logs instead of an
inbox.
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import get_settings

logger = logging.getLogger("app.notifications.email")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def _verification_email_html(verification_url: str) -> str:
    return (
        "<p>Welcome to AI Delivery Planner!</p>"
        f'<p><a href="{verification_url}">Click here to verify your email address</a>.</p>'
        "<p>This link expires in 24 hours.</p>"
    )


def _password_reset_email_html(reset_url: str) -> str:
    return (
        "<p>Someone asked to reset the password for your AI Delivery Planner account.</p>"
        f'<p><a href="{reset_url}">Click here to choose a new password</a>.</p>'
        "<p>This link expires in 30 minutes and works only once. If it wasn't you, "
        "ignore this email — your password stays the same.</p>"
    )


def _send_via_gmail(*, to: str, subject: str, html: str, sender: str, app_password: str) -> None:
    """Blocking SMTP send — always called via `asyncio.to_thread`."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    message.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.login(sender, app_password)
        smtp.sendmail(sender, [to], message.as_string())


async def send_verification_email(email: str, token: str) -> None:
    """Send an email-verification link via Gmail SMTP.

    Best-effort: a missing app password or a provider-side failure is
    logged, not raised — registration must not 500 just because the email
    provider is unavailable, consistent with how the rest of this project
    treats third-party API failures (see services/geocoding/client.py).
    """
    settings = get_settings()
    verification_url = f"{settings.FRONTEND_BASE_URL}/verify-email?token={token}"

    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        logger.info("Verification email for %s — token=%s", email, token)
        return

    try:
        await asyncio.to_thread(
            _send_via_gmail,
            to=email,
            subject="Verify your email address",
            html=_verification_email_html(verification_url),
            sender=settings.GMAIL_ADDRESS,
            app_password=settings.GMAIL_APP_PASSWORD,
        )
    except smtplib.SMTPException:
        logger.exception("Failed to send verification email to %s", email)


async def send_password_reset_email(email: str, token: str) -> None:
    """Send a password-reset link via Gmail SMTP. Best-effort, like
    `send_verification_email`: failures are logged, never raised."""
    settings = get_settings()
    reset_url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"

    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        logger.info("Password reset email for %s — token=%s", email, token)
        return

    try:
        await asyncio.to_thread(
            _send_via_gmail,
            to=email,
            subject="Reset your password",
            html=_password_reset_email_html(reset_url),
            sender=settings.GMAIL_ADDRESS,
            app_password=settings.GMAIL_APP_PASSWORD,
        )
    except smtplib.SMTPException:
        logger.exception("Failed to send password reset email to %s", email)
