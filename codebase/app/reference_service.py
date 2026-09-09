"""
Assemble les données du registre projets/ en entrées prêtes pour
reference_renderer.build_projets_data() — le pont entre le registre Drive
(fichier plat par projet, images référencées par file_id) et le moteur de
rendu (qui attend des octets déjà téléchargés).
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import drive


def _fetch_image_bytes(im: dict) -> dict | None:
    """Télécharge une image du registre ; None si le fichier a disparu de
    Drive (image supprimée manuellement) — ignorée plutôt que de faire
    échouer tout le rendu."""
    file_id = im.get("fichier_drive_id")
    if not file_id:
        return None
    try:
        content, mimetype = drive.get_projet_image_bytes(file_id)
    except Exception:
        return None
    return {
        "content": content,
        "mimetype": mimetype,
        "legende": im.get("legende", ""),
        "chapitre": im.get("chapitre", ""),
    }


def build_projets_for_render(file_ids: list[str]) -> list[dict]:
    """Hydrate N projets du registre en entrées prêtes pour
    reference_renderer.build_projets_data() :
      - champs communs via drive.get_projet()
      - equipe_display : noms résolus via drive.get_collaborateurs_lookup_for
      - images_bytes   : [{content, mimetype, legende, chapitre}] téléchargées
                         en parallèle (une seule fois pour tous les projets)
    """
    projets = [drive.get_projet(fid) for fid in file_ids]

    slugs = {
        m.get("collaborateur")
        for p in projets
        for m in (p.get("equipe") or [])
        if isinstance(m, dict) and m.get("collaborateur")
    }
    collab_lookup = drive.get_collaborateurs_lookup_for(slugs)

    toutes_images = [
        im for p in projets for im in (p.get("images") or []) if isinstance(im, dict)
    ]
    images_par_id: dict[str, dict] = {}
    if toutes_images:
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_image_bytes, im): im for im in toutes_images}
            for fut in as_completed(futures):
                im = futures[fut]
                result = fut.result()
                if result is not None:
                    images_par_id[im.get("fichier_drive_id")] = result

    result = []
    for projet in projets:
        equipe_display = []
        for m in (projet.get("equipe") or []):
            if not isinstance(m, dict) or not m.get("collaborateur"):
                continue
            collab = collab_lookup.get(m["collaborateur"])
            nom = collab["display"] if collab else m["collaborateur"]
            equipe_display.append({"nom": nom, "role": m.get("role", "")})

        images_bytes = [
            images_par_id[im["fichier_drive_id"]]
            for im in (projet.get("images") or [])
            if isinstance(im, dict) and im.get("fichier_drive_id") in images_par_id
        ]

        result.append({
            **projet,
            "equipe_display": equipe_display,
            "images_bytes": images_bytes,
        })

    return result
