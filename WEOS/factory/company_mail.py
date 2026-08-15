"""Best-effort company PIN-reset email (SMTP env, otherwise log-only)."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

_log = logging.getLogger("weos.company_mail")


def public_base_url() -> str:
    env = (os.environ.get("WEOS_PUBLIC_BASE_URL") or "").strip()
    if env:
        return env.rstrip("/")
    dom = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if not dom:
        return ""
    if not dom.startswith("http://") and not dom.startswith("https://"):
        dom = "https://" + dom
    return dom.rstrip("/")


def send_pin_reset_email(*, to_email: str, company_name: str, reset_url: str) -> bool:
    """Send the PIN reset link. Returns True when SMTP accepted the message."""
    to_email = str(to_email or "").strip()
    if not to_email or "@" not in to_email:
        return False
    host = (os.environ.get("SMTP_HOST") or os.environ.get("WEOS_SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or os.environ.get("WEOS_SMTP_USER") or "").strip()
    password = (os.environ.get("SMTP_PASS") or os.environ.get("WEOS_SMTP_PASS") or "").strip()
    from_addr = (os.environ.get("SMTP_FROM") or os.environ.get("WEOS_SMTP_FROM") or user or "").strip()
    try:
        port = int(os.environ.get("SMTP_PORT") or os.environ.get("WEOS_SMTP_PORT") or 587)
    except (TypeError, ValueError):
        port = 587
    name = (company_name or "WEOS company").strip() or "WEOS company"
    body = (
        f"Hello {name},\n\n"
        "A 4-digit company login PIN reset was requested for this WEOS workspace.\n\n"
        f"Set a new PIN here (link expires in 1 hour):\n{reset_url}\n\n"
        "If you did not ask for this, ignore this email — your current PIN stays the same.\n"
    )
    if not host or not from_addr:
        _log.warning("PIN reset email not sent (SMTP not configured). Link: %s", reset_url)
        return False
    msg = EmailMessage()
    msg["Subject"] = f"WEOS PIN reset — {name}"
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except Exception:
                pass
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception:
        _log.exception("PIN reset SMTP send failed to %s", to_email)
        return False
