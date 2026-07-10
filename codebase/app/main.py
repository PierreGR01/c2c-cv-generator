"""
C2C Tenders App — API FastAPI (génération de CV + ingestion fin de projet + édition fiches).
"""
import io
import json
import zipfile
from pathlib import Path
from typing import Annotated, Optional, List
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")  # charge le .env de l'app quel que soit le cwd

import yaml
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import config, drive, gmail_notify, ingest, renderer, scorer

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
    """
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
            data = scorer.projeter_cible(fiche, cible_collab)
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

_FAMILY_LABELS = {
    "cartographie_web":         "Cartographie web",
    "serveurs_carto":           "Serveurs cartographiques",
    "sig_desktop":              "SIG Desktop",
    "catalogues_metadonnees":   "Catalogues & Métadonnées",
    "bases_de_donnees":         "Bases de données",
    "etl_donnees":              "ETL & Données",
    "infrastructure":           "Infrastructure",
    "langages":                 "Langages",
    "frameworks_backend":       "Frameworks Backend",
    "frameworks_frontend":      "Frameworks Frontend",
    "ia_ml":                    "IA & Machine Learning",
    "mobile":                   "Mobile",
    "tests":                    "Tests",
    "outils_dev":               "Outils Dev",
    "cms":                      "CMS",
    "3d_visualisation":         "3D & Visualisation",
    "monitoring_bi":            "Monitoring & BI",
    "reseau_telecom_securite":  "Réseau, Télécom & Sécurité",
    "design_systems":           "Design Systems",
    "design_ui":                "Design UI",
    "design_ux":                "Design UX",
    "gestion_conseil":          "Gestion & Conseil",
    "erp_odoo":                 "ERP & Odoo",
}

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
# API — Ingestion fiche fin de projet (auto-ingestion depuis le formulaire CP)
# ---------------------------------------------------------------------------

@app.post("/api/fiche/parse")
async def api_fiche_parse(fiche_yaml: Annotated[str, Form()]):
    """Analyse la fiche fin de projet et retourne l'aperçu des modifications."""
    try:
        collab_lookup = drive.get_collaborateurs_lookup()
        competences_yaml = drive.get_competences_raw()
        return ingest.parse_fiche_cp(fiche_yaml, collab_lookup, competences_yaml)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fiche/apply")
async def api_fiche_apply(request: Request, background_tasks: BackgroundTasks):
    """Applique l'aperçu validé : écrit les fiches maîtres sur Drive."""
    try:
        preview = await request.json()
        collab_lookup = drive.get_collaborateurs_lookup()
        competences_yaml = drive.get_competences_raw()
        results, _ = ingest.apply_fiche_cp(preview, collab_lookup, competences_yaml)

        actor = drive.get_current_user_email()
        projet = (preview.get("projet") or {})
        projet_nom = projet.get("designation") or projet.get("id") or "projet"
        touched = [r.get("display") or r.get("slug") for r in results if r.get("ok")]
        details = (
            f"Projet : {projet_nom}\n"
            f"Client : {projet.get('client_ref', '')}\n"
            f"Fiches mises à jour : {', '.join(touched) if touched else 'aucune'}"
        )
        background_tasks.add_task(
            gmail_notify.notify, actor,
            "a créé une fiche de fin de projet (ingestion)", details)
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
