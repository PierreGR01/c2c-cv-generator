"""
Notifications e-mail via l'API Gmail, sous l'identité OAuth de l'utilisateur courant.

Le mail part DU compte de la personne qui a effectué l'action, vers le(s)
destinataire(s) résolus par `config` (le rôle admin). Aucun secret SMTP : on
réutilise le token OAuth existant (scope gmail.send).

Best-effort : toute erreur est loggée mais n'interrompt JAMAIS l'opération métier.
Conçu pour tourner en tâche de fond (FastAPI BackgroundTasks).
"""
import base64
import sys
from datetime import datetime
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from . import config, drive, google_oauth


def notify(actor_email: str, action: str, details: str = "") -> None:
    try:
        if not config.notifications_enabled():
            return
        recipients = [r for r in config.get_notify_recipients() if r]
        if not recipients:
            return

        creds = google_oauth.get_credentials(drive.SCOPES, drive.APP_NAME)
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        actor = actor_email or "un utilisateur"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = f"[C2C Tenders] {actor} — {action}"
        body = (
            f"{actor} a effectué une opération sur l'app CV Camptocamp.\n\n"
            f"Action : {action}\n"
            + (f"{details}\n" if details else "")
            + f"Date : {ts}\n"
        )
        msg = MIMEText(body)
        msg["to"] = ", ".join(recipients)
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as e:  # noqa: BLE001 — notification best-effort
        print(f"[gmail_notify] notification non envoyée : {e}", file=sys.stderr)
