"""
Mailjet API mail service.

Replaces the old Flask-Mail / raw-SMTP sending path. Uses Mailjet's
transactional Send API (v3.1) over HTTPS instead of an SMTP socket
connection — no SMTP host/port/TLS settings needed anymore.

Docs: https://dev.mailjet.com/email/guides/send-api-v31/
"""
import base64
import logging

import requests
from flask import current_app

logger = logging.getLogger(__name__)

MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"
_BATCH_SIZE = 50  # Mailjet's max Messages[] entries per API call


def _sender():
    return {
        "Email": current_app.config["MAILJET_SENDER_EMAIL"],
        "Name": current_app.config.get("MAILJET_SENDER_NAME", ""),
    }


def _auth():
    api_key = current_app.config.get("MAILJET_API_KEY")
    api_secret = current_app.config.get("MAILJET_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(
            "MAILJET_API_KEY / MAILJET_API_SECRET are not configured")
    return (api_key, api_secret)


def _build_message(recipient_email, subject, body, recipient_name=None,
                    attachments=None):
    message = {
        "From": _sender(),
        "To": [{"Email": recipient_email, "Name": recipient_name or ""}],
        "Subject": subject,
        "TextPart": body,
    }
    if attachments:
        message["Attachments"] = [
            {
                "ContentType": content_type,
                "Filename": filename,
                "Base64Content": base64.b64encode(raw_bytes).decode("ascii"),
            }
            for filename, content_type, raw_bytes in attachments
        ]
    return message


def send_mail(subject, recipients, body, recipient_name=None,
              attachments=None):
    """
    Send a single email (optionally to several recipients) via Mailjet.

    attachments: optional list of (filename, content_type, raw_bytes) tuples.
    Raises on failure — callers should catch and handle as before.
    """
    if isinstance(recipients, str):
        recipients = [recipients]

    payload = {
        "Messages": [
            _build_message(email, subject, body,
                            recipient_name=recipient_name,
                            attachments=attachments)
            for email in recipients
        ]
    }

    resp = requests.post(MAILJET_SEND_URL, auth=_auth(), json=payload,
                          timeout=15)
    if resp.status_code != 200:
        logger.error("Mailjet send failed (%s): %s",
                      resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()


def send_personalized_bulk_mail(subject, entries):
    """
    Send a personalized email to each recipient in a single batched call
    (grouped in Mailjet's max-50-per-request limit).

    entries: list of (email, name, body) tuples — each recipient gets
    their own body text (e.g. "Dear <name>, ...").
    """
    results = []
    for i in range(0, len(entries), _BATCH_SIZE):
        chunk = entries[i:i + _BATCH_SIZE]
        payload = {
            "Messages": [
                _build_message(email, subject, body, recipient_name=name)
                for email, name, body in chunk
            ]
        }
        resp = requests.post(MAILJET_SEND_URL, auth=_auth(), json=payload,
                              timeout=20)
        if resp.status_code != 200:
            logger.error("Mailjet personalized bulk send failed (%s): %s",
                          resp.status_code, resp.text)
            resp.raise_for_status()
        results.append(resp.json())
    return results


def send_bulk_mail(subject, body, recipients):
    """
    Send the same subject/body to many recipients, each as its own
    message (so one bad address doesn't affect the others), batched
    in groups of 50 per Mailjet API call.

    recipients: list of email strings, or list of (email, name) tuples.
    """
    normalized = []
    for r in recipients:
        if isinstance(r, tuple):
            normalized.append(r)
        else:
            normalized.append((r, None))

    results = []
    for i in range(0, len(normalized), _BATCH_SIZE):
        chunk = normalized[i:i + _BATCH_SIZE]
        payload = {
            "Messages": [
                _build_message(email, subject, body, recipient_name=name)
                for email, name in chunk
            ]
        }
        resp = requests.post(MAILJET_SEND_URL, auth=_auth(), json=payload,
                              timeout=20)
        if resp.status_code != 200:
            logger.error("Mailjet bulk send failed (%s): %s",
                          resp.status_code, resp.text)
            resp.raise_for_status()
        results.append(resp.json())
    return results