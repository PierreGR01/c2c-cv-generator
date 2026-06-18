"""
Client Google Drive — lecture seule des fiches collaborateurs.
Auth via service account (JSON dans variable d'env GOOGLE_SERVICE_ACCOUNT_JSON).

Mode local : si aucune credential n'est définie, lit depuis le dossier
local `collaborateurs/` (utile pour les tests).
"""
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Lecture seule — pas besoin d'écrire sur Drive
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Dossier local utilisé en mode test (quand Drive n'est pas configuré)
# Priorité : var d'env COLLABORATEURS_LOCAL_DIR > dossier frère de cv-generator/ > fallback interne
_env_dir = os.environ.get("COLLABORATEURS_LOCAL_DIR")
LOCAL_DIR = Path(_env_dir) if _env_dir else Path(__file__).parent.parent.parent / "collaborateurs"

# Cache en mémoire pour le listing Drive (évite de re-télécharger 55 fichiers à chaque appel)
_listing_cache: list[dict] | None = None
_listing_cache_ts: float = 0.0
_CACHE_TTL = 300  # 5 minutes


def _is_local_mode() -> bool:
    return not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and \
           not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_FILE")


def _build_service():
    # Priorité 1 : chemin vers le fichier JSON (local, plus simple)
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_FILE")
    if sa_file:
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return build("drive", "v3", credentials=creds)
    # Priorité 2 : contenu JSON inline (production / Render)
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("Ni GOOGLE_SERVICE_ACCOUNT_JSON ni GOOGLE_SERVICE_ACCOUNT_JSON_FILE défini")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _get_subfolder_id(service, parent_id: str, name: str) -> str | None:
    """Trouve l'ID d'un sous-dossier par nom."""
    q = (
        f"'{parent_id}' in parents "
        f"and name = '{name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _collab_entry_from_fiche(file_id: str, filename: str, fiche: dict) -> dict:
    """Construit l'entrée de listing à partir d'une fiche parsée."""
    identite = fiche.get("identite", {})
    stem = filename.replace(".yaml", "").replace(".yml", "")
    prenom = identite.get("prenom", "")
    nom = identite.get("nom", "")
    display = f"{prenom} {nom}".strip() if (prenom or nom) \
        else " ".join(part.capitalize() for part in stem.replace("-", " ").split())
    return {
        "id": file_id,
        "name": stem,
        "display": display,
        "filename": filename,
        "categorie": identite.get("categorie_poste", ""),
    }


def list_collaborateurs() -> list[dict]:
    """
    Liste les fiches collaborateurs (.yaml) avec leur categorie_poste.
    Mode local  : lit + parse chaque YAML depuis collaborateurs/.
    Mode Drive  : télécharge en parallèle (10 workers) puis cache 5 min.
    """
    global _listing_cache, _listing_cache_ts

    if _is_local_mode():
        result = []
        for path in sorted(LOCAL_DIR.glob("*.yaml")):
            try:
                fiche = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                fiche = {}
            result.append(_collab_entry_from_fiche(f"local::{path.stem}", path.name, fiche))
        return result

    # Cache valide ?
    if _listing_cache is not None and (time.time() - _listing_cache_ts) < _CACHE_TTL:
        return _listing_cache

    root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    service = _build_service()
    folder_id = _get_subfolder_id(service, root_id, "collaborateurs")
    if not folder_id:
        return []

    q = f"'{folder_id}' in parents and name contains '.yaml' and trashed = false"
    res = service.files().list(q=q, fields="files(id,name)", orderBy="name").execute()
    files = res.get("files", [])

    def _fetch(f: dict) -> dict:
        try:
            fiche = get_fiche(f["id"])
        except Exception:
            fiche = {}
        return _collab_entry_from_fiche(f["id"], f["name"], fiche)

    result = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch, f): f for f in files}
        for fut in as_completed(futures):
            result.append(fut.result())

    result.sort(key=lambda x: x["name"])
    _listing_cache = result
    _listing_cache_ts = time.time()
    return result


def get_fiche(file_id: str) -> dict:
    """Charge et parse une fiche YAML collaborateur (Drive ou local)."""
    if file_id.startswith("local::"):
        stem = file_id.removeprefix("local::")
        path = LOCAL_DIR / f"{stem}.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    service = _build_service()
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return yaml.safe_load(buf.read().decode("utf-8"))
