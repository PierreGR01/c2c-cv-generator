"""
CV Generator — API FastAPI
"""
import io
import zipfile
from typing import Annotated, Optional

from dotenv import load_dotenv
load_dotenv()

import yaml
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import drive, renderer, scorer

app = FastAPI(title="CV Generator Camptocamp")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/collaborateurs")
async def list_collaborateurs():
    """Liste les collaborateurs disponibles sur Drive."""
    try:
        return drive.list_collaborateurs()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/generate")
async def generate_cvs(
    collaborateurs: Annotated[list[str], Form()],
    max_projets: Annotated[int, Form()] = 4,
    max_pages: Annotated[int, Form()] = 1,
    inclure_parcours: Annotated[bool, Form()] = True,
    ao_yaml: Optional[UploadFile] = None,
):
    """
    Génère un ou plusieurs CVs ciblés sur un AO (ou génériques si pas d'AO).

    - ao_yaml          : fichier YAML de l'appel d'offre (optionnel)
    - collaborateurs   : liste de drive_file_ids
    - max_projets      : nombre max de projets par CV (0 = tous, défaut 4)
    - max_pages        : limite de pages (1, 2, ou 0 = sans limite, défaut 1)
    - inclure_parcours : inclure le parcours professionnel antérieur (défaut True)
    """
    # Parse AO — ou cible générique si pas de fichier
    if ao_yaml is not None and ao_yaml.filename:
        try:
            ao_content = await ao_yaml.read()
            cible = yaml.safe_load(ao_content.decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"AO YAML invalide : {e}")
        ao_stem = ao_yaml.filename.replace(".yaml", "").replace(".yml", "")
    else:
        cible = {"technologies_cles": [], "domaines": []}
        ao_stem = "generique"

    cible["max_projets"] = max_projets
    cible["inclure_parcours"] = inclure_parcours

    pdfs: dict[str, bytes] = {}

    for file_id in collaborateurs:
        # Charger la fiche depuis Drive
        try:
            fiche = drive.get_fiche(file_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Fiche introuvable ({file_id}) : {e}")

        id_section = fiche.get("identite", {})
        prenom = id_section.get("prenom", "inconnu").lower()
        nom = id_section.get("nom", "").lower()
        collab_stem = f"{prenom}-{nom}".replace(" ", "-")
        pdf_filename = f"cv-{collab_stem}--{ao_stem}.pdf"

        # Projection AO
        try:
            data = scorer.projeter_cible(fiche, cible)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur scoring ({collab_stem}) : {e}")

        # Rendu PDF
        try:
            pdf_bytes, _ = renderer.render_cv_to_bytes(data, max_projets=max_projets, max_pages=max_pages)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur rendu ({collab_stem}) : {e}")

        pdfs[pdf_filename] = pdf_bytes

    if not pdfs:
        raise HTTPException(status_code=500, detail="Aucun PDF généré.")

    # PDF direct si un seul collaborateur, ZIP si plusieurs
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
# Frontend statique
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
