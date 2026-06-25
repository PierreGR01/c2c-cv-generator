"""
Client Google Drive — lecture des fiches collaborateurs.
Auth via service account (JSON dans GOOGLE_SERVICE_ACCOUNT_JSON).

Mode local : si aucune credential n'est définie, lit depuis collaborateurs/.

Écriture (ingestion fiche fin de projet) :
  Utilise un SA secondaire avec scope write, configuré via CV_EDITOR_SA_JSON
  ou CV_EDITOR_SA_FILE (mêmes variables que cv-editor).
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
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

_SCOPES_READ  = ["https://www.googleapis.com/auth/drive.readonly"]
_SCOPES_WRITE = ["https://www.googleapis.com/auth/drive"]

_env_dir = os.environ.get("COLLABORATEURS_LOCAL_DIR")
LOCAL_DIR = Path(_env_dir) if _env_dir else Path(__file__).parent.parent.parent / "collaborateurs"

_listing_cache = None
_listing_cache_ts = 0.0
_CACHE_TTL = 300


# ---------- Auth -------------------------------------------------------------

def _is_local_mode():
    return not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and \
           not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_FILE")


def _build_service_read():
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_FILE")
    if sa_file:
        creds = service_account.Credentials.from_service_account_file(
            sa_file, scopes=_SCOPES_READ)
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError(
            "Ni GOOGLE_SERVICE_ACCOUNT_JSON ni GOOGLE_SERVICE_ACCOUNT_JSON_FILE défini")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=_SCOPES_READ)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _build_service_write():
    sa_file = os.environ.get("CV_EDITOR_SA_FILE")
    if sa_file:
        creds = service_account.Credentials.from_service_account_file(
            sa_file, scopes=_SCOPES_WRITE)
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    sa_json = os.environ.get("CV_EDITOR_SA_JSON")
    if not sa_json:
        raise RuntimeError(
            "Écriture Drive impossible : CV_EDITOR_SA_JSON ou CV_EDITOR_SA_FILE "
            "non configurés dans .env")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=_SCOPES_WRITE)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---------- Helpers ----------------------------------------------------------

def _get_subfolder_id(service, parent_id, name):
    q = (
        "'" + parent_id + "' in parents"
        " and name = '" + name + "'"
        " and mimeType = 'application/vnd.google-apps.folder'"
        " and trashed = false"
    )
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _collab_entry_from_fiche(file_id, filename, fiche):
    identite = fiche.get("identite", {})
    stem = filename.replace(".yaml", "").replace(".yml", "")
    prenom = identite.get("prenom", "")
    nom = identite.get("nom", "")
    if prenom or nom:
        display = (prenom + " " + nom).strip()
    else:
        display = " ".join(p.capitalize() for p in stem.replace("-", " ").split())
    return {
        "id": file_id,
        "name": stem,
        "display": display,
        "filename": filename,
        "categorie": identite.get("categorie_poste", ""),
    }


# ---------- Lecture ----------------------------------------------------------

def list_collaborateurs():
    """Liste les fiches collaborateurs (.yaml)."""
    global _listing_cache, _listing_cache_ts

    if _is_local_mode():
        result = []
        for path in sorted(LOCAL_DIR.glob("*.yaml")):
            try:
                fiche = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                fiche = {}
            result.append(
                _collab_entry_from_fiche("local::" + path.stem, path.name, fiche))
        return result

    if _listing_cache is not None and (time.time() - _listing_cache_ts) < _CACHE_TTL:
        return _listing_cache

    service = _build_service_read()
    # Priorité : COLLABORATEURS_FOLDER_ID (ID direct du dossier)
    # Fallback : cherche un sous-dossier "collaborateurs" dans GOOGLE_DRIVE_FOLDER_ID
    folder_id = os.environ.get("COLLABORATEURS_FOLDER_ID")
    if not folder_id:
        root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        folder_id = _get_subfolder_id(service, root_id, "collaborateurs")
    if not folder_id:
        return []

    q = "'" + folder_id + "' in parents and name contains '.yaml' and trashed = false"
    res = service.files().list(q=q, fields="files(id,name)", orderBy="name").execute()
    # Exclure les fichiers non-collaborateurs (competences.yaml, fichiers commençant par _)
    files = [f for f in res.get("files", []) if not f["name"].startswith("_") and f["name"] != "competences.yaml"]

    def _fetch(f):
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


def get_fiche(file_id):
    """Charge et parse une fiche YAML collaborateur (Drive ou local)."""
    if file_id.startswith("local::"):
        stem = file_id[len("local::"):]
        path = LOCAL_DIR / (stem + ".yaml")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    service = _build_service_read()
    return yaml.safe_load(_download_raw(service, file_id)) or {}


def get_fiche_raw(file_id):
    """Charge le contenu YAML brut d'une fiche (Drive ou local)."""
    if file_id.startswith("local::"):
        stem = file_id[len("local::"):]
        path = LOCAL_DIR / (stem + ".yaml")
        return path.read_text(encoding="utf-8")
    service = _build_service_read()
    return _download_raw(service, file_id)


def get_collaborateurs_lookup():
    """Retourne {slug: {file_id, fiche, display, filename}} pour tous les collabs."""
    collabs = list_collaborateurs()
    result = {}
    for c in collabs:
        try:
            fiche = get_fiche(c["id"])
        except Exception:
            fiche = {}
        result[c["name"]] = {
            "file_id": c["id"],
            "fiche": fiche,
            "display": c["display"],
            "filename": c["filename"],
        }
    return result


def get_competences_raw():
    """Retourne le contenu brut de competences.yaml."""
    if _is_local_mode():
        for candidate in ["competences.yaml", "_competence.yaml", "_competences.yaml"]:
            p = LOCAL_DIR.parent / candidate
            if p.exists():
                return p.read_text(encoding="utf-8")
            p2 = LOCAL_DIR / candidate
            if p2.exists():
                return p2.read_text(encoding="utf-8")
        return ""

    competences_file_id = os.environ.get("COMPETENCES_FILE_ID")
    service = _build_service_read()

    if not competences_file_id:
        # Cherche dans le dossier racine ET le dossier collaborateurs
        search_folders = []
        root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        collab_id = os.environ.get("COLLABORATEURS_FOLDER_ID")
        if root_id:
            search_folders.append(root_id)
        if collab_id and collab_id != root_id:
            search_folders.append(collab_id)

        for folder_id in search_folders:
            # Cherche plusieurs variantes de nom
            q = (
                "'" + folder_id + "' in parents"
                " and (name = 'competences.yaml'"
                "   or name = '_competence.yaml'"
                "   or name = '_competences.yaml')"
                " and trashed = false"
            )
            res = service.files().list(q=q, fields="files(id,name)").execute()
            files = res.get("files", [])
            if files:
                competences_file_id = files[0]["id"]
                break

    if not competences_file_id:
        return ""

    return _download_raw(service, competences_file_id)


# ---------- Écriture ---------------------------------------------------------

def save_fiche_content(file_id, yaml_str):
    """Met à jour une fiche YAML collaborateur sur Drive (en place)."""
    if file_id.startswith("local::"):
        stem = file_id[len("local::"):]
        path = LOCAL_DIR / (stem + ".yaml")
        path.write_text(yaml_str, encoding="utf-8")
        return
    service = _build_service_write()
    _upload_content(service, file_id, yaml_str)


def save_competences(yaml_str):
    """Met à jour competences.yaml sur Drive."""
    if _is_local_mode():
        local_path = LOCAL_DIR.parent / "competences.yaml"
        local_path.write_text(yaml_str, encoding="utf-8")
        return

    competences_file_id = os.environ.get("COMPETENCES_FILE_ID")
    root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    service = _build_service_write()

    if not competences_file_id:
        q = "'" + root_id + "' in parents and name = 'competences.yaml' and trashed = false"
        res = service.files().list(q=q, fields="files(id)").execute()
        files = res.get("files", [])
        if not files:
            raise RuntimeError("competences.yaml introuvable dans Drive")
        competences_file_id = files[0]["id"]

    _upload_content(service, competences_file_id, yaml_str)


# ---------- Primitives -------------------------------------------------------

def _download_raw(service, file_id):
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read().decode("utf-8")


def _upload_content(service, file_id, content):
    media = MediaInMemoryUpload(
        content.encode("utf-8"),
        mimetype="application/octet-stream",
        resumable=False,
    )
    service.files().update(fileId=file_id, media_body=media).execute()
