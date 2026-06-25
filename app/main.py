"""
CV Generator — API FastAPI
"""
import io
import zipfile
from pathlib import Path
from typing import Annotated, Optional, List

from dotenv import load_dotenv
load_dotenv()

import yaml
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import drive, renderer, scorer

app = FastAPI(title="CV Generator Camptocamp")


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
async def debug_projection(file_id: str, max_projets: int = 4):
    """Debug : affiche la sélection finale envoyée au renderer."""
    try:
        fiche = drive.get_fiche(file_id)
        cible = {"technologies_cles": [], "domaines": [], "max_projets": max_projets}
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
    annee_min: Annotated[int, Form()] = 0,
    secteur: Annotated[str, Form()] = "",
    domaines: Annotated[Optional[List[str]], Form()] = None,
    competences: Annotated[Optional[List[str]], Form()] = None,
):
    """
    Génère un ou plusieurs CVs ciblés par filtres (ou génériques si pas de filtre).

    - collaborateurs   : liste de drive_file_ids
    - max_projets      : nombre max de projets par CV (0 = tous, défaut 4)
    - max_pages        : limite de pages (1, 2, ou 0 = sans limite, défaut 1)
    - inclure_parcours : inclure le parcours professionnel antérieur (défaut True)
    - annee_min        : exclure les projets antérieurs à cette année (0 = sans limite)
    - secteur          : filtrer par secteur ("public", "prive", ou "" = tous)
    - domaines         : liste de domaines à valoriser (ids canoniques)
    - competences      : liste de compétences clés à valoriser
    """
    domaines_list = domaines or []
    competences_list = competences or []

    cible: dict = {
        "technologies_cles": competences_list,
        "domaines": domaines_list,
        "max_projets": max_projets,
        "inclure_parcours": inclure_parcours,
        "annee_min": annee_min,
    }
    if secteur in ("public", "prive"):
        cible["secteur"] = secteur

    # Nom du fichier de sortie
    if domaines_list or competences_list or secteur or annee_min:
        ao_stem = "cible"
        if secteur:
            ao_stem += f"-{secteur}"
        if annee_min:
            ao_stem += f"-depuis{annee_min}"
    else:
        ao_stem = "generique"

    pdfs: dict[str, bytes] = {}

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

        try:
            data = scorer.projeter_cible(fiche, cible)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur scoring ({collab_stem}) : {e}")

        try:
            pdf_bytes, _ = renderer.render_cv_to_bytes(data, max_projets=max_projets, max_pages=max_pages)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur rendu ({collab_stem}) : {e}")

        pdfs[pdf_filename] = pdf_bytes

    if not pdfs:
        raise HTTPException(status_code=500, detail="Aucun PDF généré.")

    if len(pdfs) == 1:
        filename, pdf_bytes = next(iter(pdfs.items()))
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, fbytes in pdfs.items():
            zf.writestr(fname, fbytes)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="cvs-{ao_stem}.zip"'},
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
# Frontend statique
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
