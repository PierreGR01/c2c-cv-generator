"""
Client Google Drive — lecture des fiches collaborateurs + écriture (ingestion).
Auth via OAuth utilisateur (voir app/google_oauth.py et SETUP-OAUTH.md).

Source de données unique : Google Drive. Aucun mode de secours local.
"""
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

from . import google_oauth

_listing_cache = None
_listing_cache_ts = 0.0
_CACHE_TTL = 300


# ---------- Auth -------------------------------------------------------------
# OAuth utilisateur : une identité par personne, permissions enforced par les
# ACL Drive. Scope "drive" complet — l'app lit les fiches ET écrit (ingestion).
# gmail.send : notifications e-mail envoyées sous l'identité de l'utilisateur.
# Ce que l'utilisateur peut RÉELLEMENT faire ne dépend que du partage Drive
# accordé à SON compte, pas du code ci-dessous.
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]
APP_NAME = "c2c-tenders-app"


def authenticate():
    """Déclenche le consentement OAuth si nécessaire (appelé au démarrage)."""
    google_oauth.get_credentials(SCOPES, APP_NAME)


def _build_service_read():
    return google_oauth.build_drive(SCOPES, APP_NAME)


def _build_service_write():
    return google_oauth.build_drive(SCOPES, APP_NAME)


# ---------- Helpers ----------------------------------------------------------

def _is_collab_filename(name: str) -> bool:
    """False pour les fichiers non-collaborateurs (référentiel compétences,
    fichiers techniques préfixés _, versions V0_/V1_...)."""
    low = name.lower()
    if low.startswith(("_", "v0_", "v1_", "v2_")):
        return False
    if "competence" in low:   # competences.yaml, _competences.yaml, etc.
        return False
    return True


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


def _collab_entry_from_fiche(file_id, filename, fiche, modified=""):
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
        "title": display,          # utilisé par l'UI admin (éditeur de fiches)
        "filename": filename,
        "modified": modified,      # RFC3339 (Drive) ou ISO local
        "categorie": identite.get("categorie_poste") or "",
        "localisation": identite.get("localisation") or "",
    }


# ---------- Lecture ----------------------------------------------------------

def list_collaborateurs():
    """Liste les fiches collaborateurs (.yaml)."""
    global _listing_cache, _listing_cache_ts

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
    res = service.files().list(
        q=q, fields="files(id,name,modifiedTime)", orderBy="name").execute()
    # Exclure les fichiers non-collaborateurs (référentiels compétences/clients par nom OU par ID)
    competences_id = os.environ.get("COMPETENCES_FILE_ID")
    clients_id = os.environ.get("CLIENTS_FILE_ID")
    files = [
        f for f in res.get("files", [])
        if _is_collab_filename(f["name"]) and f["id"] not in (competences_id, clients_id)
    ]

    def _fetch(f):
        try:
            fiche = get_fiche(f["id"])
        except Exception:
            fiche = {}
        return _collab_entry_from_fiche(
            f["id"], f["name"], fiche, f.get("modifiedTime", ""))

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
    """Charge et parse une fiche YAML collaborateur depuis Drive."""
    service = _build_service_read()
    return yaml.safe_load(_download_raw(service, file_id)) or {}


def get_fiche_raw(file_id):
    """Charge le contenu YAML brut d'une fiche depuis Drive."""
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


def get_clients_raw():
    """Retourne le contenu brut de _clients.yaml (référentiel clients)."""
    clients_file_id = os.environ.get("CLIENTS_FILE_ID")
    service = _build_service_read()

    if not clients_file_id:
        # Cherche dans le dossier racine ET le dossier collaborateurs
        search_folders = []
        root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        collab_id = os.environ.get("COLLABORATEURS_FOLDER_ID")
        if root_id:
            search_folders.append(root_id)
        if collab_id and collab_id != root_id:
            search_folders.append(collab_id)

        for folder_id in search_folders:
            q = (
                "'" + folder_id + "' in parents"
                " and (name = 'clients.yaml' or name = '_clients.yaml')"
                " and trashed = false"
            )
            res = service.files().list(q=q, fields="files(id,name)").execute()
            files = res.get("files", [])
            if files:
                clients_file_id = files[0]["id"]
                break

    if not clients_file_id:
        return ""

    return _download_raw(service, clients_file_id)


# ---------- Écriture ---------------------------------------------------------

def save_fiche_content(file_id, yaml_str):
    """Met à jour une fiche YAML collaborateur sur Drive (en place)."""
    service = _build_service_write()
    _upload_content(service, file_id, yaml_str)


def save_competences(yaml_str):
    """Met à jour competences.yaml sur Drive."""
    competences_file_id = os.environ.get("COMPETENCES_FILE_ID")
    service = _build_service_write()
    if competences_file_id:
        _upload_content(service, competences_file_id, yaml_str)
        return
    # Cherche le fichier existant pour l'écraser
    root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if root_id:
        q = (
            "'" + root_id + "' in parents"
            " and (name = 'competences.yaml' or name = '_competences.yaml')"
            " and trashed = false"
        )
        res = service.files().list(q=q, fields="files(id,name)").execute()
        files = res.get("files", [])
        if files:
            _upload_content(service, files[0]["id"], yaml_str)


def save_clients(yaml_str):
    """Met à jour _clients.yaml sur Drive."""
    clients_file_id = os.environ.get("CLIENTS_FILE_ID")
    service = _build_service_write()
    if clients_file_id:
        _upload_content(service, clients_file_id, yaml_str)
        return
    # Cherche le fichier existant pour l'écraser
    root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if root_id:
        q = (
            "'" + root_id + "' in parents"
            " and (name = 'clients.yaml' or name = '_clients.yaml')"
            " and trashed = false"
        )
        res = service.files().list(q=q, fields="files(id,name)").execute()
        files = res.get("files", [])
        if files:
            _upload_content(service, files[0]["id"], yaml_str)


def _download_raw(service, file_id: str) -> str:
    """Télécharge le contenu brut d'un fichier Drive."""
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8")


def _upload_content(service, file_id: str, content: str) -> None:
    """Met à jour le contenu d'un fichier Drive existant."""
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain", resumable=False)
    service.files().update(fileId=file_id, media_body=media).execute()
    _invalidate_cache()


def _invalidate_cache():
    global _listing_cache, _listing_cache_ts
    _listing_cache = None
    _listing_cache_ts = 0.0


def create_fiche(filename: str, yaml_str: str) -> str:
    """Crée une nouvelle fiche YAML dans le dossier collaborateurs. Retourne le file_id."""
    service = _build_service_write()
    folder_id = os.environ.get("COLLABORATEURS_FOLDER_ID")
    if not folder_id:
        root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        folder_id = _get_subfolder_id(service, root_id, "collaborateurs")
    metadata = {"name": filename, "parents": [folder_id], "mimeType": "application/octet-stream"}
    media = MediaInMemoryUpload(yaml_str.encode("utf-8"), mimetype="application/octet-stream", resumable=False)
    created = service.files().create(body=metadata, media_body=media, fields="id").execute()
    _invalidate_cache()
    return created["id"]


def delete_fiche(file_id: str) -> None:
    """Supprime une fiche (corbeille Drive)."""
    service = _build_service_write()
    service.files().update(fileId=file_id, body={"trashed": True}).execute()
    _invalidate_cache()


def get_current_user_email() -> str:
    """E-mail du compte OAuth connecté (pour la détection de rôle)."""
    try:
        service = _build_service_read()
        about = service.about().get(fields="user(emailAddress)").execute()
        return (about.get("user", {}) or {}).get("emailAddress", "") or ""
    except Exception:
        return ""
