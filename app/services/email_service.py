from __future__ import annotations
import base64
import os
from pathlib import Path
import msal
import requests
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.activity_log_service import log_activity

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

def _guess_attachment_content_type(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return "application/octet-stream"

def _log_email_activity(
    *,
    action: str,
    status_code: int,
    subject: str,
    to_email: str | None,
    attachment_paths: list[str] | None,
    error: str | None = None,
    provider: str = "graph",
) -> None:
    db = SessionLocal()
    try:
        attachment_names = [Path(p).name for p in (attachment_paths or [])]

        log_activity(
            db,
            event_type="System event",
            user_type="system",
            user_name=None,
            action=action,
            target=subject,
            path="email_service",
            method=provider.upper(),
            status_code=status_code,
            details={
                "provider": provider,
                "subject": subject,
                "to_email": to_email,
                "attachment_names": attachment_names,
                "attachment_paths": attachment_paths or [],
                "error": error,
            },
        )
    except Exception:
        db.rollback()
    finally:
        db.close()

def _get_setting_from_db(key: str) -> str | None:
    db = SessionLocal()
    try:
        row = (
            db.execute(
                text(
                    """
                    SELECT setting_value
                    FROM app_settings
                    WHERE setting_key = :key
                    LIMIT 1
                    """
                ),
                {"key": key},
            )
            .mappings()
            .first()
        )
        return row["setting_value"] if row and row["setting_value"] is not None else None
    except Exception:
        db.rollback()
        return None
    finally:
        db.close()

def _get_config_value(setting_key: str, env_key: str, default: str = "") -> str:
    db_value = _get_setting_from_db(setting_key)
    if db_value is not None and str(db_value).strip() != "":
        return str(db_value).strip()

    return os.getenv(env_key, default).strip()

def _get_delivery_method() -> str:
    return _get_config_value("email_delivery_method", "EMAIL_DELIVERY_METHOD", "graph").lower()

def _build_graph_app() -> msal.ConfidentialClientApplication:
    tenant_id = _get_config_value("graph_tenant_id", "GRAPH_TENANT_ID")
    client_id = _get_config_value("graph_client_id", "GRAPH_CLIENT_ID")
    client_secret = _get_config_value("graph_client_secret", "GRAPH_CLIENT_SECRET")

    if not tenant_id or not client_id or not client_secret:
        raise RuntimeError(
            "Graph configuration is incomplete. "
            "Set graph_tenant_id, graph_client_id, and graph_client_secret in Settings or .env"
        )

    authority = f"https://login.microsoftonline.com/{tenant_id}"

    return msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential=client_secret,
    )

def _acquire_graph_token() -> str:
    app = _build_graph_app()

    result = app.acquire_token_silent(scopes=GRAPH_SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    access_token = result.get("access_token")
    if not access_token:
        error = result.get("error_description") or str(result)
        raise RuntimeError(f"Failed to acquire Microsoft Graph token: {error}")

    return access_token

def _build_graph_file_attachments(attachment_paths: list[Path]) -> list[dict]:
    attachments: list[dict] = []

    for path in attachment_paths:
        content_bytes = base64.b64encode(path.read_bytes()).decode("utf-8")
        attachments.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": path.name,
                "contentType": _guess_attachment_content_type(path),
                "contentBytes": content_bytes,
            }
        )

    return attachments

def _send_via_graph(
    *,
    subject: str,
    body: str,
    attachment_paths: list[Path],
    to_email: str | None = None,
) -> None:
    sender_email = _get_config_value(
        "graph_sender_email",
        "GRAPH_SENDER_EMAIL",
        _get_config_value("email_from", "EMAIL_FROM", ""),
    )
    recipient = to_email or _get_config_value("email_to", "EMAIL_TO", "")

    if not sender_email or not recipient:
        raise RuntimeError(
            "Graph email configuration is incomplete. "
            "Set graph_sender_email and email_to in Settings or .env"
        )

    token = _acquire_graph_token()
    endpoint = f"{GRAPH_BASE_URL}/users/{sender_email}/sendMail"

    recipients = [
        {
            "emailAddress": {
                "address": addr.strip(),
            }
        }
        for addr in recipient.split(",")
        if addr.strip()
    ]

    if not recipients:
        raise RuntimeError("No valid recipient email address found.")

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": recipients,
            "attachments": _build_graph_file_attachments(attachment_paths),
        },
        "saveToSentItems": True,
    }

    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )

    if response.status_code not in (202, 200):
        try:
            response_text = response.json()
        except Exception:
            response_text = response.text
        raise RuntimeError(
            f"Microsoft Graph sendMail failed: HTTP {response.status_code} - {response_text}"
        )

def send_email_with_attachments(
    *,
    subject: str,
    body: str,
    attachment_paths: list[str | Path],
    to_email: str | None = None,
) -> None:
    delivery_method = _get_delivery_method()
    normalized_paths = [Path(p) for p in attachment_paths]

    missing = [str(p) for p in normalized_paths if not p.exists()]
    if missing:
        error = f"Attachment(s) not found: {', '.join(missing)}"
        _log_email_activity(
            action="Email sending failed",
            status_code=404,
            subject=subject,
            to_email=to_email or _get_config_value("email_to", "EMAIL_TO", ""),
            attachment_paths=[str(p) for p in normalized_paths],
            error=error,
            provider=delivery_method,
        )
        raise FileNotFoundError(error)

    try:
        if delivery_method == "graph":
            _send_via_graph(
                subject=subject,
                body=body,
                attachment_paths=normalized_paths,
                to_email=to_email,
            )
        else:
            raise RuntimeError(
                f"Unsupported EMAIL_DELIVERY_METHOD: {delivery_method}. "
                "Use EMAIL_DELIVERY_METHOD=graph"
            )

        _log_email_activity(
            action="Email sent",
            status_code=200,
            subject=subject,
            to_email=to_email or _get_config_value("email_to", "EMAIL_TO", ""),
            attachment_paths=[str(p) for p in normalized_paths],
            provider=delivery_method,
        )

    except Exception as e:
        _log_email_activity(
            action="Email sending failed",
            status_code=500,
            subject=subject,
            to_email=to_email or _get_config_value("email_to", "EMAIL_TO", ""),
            attachment_paths=[str(p) for p in normalized_paths],
            error=str(e),
            provider=delivery_method,
        )
        raise

def send_email_with_attachments(
    *,
    subject: str,
    body: str,
    attachment_paths: list[str | Path],
    to_email: str | None = None,
) -> None:
    delivery_method = _get_delivery_method()
    normalized_paths = [Path(p) for p in attachment_paths]

    missing = [str(p) for p in normalized_paths if not p.exists()]

    if missing:
        error = f"Attachment(s) not found: {', '.join(missing)}"

        _log_email_activity(
            action="Email sending failed",
            status_code=404,
            subject=subject,
            to_email=to_email or _get_config_value("email_to", "EMAIL_TO", ""),
            attachment_paths=[str(p) for p in normalized_paths],
            error=error,
            provider=delivery_method,
        )

        raise FileNotFoundError(error)

    try:
        if delivery_method == "graph":
            _send_via_graph(
                subject=subject,
                body=body,
                attachment_paths=normalized_paths,
                to_email=to_email,
            )
        else:
            raise RuntimeError(
                f"Unsupported EMAIL_DELIVERY_METHOD: {delivery_method}. "
                "Use EMAIL_DELIVERY_METHOD=graph"
            )

        recipient = to_email or _get_config_value("email_to", "EMAIL_TO", "")
        attachment_path_texts = [str(p) for p in normalized_paths]

        _log_email_activity(
            action="Email sent",
            status_code=200,
            subject=subject,
            to_email=recipient,
            attachment_paths=attachment_path_texts,
            provider=delivery_method,
        )

        try:
            db = SessionLocal()

            from app.services.notification_service import notify_email_sent

            notify_email_sent(
                db,
                subject=subject,
                to_email=recipient,
                attachment_paths=attachment_path_texts,
            )

        except Exception:
            db.rollback()

        finally:
            try:
                db.close()
            except Exception:
                pass

    except Exception as exc:
        _log_email_activity(
            action="Email sending failed",
            status_code=500,
            subject=subject,
            to_email=to_email or _get_config_value("email_to", "EMAIL_TO", ""),
            attachment_paths=[str(p) for p in normalized_paths],
            error=str(exc),
            provider=delivery_method,
        )

        raise