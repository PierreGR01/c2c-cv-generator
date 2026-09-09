"""
C2C Tenders App — API FastAPI (génération de CV + ingestion fin de projet + édition fiches).
"""
import io
import json
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Annotated, Optional, List
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")  # charge le .env de l'app quel que soit le cwd

import yaml
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config, drive, gmail_notify, ingest, reference_renderer, reference_service, renderer, scorer

app = FastAPI(title="C2C Tenders App — Camptocamp")

STATIC_DIR = Path(__file__).parent.parent / "static"


# ---------------------------------------------------------------------------
# API — Collaborateurs
# ---------------------------------------------------------------------------

@app.get("/api/collaborateurs")
async def list_collaborateurs():
    """Liste les collaborateurs disponibles sur Drive."""
    try:
        return drive.list_collaborateurs()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/debug/scores/{file_id}")
async def debug_scores(file_id: str):
    """Debug : affiche les scores de tous les projets d'une fiche."""
    try:
        fiche = drive.get_fiche(file_id)
        cible = {"technologies_cles": [], "domaines": []}
        scored = scorer.scorer_projets(fiche, cible)
        return {"projets": scored, "scorer_version": "recency_v2"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/debug/projection/{file_id}")
async def debug_projection(file_id: str, max_projets: int = 4, client_refs: str = ""):
    """Debug : affiche la sélection finale envoyée au renderer."""
    try:
        fiche = drive.get_fiche(file_id)
        cible = {
            "technologies_cles": [], "domaines": [], "max_projets": max_projets,
            "client_refs": [c.strip() for c in client_refs.split(",") if c.strip()],
        }
        data = scorer.projeter_cible(fiche, cible)
        return {
            "nb_projets_selectionnes": len(data["projets"]),
            "projets": [
                {"client": p.get("client", ""), "designation": p.get("designation", ""), "periode": p.get("periode", "")}
                for p in data["projets"]
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Générateur CVs
# ---------------------------------------------------------------------------

@app.post("/api/generate")
async def generate_cvs(
    collaborateurs: Annotated[List[str], Form()],
    max_projets: Annotated[int, Form()] = 4,
    max_pages: Annotated[int, Form()] = 1,
    inclure_parcours: Annotated[bool, Form()] = True,
    masquer_designations: Annotated[bool, Form()] = False,
    annee_min: Annotated[int, Form()] = 0,
    secteur: Annotated[str, Form()] = "",
    domaines: Annotated[Optional[List[str]], Form()] = None,
    competences: Annotated[Optional[List[str]], Form()] = None,
    client_refs: Annotated[Optional[List[str]], Form()] = None,
    profils: Annotated[Optional[str], Form()] = None,
    lang: Annotated[str, Form()] = "fr",
):
    """
    Génère un ou plusieurs CVs ciblés par filtres (ou génériques si pas de filtre).

    - collaborateurs   : liste de drive_file_ids
    - max_projets      : nombre max de projets par CV (0 = tous, défaut 4)
    - max_pages        : limite de pages (1, 2, ou 0 = sans limite, défaut 1)
    - inclure_parcours : inclure le parcours professionnel antérieur (défaut True)
    - masquer_designations : n'afficher que le nom du client, sans la désignation de projet (défaut False)
    - annee_min        : exclure les projets antérieurs à cette année (0 = sans limite)
    - secteur          : filtrer par secteur ("public", "prive", ou "" = tous)
    - domaines         : liste de domaines à valoriser (ids canoniques)
    - competences      : liste de compétences clés à valoriser
    - client_refs      : liste de clients (référentiel) dont les projets sont priorisés
    - profils          : JSON {drive_file_id: profil_cle} — force le profil (paragraphe) affiché
                         pour tel ou tel collaborateur, indépendamment du ciblage AO
    - lang             : langue de rendu du CV ("fr" ou "en", défaut "fr")
    """
    if lang not in ("fr", "en"):
        raise HTTPException(status_code=400, detail=f"Langue non supportée : {lang!r} (attendu 'fr' ou 'en')")

    domaines_list = domaines or []
    competences_list = competences or []
    client_refs_list = client_refs or []
    try:
        profils_map = json.loads(profils) if profils else {}
    except ValueError:
        profils_map = {}

    cible: dict = {
        "technologies_cles": competences_list,
        "domaines": domaines_list,
        "client_refs": client_refs_list,
        "max_projets": max_projets,
        "inclure_parcours": inclure_parcours,
        "masquer_designations": masquer_designations,
        "annee_min": annee_min,
    }
    if secteur in ("public", "prive"):
        cible["secteur"] = secteur

    # Nom du fichier de sortie
    if domaines_list or competences_list or client_refs_list or secteur or annee_min:
        ao_stem = "cible"
        if secteur:
            ao_stem += f"-{secteur}"
        if annee_min:
            ao_stem += f"-depuis{annee_min}"
        if client_refs_list:
            ao_stem += "-clients"
    else:
        ao_stem = "generique"

    if lang == "en":
        ao_stem += "-en"

    pdfs: dict[str, bytes] = {}
    warnings: dict[str, str] = {}

    for file_id in collaborateurs:
        try:
            fiche = drive.get_fiche(file_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fiche introuvable ({file_id}) : {e}")

        id_section = fiche.get("identite", {})
        prenom = id_section.get("prenom", "inconnu").lower()
        nom = id_section.get("nom", "").lower()
        collab_stem = f"{prenom}-{nom}".replace(" ", "-")
        pdf_filename = f"cv-{collab_stem}--{ao_stem}.pdf"

        cible_collab = cible
        if profils_map.get(file_id):
            cible_collab = {**cible, "profil_cle": profils_map[file_id]}

        try:
            data = scorer.projeter_cible(fiche, cible_collab, lang=lang)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur scoring ({collab_stem}) : {e}")

        try:
            pdf_bytes, _, warning = renderer.render_cv_to_bytes(data, max_projets=max_projets, max_pages=max_pages)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur rendu ({collab_stem}) : {e}")

        pdfs[pdf_filename] = pdf_bytes
        if warning:
            warnings[pdf_filename] = warning

    if not pdfs:
        raise HTTPException(status_code=500, detail="Aucun PDF généré.")

    if len(pdfs) == 1:
        filename, pdf_bytes = next(iter(pdfs.items()))
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if warnings:
            headers["X-CV-Warning"] = quote(next(iter(warnings.values())))
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers=headers,
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, fbytes in pdfs.items():
            zf.writestr(fname, fbytes)
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="cvs-{ao_stem}.zip"'}
    if warnings:
        headers["X-CV-Warnings"] = quote(json.dumps(warnings, ensure_ascii=False))
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# API — Compétences (pour le formulaire CP)
# ---------------------------------------------------------------------------

_FAMILY_LABELS = scorer._FAMILY_LABELS

_FAMILY_META = {
    "cartographie_web":         "Carto & SIG",
    "serveurs_carto":           "Carto & SIG",
    "sig_desktop":              "Carto & SIG",
    "catalogues_metadonnees":   "Carto & SIG",
    "langages":                 "Développeurs",
    "bases_de_donnees":         "Développeurs",
    "etl_donnees":              "Développeurs",
    "frameworks_backend":       "Développeurs",
    "frameworks_frontend":      "Développeurs",
    "ia_ml":                    "Développeurs",
    "mobile":                   "Développeurs",
    "tests":                    "Développeurs",
    "outils_dev":               "Développeurs",
    "cms":                      "Développeurs",
    "3d_visualisation":         "Développeurs",
    "infrastructure":           "DevOps & Infrastructure",
    "monitoring_bi":            "DevOps & Infrastructure",
    "reseau_telecom_securite":  "DevOps & Infrastructure",
    "design_systems":           "Designers & UX",
    "design_ui":                "Designers & UX",
    "design_ux":                "Designers & UX",
    "methodes_ux":              "Designers & UX",
    "Product":                  "Designers & UX",
    "gestion_conseil":          "Chefs de projet & Conseil",
    "erp_odoo":                 "Chefs de projet & Conseil",
}

_META_ORDER = [
    "Carto & SIG",
    "Développeurs",
    "DevOps & Infrastructure",
    "Designers & UX",
    "Chefs de projet & Conseil",
]


@app.get("/api/competences")
async def get_competences():
    """Retourne les familles de compétences groupées par méta-catégorie (pour le formulaire CP)."""
    try:
        raw = drive.get_competences_raw()
        if not raw:
            return []
        data = yaml.safe_load(raw) or {}
        result = []
        for key, items in data.items():
            # Ignorer la section domaines (dict, pas une liste de strings)
            if not isinstance(items, list):
                continue
            flat_items = [i for i in items if isinstance(i, str)]
            if not flat_items:
                continue
            label = _FAMILY_LABELS.get(key, key.replace("_", " ").title())
            meta = _FAMILY_META.get(key, "Autres")
            result.append({"key": key, "label": label, "meta": meta, "items": flat_items})
        # Tri par méta-catégorie puis par label
        meta_rank = {m: i for i, m in enumerate(_META_ORDER)}
        result.sort(key=lambda f: (meta_rank.get(f["meta"], 99), f["label"]))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/debug/filtres")
async def debug_filtres():
    """Debug : diagnostique la lecture des domaines."""
    try:
        raw = drive.get_competences_raw()
        if not raw:
            return {"raw_len": 0, "keys": [], "domaines_keys": []}
        data = yaml.safe_load(raw) or {}
        dom = data.get("domaines", {})
        return {
            "raw_len": len(raw),
            "raw_head": raw[:200],
            "top_keys": list(data.keys()),
            "domaines_type": type(dom).__name__,
            "domaines_keys": list(dom.keys()) if isinstance(dom, dict) else str(dom)[:100],
            "n_principaux": len(dom.get("principaux", [])) if isinstance(dom, dict) else -1,
            "n_sous": len(dom.get("sous_domaines", [])) if isinstance(dom, dict) else -1,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/filtres")
async def get_filtres():
    """Retourne la liste des domaines pour les filtres de ciblage AO."""
    try:
        raw = drive.get_competences_raw()
        if not raw:
            return {"domaines": []}
        data = yaml.safe_load(raw) or {}
        domaines_section = data.get("domaines", {})
        result = []
        for entry in domaines_section.get("principaux", []):
            result.append({
                "id": entry.get("id", ""),
                "label": entry.get("label", ""),
                "group": "Grands domaines",
            })
        for entry in domaines_section.get("sous_domaines", []):
            result.append({
                "id": entry.get("id", ""),
                "label": entry.get("label", ""),
                "group": "Sous-domaines",
            })
        return {"domaines": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Clients (référentiel, pour le ciblage AO et la déclaration de projet)
# ---------------------------------------------------------------------------

@app.get("/api/clients")
async def get_clients():
    """Retourne la liste plate des clients (groupés par pays) pour les sélecteurs."""
    try:
        raw = drive.get_clients_raw()
        if not raw:
            return []
        data = yaml.safe_load(raw) or {}
        clients = data.get("clients", [])
        if not isinstance(clients, list):
            return []
        result = []
        for c in clients:
            if not isinstance(c, dict) or not c.get("nom"):
                continue
            result.append({
                "id": c["nom"],
                "label": c["nom"],
                "group": c.get("pays") or "Autres",
                "secteur": c.get("secteur", ""),
                "sous_entites": c.get("sous_entites") or [],
            })
        pays_priorite = {"France": 0, "Suisse": 1}
        result.sort(key=lambda c: (pays_priorite.get(c["group"], 2), c["group"], c["label"]))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/clients/raw")
async def api_clients_get():
    """Contenu brut du référentiel clients (édition admin structurée côté front)."""
    try:
        return JSONResponse({"content": drive.get_clients_raw()})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/clients/raw")
async def api_clients_save(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        drive.save_clients(body["content"])
        actor = drive.get_current_user_email()
        background_tasks.add_task(
            gmail_notify.notify, actor,
            "a modifié le référentiel clients",
            "Fichier : référentiel clients (_clients.yaml)")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clients/{index}/trash")
async def api_client_trash(index: int, request: Request, background_tasks: BackgroundTasks):
    """Retire un client du référentiel et le dépose en corbeille (action immédiate, réversible)."""
    try:
        body = await request.json()
        client_data = body["data"]
        raw = drive.get_clients_raw()
        data = (yaml.safe_load(raw) or {}) if raw else {}
        clients = data.get("clients") or []

        target = clients[index] if 0 <= index < len(clients) else None
        if not target or target.get("nom") != client_data.get("nom"):
            target = next((c for c in clients if c.get("nom") == client_data.get("nom")), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Client introuvable dans le référentiel")

        clients.remove(target)
        data["clients"] = clients
        drive.save_clients(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))

        actor = drive.get_current_user_email()
        drive.trash_client(target, actor)
        background_tasks.add_task(
            gmail_notify.notify, actor, "a mis un client à la corbeille",
            f"Client : {target.get('nom', '')}")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Rôle / identité
# ---------------------------------------------------------------------------

@app.get("/api/whoami")
async def whoami():
    """Compte connecté + rôle. Le rôle est indicatif (l'accès réel est enforced
    par les ACL Drive) : il sert uniquement à afficher/masquer l'UI admin."""
    email = drive.get_current_user_email()
    return {"email": email, "is_admin": config.is_admin(email)}


# ---------------------------------------------------------------------------
# API — Fiches maîtres (CRUD — édition directe, section admin)
# ---------------------------------------------------------------------------

@app.get("/api/collaborateurs/{file_id}")
async def api_get_fiche(file_id: str):
    try:
        return JSONResponse({"content": drive.get_fiche_raw(file_id)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/collaborateurs/{file_id}")
async def api_save_fiche(file_id: str, request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        content = body["content"]
        drive.save_fiche_content(file_id, content)
        # Notification (best-effort, en tâche de fond)
        actor = drive.get_current_user_email()
        nom = _fiche_display_from_yaml(content) or file_id
        background_tasks.add_task(
            gmail_notify.notify, actor, "a modifié une fiche YAML",
            f"Fiche : {nom}")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/collaborateurs")
async def api_create_fiche(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        file_id = drive.create_fiche(body["filename"], body["content"])
        actor = drive.get_current_user_email()
        background_tasks.add_task(
            gmail_notify.notify, actor, "a créé une fiche collaborateur",
            f"Fichier : {body.get('filename', '')}")
        return {"file_id": file_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/collaborateurs/{file_id}")
async def api_delete_fiche(file_id: str):
    try:
        drive.delete_fiche(file_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Projets (registre transversal — un fichier par projet, source des
# champs partagés entre les fiches collaborateurs qui y participent)
# ---------------------------------------------------------------------------

@app.get("/api/projets")
async def api_list_projets():
    """Liste légère des projets du registre (id, désignation, client, période,
    équipe avec noms résolus), pour la grille de cartes Administration > Projets."""
    try:
        projets = drive.list_projets()
        if projets:
            # Pas besoin du contenu complet des fiches ici, juste du nom
            # affiché — list_collaborateurs() est déjà en cache, contrairement
            # à get_collaborateurs_lookup() qui re-téléchargerait la fiche de
            # TOUTE l'organisation à chaque chargement de la liste.
            display_by_slug = {c["name"]: c["display"] for c in drive.list_collaborateurs()}
            for p in projets:
                for m in (p.get("equipe") or []):
                    m["display"] = display_by_slug.get(m.get("collaborateur"), m.get("collaborateur"))
        return projets
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projets/{file_id}/detail")
async def api_get_projet_detail(file_id: str):
    """Détail hydraté d'un projet (champs communs + membres avec leurs données
    individuelles lues dans leur propre fiche) — pour pré-remplir le
    formulaire d'édition depuis Administration > Projets."""
    try:
        projet = drive.get_projet(file_id)
        slugs = [m.get("collaborateur") for m in (projet.get("equipe") or []) if isinstance(m, dict)]
        collab_lookup = drive.get_collaborateurs_lookup_for(slugs)
        detail = ingest.hydrate_projet_detail(projet, collab_lookup)
        detail["file_id"] = file_id
        return detail
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/projets/{file_id}")
async def api_delete_projet(file_id: str, background_tasks: BackgroundTasks):
    """Met un projet du registre à la corbeille Drive (réversible). Ne touche
    pas aux fiches collaborateurs déjà liées — retrait individuel si besoin via
    le formulaire d'édition existant (cf. PLAN-dissocier-validation.md)."""
    try:
        projet = drive.get_projet(file_id)
        drive.trash_projet(file_id)
        actor = drive.get_current_user_email()
        nom = projet.get("designation") or projet.get("id") or file_id
        background_tasks.add_task(
            gmail_notify.notify, actor, "a mis un projet à la corbeille",
            f"Projet : {nom}")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projets/{file_id}")
async def api_get_projet(file_id: str):
    try:
        return JSONResponse({"content": drive.get_projet_raw(file_id)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/projets/{file_id}")
async def api_save_projet(file_id: str, request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        content = body["content"]
        drive.save_projet_content(file_id, content)
        actor = drive.get_current_user_email()
        background_tasks.add_task(
            gmail_notify.notify, actor, "a modifié une fiche projet",
            f"Fichier : {file_id}")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Images d'un projet (registre transversal) — upload immédiat,
# indépendant du formulaire de déclaration/édition (pas de brouillon local).
# ---------------------------------------------------------------------------

ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _validate_chapitre(chapitre: str) -> str:
    """Vide = image libre. Sinon doit être un des 4 chapitres illustrables
    (jamais 'technique', volontairement toujours en texte seul — cf.
    reference_renderer.CHAPITRE_IMAGE_KEYS)."""
    chapitre = (chapitre or "").strip()
    if chapitre and chapitre not in reference_renderer.CHAPITRE_IMAGE_KEYS:
        raise HTTPException(status_code=400, detail=f"Chapitre invalide : {chapitre!r}")
    return chapitre


def _replace_slot_images(images: list[dict], chapitre: str) -> list[dict]:
    """Retire, s'il existe, l'image occupant déjà le même slot (le chapitre
    donné, ou l'image libre si chapitre==""), et la met à la corbeille Drive —
    au plus une image par chapitre, au plus une image libre (cf. plan §1)."""
    kept = []
    for im in images:
        if (im.get("chapitre") or "") == chapitre:
            try:
                drive.delete_projet_image(im["fichier_drive_id"])
            except Exception:
                pass
            continue
        kept.append(im)
    return kept


@app.post("/api/projets/{file_id}/images")
async def api_add_projet_image(
    file_id: str,
    image: UploadFile = File(...),
    legende: Annotated[str, Form()] = "",
    chapitre: Annotated[str, Form()] = "",
):
    try:
        chapitre = _validate_chapitre(chapitre)
        content = await image.read()
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image trop volumineuse (max 8 Mo).")
        mimetype = image.content_type or mimetypes.guess_type(image.filename or "")[0] or ""
        if mimetype not in ALLOWED_IMAGE_MIMES:
            raise HTTPException(status_code=400, detail="Format non supporté (png, jpg, webp, gif uniquement).")

        projet = drive.get_projet(file_id)
        projet_id = projet.get("id") or file_id
        image_file_id = drive.upload_projet_image(projet_id, image.filename or "image", content, mimetype)

        images = _replace_slot_images(projet.get("images") or [], chapitre)
        images.append({
            "fichier_drive_id": image_file_id, "nom": image.filename or "",
            "legende": legende or "", "chapitre": chapitre,
        })
        projet["images"] = images
        drive.save_projet_content(file_id, yaml.safe_dump(projet, allow_unicode=True, sort_keys=False))
        return {"ok": True, "images": images}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projets/{file_id}/images/{image_id}")
async def api_get_projet_image(file_id: str, image_id: str):
    try:
        content, mimetype = drive.get_projet_image_bytes(image_id)
        return Response(content=content, media_type=mimetype)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.patch("/api/projets/{file_id}/images/{image_id}")
async def api_patch_projet_image(
    file_id: str,
    image_id: str,
    chapitre: Annotated[Optional[str], Form()] = None,
    legende: Annotated[Optional[str], Form()] = None,
):
    """Réassigne le chapitre (et/ou la légende) d'une image déjà en place, sans
    re-upload. Mêmes règles de remplacement qu'à l'ajout (D1 — cf. plan §5)."""
    try:
        projet = drive.get_projet(file_id)
        images = projet.get("images") or []
        target = next((im for im in images if im.get("fichier_drive_id") == image_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Image introuvable pour ce projet.")

        if chapitre is not None:
            chapitre = _validate_chapitre(chapitre)
            images = [im for im in images if im.get("fichier_drive_id") != image_id]
            images = _replace_slot_images(images, chapitre)
            target["chapitre"] = chapitre
            images.append(target)
        if legende is not None:
            target["legende"] = legende

        projet["images"] = images
        drive.save_projet_content(file_id, yaml.safe_dump(projet, allow_unicode=True, sort_keys=False))
        return {"ok": True, "images": images}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/projets/{file_id}/images/{image_id}")
async def api_delete_projet_image(file_id: str, image_id: str):
    try:
        projet = drive.get_projet(file_id)
        images = [im for im in (projet.get("images") or []) if im.get("fichier_drive_id") != image_id]
        projet["images"] = images
        drive.save_projet_content(file_id, yaml.safe_dump(projet, allow_unicode=True, sort_keys=False))
        drive.delete_projet_image(image_id)
        return {"ok": True, "images": images}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Portefolio de références (assemblage de N fiches projet en un PDF)
# ---------------------------------------------------------------------------

def _slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (s or "").lower()).strip()
    return re.sub(r"[-\s]+", "-", s) or "portefolio"


@app.post("/api/portefolio/generate")
async def generate_portefolio(
    background_tasks: BackgroundTasks,
    projets: Annotated[List[str], Form()],
    titre: Annotated[str, Form()] = "",
    sous_titre: Annotated[str, Form()] = "",
    chapitres: Annotated[Optional[List[str]], Form()] = None,
    inclure_equipe: Annotated[bool, Form()] = True,
    inclure_competences: Annotated[bool, Form()] = True,
    inclure_images: Annotated[bool, Form()] = True,
):
    """Génère un PDF « Références projets » à partir de N projets du registre.
    1 projet → pas de couverture (cf. reference-projets.typ, B3 du plan) ;
    ≥2 projets → couverture + index, avec ses deux titres personnalisables.

    `titre` nomme le document : grand titre de couverture, et mention du pied
    de page de chaque fiche. `sous_titre` nomme la sélection (l'appel d'offre,
    le client…) et compose le nom du fichier. Les deux sont vides par défaut
    et retombent alors sur les libellés d'origine — le formulaire, lui, les
    envoie toujours renseignés."""
    if not projets:
        raise HTTPException(status_code=400, detail="Aucun projet sélectionné.")
    try:
        hydrated = reference_service.build_projets_for_render(projets)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du chargement des projets : {e}")

    options = {
        "chapitres": chapitres or reference_renderer.CHAPITRE_ORDER,
        "inclure_equipe": inclure_equipe,
        "inclure_competences": inclure_competences,
        "inclure_images": inclure_images,
        "titre": titre or "Références projets",
        "sous_titre": sous_titre or "Sélection de projets Camptocamp",
    }

    try:
        projets_data = reference_renderer.build_projets_data(hydrated, options)
        pdf_bytes = reference_renderer.render_pdf(projets_data, options)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du rendu du portefolio : {e}")

    if len(projets_data) > 1:
        # Le nom du fichier suit le SOUS-titre : c'est lui qui désigne la
        # sélection, quand le titre nomme le type de document.
        filename = f"portefolio-{_slugify(options['sous_titre'])}.pdf"
    else:
        designation = projets_data[0].get("designation") or projets_data[0].get("client") or "projet"
        filename = f"fiche-projet-{_slugify(designation)}.pdf"

    actor = drive.get_current_user_email()
    background_tasks.add_task(
        gmail_notify.notify, actor, "a généré un portefolio de références",
        f"{len(projets_data)} projet(s) : " + ", ".join(p.get("designation") or p.get("client") or "?" for p in projets_data))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# API — Ingestion fiche fin de projet (auto-ingestion depuis le formulaire CP)
# ---------------------------------------------------------------------------

@app.post("/api/fiche/parse")
async def api_fiche_parse(
    fiche_yaml: Annotated[str, Form()],
    projet_file_id: Annotated[str, Form()] = "",
):
    """Analyse la fiche fin de projet et retourne l'aperçu des modifications.

    projet_file_id : envoyé uniquement en édition d'un projet existant
    (Administration > Projets) — désigne le fichier du registre à relire puis
    réécrire, sans repasser par une recherche par nom.
    """
    try:
        # Seuls les membres soumis dans CE formulaire sont concernés — inutile
        # de télécharger la fiche de tout le monde (get_collaborateurs_lookup).
        # YAML invalide : slugs vide, parse_fiche_cp détecte l'erreur avant
        # même d'utiliser collab_lookup.
        slugs = []
        try:
            parsed = yaml.safe_load(fiche_yaml) or {}
            slugs = [
                (m.get("collaborateur") or "").strip()
                for m in (parsed.get("membres") or []) if isinstance(m, dict)
            ]
        except yaml.YAMLError:
            pass
        collab_lookup = drive.get_collaborateurs_lookup_for(slugs)
        competences_yaml = drive.get_competences_raw()
        return ingest.parse_fiche_cp(
            fiche_yaml, collab_lookup, competences_yaml, projet_file_id=projet_file_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fiche/apply")
async def api_fiche_apply(request: Request, background_tasks: BackgroundTasks):
    """Applique l'aperçu validé : écrit les fiches maîtres sur Drive."""
    try:
        preview = await request.json()
        # Idem : uniquement les membres soumis + l'équipe/les retraits portés
        # par le registre projet, jamais l'organisation entière.
        registry = preview.get("registry") or {}
        slugs = {m.get("slug") for m in (preview.get("membres") or []) if isinstance(m, dict) and m.get("slug")}
        slugs |= {m.get("collaborateur") for m in (registry.get("equipe") or []) if isinstance(m, dict) and m.get("collaborateur")}
        slugs |= {s for s in (registry.get("removed_membres") or []) if s}
        collab_lookup = drive.get_collaborateurs_lookup_for(slugs)
        competences_yaml = drive.get_competences_raw()
        ecrire_cv = bool(preview.get("ecrire_cv", True))
        results, _ = ingest.apply_fiche_cp(preview, collab_lookup, competences_yaml, ecrire_cv=ecrire_cv)

        actor = drive.get_current_user_email()
        projet = (preview.get("projet") or {})
        projet_nom = projet.get("designation") or projet.get("id") or "projet"
        touched = [r.get("display") or r.get("slug") for r in results if r.get("ok") and r.get("slug") != "_cv_ignore_"]
        details = (
            f"Projet : {projet_nom}\n"
            f"Client : {projet.get('client_ref', '')}\n"
            f"Fiches mises à jour : {', '.join(touched) if touched else 'aucune'}"
        )
        action_label = "a enregistré une fiche projet" if not ecrire_cv else "a créé une fiche de fin de projet (ingestion)"
        background_tasks.add_task(
            gmail_notify.notify, actor,
            action_label, details)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _fiche_display_from_yaml(content: str) -> str:
    """Extrait 'Prénom Nom' d'une fiche YAML pour un libellé de notification lisible."""
    try:
        data = yaml.safe_load(content) or {}
        ident = data.get("identite", {}) if isinstance(data, dict) else {}
        nom = (str(ident.get("prenom", "")) + " " + str(ident.get("nom", ""))).strip()
        return nom
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# API — Données communes projets (référentiel de compétences)
# ---------------------------------------------------------------------------

@app.get("/api/competences/raw")
async def api_competences_get():
    """Contenu brut du référentiel de compétences (données communes projets)."""
    try:
        return JSONResponse({"content": drive.get_competences_raw()})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/competences/raw")
async def api_competences_save(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        drive.save_competences(body["content"])
        actor = drive.get_current_user_email()
        background_tasks.add_task(
            gmail_notify.notify, actor,
            "a modifié les données communes projets",
            "Fichier : référentiel de compétences (_competences.yaml)")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Corbeille (fiches collaborateurs + clients supprimés, restaurables)
# ---------------------------------------------------------------------------

@app.get("/api/corbeille")
async def api_corbeille_list():
    """Liste unifiée des éléments en corbeille (regroupement par type côté front)."""
    try:
        result = []
        for c in drive.list_trashed_collaborateurs():
            result.append({
                "type": "collaborateur",
                "id": c["id"],
                "title": c["display"] or c["filename"],
                "subtitle": c.get("categorie") or c.get("localisation") or "",
                "data": c,
                "deleted_at": c.get("deleted_at", ""),
                "deleted_by": c.get("deleted_by", ""),
            })
        for it in drive.get_corbeille_items():
            if it.get("type") != "client":
                continue
            d = it.get("data") or {}
            result.append({
                "type": "client",
                "id": it.get("id", ""),
                "title": d.get("nom") or "(sans nom)",
                "subtitle": d.get("pays") or "",
                "data": d,
                "deleted_at": it.get("deleted_at", ""),
                "deleted_by": it.get("deleted_by", ""),
            })
        for p in drive.list_trashed_projets():
            result.append({
                "type": "projet",
                "id": p["id"],
                "title": p.get("designation") or p.get("projet_id") or "(sans nom)",
                "subtitle": " / ".join(p.get("client_ref") or []) or p.get("periode", ""),
                "data": p,
                "deleted_at": p.get("deleted_at", ""),
                "deleted_by": p.get("deleted_by", ""),
            })
        result.sort(key=lambda x: x.get("deleted_at", ""), reverse=True)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/corbeille/{item_type}/{item_id}/restore")
async def api_corbeille_restore(item_type: str, item_id: str, background_tasks: BackgroundTasks):
    try:
        actor = drive.get_current_user_email()
        if item_type == "collaborateur":
            drive.restore_fiche(item_id)
            detail = "Fiche collaborateur restaurée depuis la corbeille"
        elif item_type == "client":
            restored = drive.restore_client(item_id)
            detail = f"Client restauré depuis la corbeille : {restored.get('nom', '')}"
        elif item_type == "projet":
            drive.restore_projet(item_id)
            detail = "Projet restauré depuis la corbeille"
        else:
            raise HTTPException(status_code=400, detail="Type inconnu : " + item_type)
        background_tasks.add_task(
            gmail_notify.notify, actor, "a restauré un élément depuis la corbeille", detail)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/corbeille/{item_type}/{item_id}")
async def api_corbeille_update(item_type: str, item_id: str, request: Request, background_tasks: BackgroundTasks):
    """Édite le contenu d'un élément pendant qu'il est en corbeille (sans le restaurer)."""
    try:
        body = await request.json()
        actor = drive.get_current_user_email()
        if item_type == "collaborateur":
            drive.save_fiche_content(item_id, body["content"])
            detail = "Fiche collaborateur (en corbeille) modifiée"
        elif item_type == "client":
            drive.update_corbeille_item(item_id, body["data"])
            detail = "Client (en corbeille) modifié"
        else:
            raise HTTPException(status_code=400, detail="Type inconnu : " + item_type)
        background_tasks.add_task(
            gmail_notify.notify, actor, "a modifié un élément en corbeille", detail)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/corbeille/{item_type}/{item_id}")
async def api_corbeille_purge(item_type: str, item_id: str, background_tasks: BackgroundTasks):
    """Supprime définitivement un élément (irréversible)."""
    try:
        actor = drive.get_current_user_email()
        if item_type == "collaborateur":
            drive.delete_fiche_forever(item_id)
            detail = "Fiche collaborateur supprimée définitivement"
        elif item_type == "client":
            drive.purge_corbeille_item(item_id)
            detail = "Client supprimé définitivement (corbeille)"
        elif item_type == "projet":
            drive.delete_projet_forever(item_id)
            detail = "Projet supprimé définitivement (corbeille)"
        else:
            raise HTTPException(status_code=400, detail="Type inconnu : " + item_type)
        background_tasks.add_task(
            gmail_notify.notify, actor, "a supprimé définitivement un élément", detail)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API — Suivi d'activité (historique des révisions Drive : fiches + référentiels)
# ---------------------------------------------------------------------------

@app.get("/api/activite")
async def api_activite():
    """Historique des éditions Drive (fiches collaborateurs + référentiels), le plus récent en premier."""
    try:
        return drive.list_activity()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Pages & frontend statique
# ---------------------------------------------------------------------------

@app.get("/admin")
async def admin_page():
    """Compat : l'admin est désormais intégré dans la page unique."""
    return RedirectResponse(url="/#admin-collabs")


app.mount("/cv-fonts", StaticFiles(directory=str(renderer.ASSETS)), name="cv-fonts")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
