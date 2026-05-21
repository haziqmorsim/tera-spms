from __future__ import annotations
import json
import os
from typing import Any
from urllib.parse import quote
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

def _get_setting(db: Session, key: str, default: str = "") -> str:
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

    if not row:
        return default
    
    return row["setting_value"] or default

def _get_graph_access_token(*, tenant_id: str, cliend_id: str, client_secret: str,) -> str:
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    response = requests.post(
        token_url, 
        data={
            "client_id": cliend_id, 
            "client_secret": client_secret, 
            "scope": "https://graph.microsoft.com/.default", 
            "grant_type": "client_credentials",
        }, 
        timeout=30,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            "Failed to get Microsoft Graph access token: "
            f"{response.status_code} {response.text}"
        )
    
    payload = response.json()
    access_token = payload.get("access_token")

    if not access_token:
        raise RuntimeError("Microsoft Graph access token was not returned.")
    
    return access_token

def send_password_reset_email(db: Session, *, recipient_email: str, recipient_name: str, reset_url: str,) -> None:
    tenant_id = _get_setting(db, "graph_tenant_id", os.getenv("GRAPH_TENANT_ID", ""),).strip()
    client_id = _get_setting(db, "graph_client_id", os.getenv("GRAPH_CLIENT_ID", ""),).strip()
    client_secret = _get_setting(db, "graph_client_secret", os.getenv("GRAPH_CLIENT_SECRET"),).strip()
    sender_email = _get_setting(db, "graph_sender_email", os.getenv("GRAPH_SENDER_EMAIL"),).strip()

    if not tenant_id or not client_id or not client_secret or not sender_email:
        raise RuntimeError(
            "Microsoft Graph e-mail settings are incomplete. "
            "Please configure Tenant ID, Client ID, Client Secret, and Sender E-mail."
        )
    
    access_token = _get_graph_access_token(
        tenant_id=tenant_id, 
        cliend_id=client_id, 
        client_secret=client_secret,
    )

    subject = "Reset Your TERA SPMS Password"

    html_body =  f"""
    <div style="font-family: Arial, sans-serif; font-size: 14px; color: #111827;">
        <p>Hi {recipient_name},</p>

        <p>
            We received a request to reset your TERA SPMS password.
            Click the button below to create a new password.
        </p>

        <p style="margin: 24px 0;">
            <a href="{reset_url}"
               style="background: #0d6efd; color: #ffffff; text-decoration: none;
                      padding: 10px 16px; border-radius: 6px; display: inline-block;">
                Reset Password
            </a>
        </p>

        <p>
            This link will expire in 30 minutes.
        </p>

        <p>
            If you did not request a password reset, you can ignore this e-mail.
        </p>

        <p style="margin-top: 24px;">
            Regards,<br>
            TERA SPMS
        </p>
    </div>
    """

    message: dict[str, Any] = {
        "message": {
            "subject": subject, 
            "body": {
                "contentType": "HTML", 
                "content": html_body,
            }, 
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": recipient_email,
                    }
                }
            ],
        },
        "saveToSentItems": True,
    }

    send_url = (
        "https://graph.microsoft.com/v1.0/users/"
        f"{quote(sender_email)}/sendMail"
    )

    response = requests.post(
        send_url, 
        headers={
            "Authorization": f"Bearer {access_token}", 
            "Content-Type": "application/json",
        }, 
        data=json.dump(message), 
        timeout=30,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            "Failed to send password reset e-mail: "
            f"{response.status_code} {response.text}"
        )