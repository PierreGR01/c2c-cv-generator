"""
Client Google Drive — lecture des fiches collaborateurs + écriture (ingestion).
Auth via OAuth utilisateur (voir app/google_oauth.py et SETUP-OAUTH.md).

Source de données unique : Google Drive. Aucun mode de secours local.
"""
import io
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

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


def list_trashed_collaborateurs():
    """Liste les fiches collaborateurs passées à la corbeille (Drive trashed=true)."""
    service = _build_service_read()
    folder_id = os.environ.get("COLLABORATEURS_FOLDER_ID")
    if not folder_id:
        root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        folder_id = _get_subfolder_id(service, root_id, "collaborateurs")
    if not folder_id:
        return []

    q = "'" + folder_id + "' in parents and name contains '.yaml' and trashed = true"
    raw_files = []
    page_token = None
    while True:
        res = service.files().list(
            q=q, fields="nextPageToken,files(id,name,modifiedTime,trashedTime,trashingUser)",
            orderBy="name", pageSize=1000, pageToken=page_token).execute()
        raw_files.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    competences_id = os.environ.get("COMPETENCES_FILE_ID")
    clients_id = os.environ.get("CLIENTS_FILE_ID")
    files = [
        f for f in raw_files
        if _is_collab_filename(f["name"]) and f["id"] not in (competences_id, clients_id)
    ]

    def _fetch(f):
        try:
            fiche = get_fiche(f["id"])
        except Exception:
            fiche = {}
        entry = _collab_entry_from_fiche(f["id"], f["name"], fiche, f.get("modifiedTime", ""))
        entry["deleted_at"] = f.get("trashedTime", "")
        entry["deleted_by"] = (f.get("trashingUser") or {}).get("emailAddress", "")
        return entry

    result = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch, f): f for f in files}
        for fut in as_completed(futures):
            result.append(fut.result())
    result.sort(key=lambda x: x.get("deleted_at", ""), reverse=True)
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


def _find_corbeille_file_id(service):
    corbeille_file_id = os.environ.get("CORBEILLE_FILE_ID")
    if corbeille_file_id:
        return corbeille_file_id
    root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not root_id:
        return None
    q = "'" + root_id + "' in parents and name = '_corbeille.yaml' and trashed = false"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _get_or_create_corbeille_file_id(service):
    file_id = _find_corbeille_file_id(service)
    if file_id:
        return file_id
    root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    if not root_id:
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID manquant : impossible de créer _corbeille.yaml")
    metadata = {"name": "_corbeille.yaml", "parents": [root_id], "mimeType": "application/octet-stream"}
    media = MediaInMemoryUpload(b"items: []\n", mimetype="application/octet-stream", resumable=False)
    created = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return created["id"]


def get_corbeille_items():
    """Retourne les entrées de la corbeille (clients, etc. — pas les fiches, gérées via Drive trash)."""
    service = _build_service_read()
    file_id = _find_corbeille_file_id(service)
    if not file_id:
        return []
    raw = _download_raw(service, file_id)
    data = yaml.safe_load(raw) or {}
    return data.get("items") or []


def _save_corbeille_items(items) -> None:
    service = _build_service_write()
    file_id = _get_or_create_corbeille_file_id(service)
    content = yaml.safe_dump({"items": items}, allow_unicode=True, sort_keys=False)
    _upload_content(service, file_id, content)


def trash_client(client_data: dict, actor_email: str = "") -> None:
    """Dépose un client retiré du référentiel dans la corbeille."""
    items = get_corbeille_items()
    items.append({
        "id": str(uuid.uuid4()),
        "type": "client",
        "deleted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deleted_by": actor_email or "",
        "data": client_data,
    })
    _save_corbeille_items(items)


def restore_client(item_id: str) -> dict:
    """Retire une entrée client de la corbeille et la ré-ajoute au référentiel. Retourne les données restaurées."""
    items = get_corbeille_items()
    keep, found = [], None
    for it in items:
        if it.get("id") == item_id and it.get("type") == "client":
            found = it
        else:
            keep.append(it)
    if found is None:
        raise ValueError("Élément de corbeille introuvable : " + item_id)
    _save_corbeille_items(keep)

    raw = get_clients_raw()
    data = (yaml.safe_load(raw) or {}) if raw else {}
    clients = data.get("clients") or []
    clients.append(found["data"])
    data["clients"] = clients
    save_clients(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return found["data"]


def purge_corbeille_item(item_id: str) -> None:
    """Supprime définitivement une entrée de la corbeille (hors fiches collaborateurs)."""
    items = get_corbeille_items()
    remaining = [it for it in items if it.get("id") != item_id]
    _save_corbeille_items(remaining)


def update_corbeille_item(item_id: str, new_data: dict) -> None:
    """Édite le contenu (`data`) d'une entrée en corbeille, sans la restaurer."""
    items = get_corbeille_items()
    found = False
    for it in items:
        if it.get("id") == item_id:
            it["data"] = new_data
            found = True
            break
    if not found:
        raise ValueError("Élément de corbeille introuvable : " + item_id)
    _save_corbeille_items(items)


# ---------- Écriture ---------------------------------------------------------

def save_fiche_content(file_id, yaml_str):
    """Met à jour une fiche YAML collaborateur sur Drive (en place)."""
    service = _build_service_write()
    _upload_content(service, file_id, yaml_str)


def save_competences(yaml_str):
    """Met à jour competences.yaml sur Drive."""
    competences_file_id = os.environ.get("COMPETENCES_FILE_ID")
    service = _build_service_write()
    if not competences_file_id:
        # Cherche le fichier existant (racine PUIS dossier collaborateurs) pour l'écraser
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
                " and (name = 'competences.yaml' or name = '_competences.yaml')"
                " and trashed = false"
            )
            res = service.files().list(q=q, fields="files(id,name)").execute()
            files = res.get("files", [])
            if files:
                competences_file_id = files[0]["id"]
                break
    if not competences_file_id:
        raise RuntimeError("Fichier competences.yaml introuvable sur Drive : impossible d'enregistrer.")
    _upload_content(service, competences_file_id, yaml_str)


def save_clients(yaml_str):
    """Met à jour _clients.yaml sur Drive."""
    clients_file_id = os.environ.get("CLIENTS_FILE_ID")
    service = _build_service_write()
    if not clients_file_id:
        # Cherche le fichier existant (racine PUIS dossier collaborateurs) pour l'écraser
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
        raise RuntimeError("Fichier _clients.yaml introuvable sur Drive : impossible d'enregistrer.")
    _upload_content(service, clients_file_id, yaml_str)


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


def restore_fiche(file_id: str) -> None:
    """Restaure une fiche depuis la corbeille Drive."""
    service = _build_service_write()
    service.files().update(fileId=file_id, body={"trashed": False}).execute()
    _invalidate_cache()


def delete_fiche_forever(file_id: str) -> None:
    """Purge définitivement une fiche (hors corbeille Drive — irréversible)."""
    service = _build_service_write()
    service.files().delete(fileId=file_id).execute()
    _invalidate_cache()


def get_current_user_email() -> str:
    """E-mail du compte OAuth connecté (pour la détection de rôle)."""
    try:
        service = _build_service_read()
        about = service.about().get(fields="user(emailAddress)").execute()
        return (about.get("user", {}) or {}).get("emailAddress", "") or ""
    except Exception:
        return ""
