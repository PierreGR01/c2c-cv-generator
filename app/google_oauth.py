"""
Auth Google Drive via OAuth utilisateur (flux loopback "application de bureau").

Remplace le compte de service PARTAGÉ par une identité PAR UTILISATEUR : chacun
s'authentifie avec son propre compte Google Workspace. Les permissions réelles
sont donc celles que le Drive accorde à CE compte — l'application ne décide rien,
elle découvre. Aucun secret d'accès aux données n'est distribué : le poste ne
stocke qu'un token personnel, révocable côté Workspace.

Config (.env) :
  GOOGLE_OAUTH_CLIENT_SECRET_FILE : chemin vers client_secret.json (client OAuth
                                    "Desktop app" créé dans Google Cloud — voir
                                    SETUP-OAUTH.md). Ce fichier identifie l'app,
                                    il n'ouvre aucune donnée par lui-même.
  GOOGLE_OAUTH_CLIENT_SECRET_JSON : alternative inline (contenu JSON du client).
  GOOGLE_OAUTH_TOKEN_FILE         : où stocker le token utilisateur.
                                    Défaut : ~/.config/cv-c2c/token-<app>.json

Un token par (application, jeu de scopes). Refresh automatique tant que le
refresh_token est valide ; sinon, re-consentement navigateur.
"""
import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


def _client_config():
    """Retourne (config_dict|None, file_path|None) pour le client OAuth."""
    inline = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_JSON")
    if inline:
        return json.loads(inline), None
    path = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE")
    if path:
        return None, path
    raise RuntimeError(
        "Client OAuth manquant : renseigne GOOGLE_OAUTH_CLIENT_SECRET_FILE "
        "(ou GOOGLE_OAUTH_CLIENT_SECRET_JSON) dans .env. Voir SETUP-OAUTH.md."
    )


def _token_path(app_name: str) -> Path:
    override = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "cv-c2c"
    return base / f"token-{app_name}.json"


def _save_token(token_file: Path, creds: Credentials) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    # Token personnel : lisible par le seul propriétaire quand l'OS le permet.
    try:
        os.chmod(token_file, 0o600)
    except (OSError, NotImplementedError):
        pass


def get_credentials(scopes: list[str], app_name: str) -> Credentials:
    """
    Retourne des credentials OAuth utilisateur valides pour `scopes`.
    Réutilise le token en cache, le rafraîchit, ou déclenche le consentement
    navigateur (flux loopback) en dernier recours.
    """
    token_file = _token_path(app_name)
    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes)
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(token_file, creds)
            return creds
        except Exception:
            creds = None  # refresh impossible → on repasse par le consentement

    config, path = _client_config()
    if config is not None:
        flow = InstalledAppFlow.from_client_config(config, scopes)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(path, scopes)
    # port=0 : port loopback éphémère ; le navigateur s'ouvre pour le consentement.
    creds = flow.run_local_server(port=0, prompt="consent")
    _save_token(token_file, creds)
    return creds


def build_drive(scopes: list[str], app_name: str):
    """Construit le service Drive v3 authentifié en OAuth utilisateur."""
    creds = get_credentials(scopes, app_name)
    return build("drive", "v3", credentials=creds, cache_discovery=False)
