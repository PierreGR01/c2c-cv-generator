"""
Rôle admin + destinataires de notification — liés à un RÔLE, pas à un individu.

Source de vérité (par ordre de priorité) :
  1. Fichier `_app-config.yaml` à la racine du Drive (GOOGLE_DRIVE_FOLDER_ID) :
       admins:
         - pierre.grambert@camptocamp.com
       notifications:
         enabled: true
         recipients: []        # vide => on notifie les admins
  2. Variables d'environnement : ADMINS, NOTIFY_RECIPIENTS (emails séparés par des virgules).

Changer d'admin = éditer `_app-config.yaml` sur le Drive. Aucun changement de code,
aucune dépendance à un email individuel codé en dur.
"""
import os
import time

import yaml

_cache = None
_cache_ts = 0.0
_TTL = 300


def _env_list(name):
    raw = os.environ.get(name, "") or ""
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _load_from_drive():
    try:
        service = drive._build_service_read()
        root_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        if not root_id:
            return {}
        q = "'" + root_id + "' in parents and name = '_app-config.yaml' and trashed = false"
        res = service.files().list(q=q, fields="files(id)").execute()
        files = res.get("files", [])
        if not files:
            return {}
        raw = drive._download_raw(service, files[0]["id"])
        return yaml.safe_load(raw) or {}
    except Exception:
        return {}


def _config():
    global _cache, _cache_ts
    if _cache is not None and (time.time() - _cache_ts) < _TTL:
        return _cache
    _cache = _load_from_drive()
    _cache_ts = time.time()
    return _cache


def get_admins():
    cfg = _config()
    admins = [str(a).strip().lower() for a in (cfg.get("admins") or []) if str(a).strip()]
    return admins or _env_list("ADMINS")


def is_admin(email):
    return bool(email) and email.strip().lower() in get_admins()


def get_notify_recipients():
    cfg = _config()
    notif = cfg.get("notifications") or {}
    recipients = [str(r).strip() for r in (notif.get("recipients") or []) if str(r).strip()]
    if not recipients:
        recipients = _env_list("NOTIFY_RECIPIENTS")
    return recipients or get_admins()   # défaut : notifier les admins


def notifications_enabled():
    cfg = _config()
    notif = cfg.get("notifications") or {}
    if "enabled" in notif:
        return bool(notif.get("enabled"))
    return bool(get_notify_recipients())
