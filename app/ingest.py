"""
Moteur d'ingestion des fiches fin de projet CP.

Workflow :
  1. parse_fiche_cp()  — analyse la fiche YAML du CP, compare avec les
     fiches collaborateurs et le référentiel de compétences.
     Retourne un dict "preview" lisible par le frontend.

  2. apply_fiche_cp()  — applique le preview validé par Pierre :
     - Ajoute l'entrée projet dans chaque fiche collaborateur
     - Ajoute les nouvelles compétences dans les fiches collaborateurs
     - Met à jour competences.yaml si de nouvelles entrées référentiel
       sont présentes
"""
import io
import textwrap
from typing import Any

import yaml
from ruamel.yaml import YAML as RuamelYAML


# ─── YAML round-trip helper ───────────────────────────────────────────────────

def _make_ryaml() -> RuamelYAML:
    ry = RuamelYAML()
    ry.preserve_quotes = True
    ry.width = 120
    ry.best_sequence_indent = 2
    ry.best_map_flow_style = False
    return ry


def _load_ruamel(yaml_str: str):
    ry = _make_ryaml()
    return ry.load(io.StringIO(yaml_str))


def _dump_ruamel(data) -> str:
    ry = _make_ryaml()
    buf = io.StringIO()
    ry.dump(data, buf)
    return buf.getvalue()


# ─── Référentiel compétences ─────────────────────────────────────────────────

def flatten_competences(competences_yaml_str: str) -> set[str]:
    """
    Aplatit competences.yaml en un set de tous les libellés autorisés.
    """
    if not competences_yaml_str.strip():
        return set()
    data = yaml.safe_load(competences_yaml_str) or {}
    flat = set()
    for family_items in data.values():
        if isinstance(family_items, list):
            for item in family_items:
                if isinstance(item, str):
                    flat.add(item)
    return flat


def _get_family_for_competence(comp_name: str, competences_yaml_str: str) -> str | None:
    """Retourne le nom de la famille (clé YAML) contenant cette compétence."""
    if not competences_yaml_str.strip():
        return None
    data = yaml.safe_load(competences_yaml_str) or {}
    for family, items in data.items():
        if isinstance(items, list) and comp_name in items:
            return family
    return None


# ─── Parse ────────────────────────────────────────────────────────────────────

def parse_fiche_cp(
    fiche_yaml_str: str,
    collab_lookup: dict[str, dict],
    competences_yaml_str: str,
) -> dict:
    """
    Analyse la fiche CP et construit un dict preview.

    collab_lookup : {slug: {"file_id": ..., "fiche": dict, "display": str, "filename": str}}
    competences_yaml_str : contenu brut de competences.yaml

    Retourne:
    {
      "projet": {...},
      "membres": [
        {
          "slug": str,
          "file_id": str | None,
          "display": str,
          "found": bool,
          "role": str,
          "new_projet_entry": dict,
          "new_projet_entry_yaml": str,  # rendu YAML pour affichage frontend
          "competences_ok": [str],       # déjà dans la fiche collab
          "new_competences_for_collab": [{"nom": str, "categorie": str|None, "domaines": list}],
          "new_competences_for_referentiel": [{"nom": str, "categorie": str, "domaines": list}],
          "warnings": [str],
        }
      ],
      "errors": [str],
    }
    """
    errors = []
    try:
        fiche = yaml.safe_load(fiche_yaml_str)
    except yaml.YAMLError as e:
        return {"projet": {}, "membres": [], "errors": [f"YAML invalide : {e}"]}

    if not isinstance(fiche, dict):
        return {"projet": {}, "membres": [], "errors": ["Format invalide : la fiche doit être un mapping YAML"]}

    projet = fiche.get("projet", {})
    if not isinstance(projet, dict):
        projet = {}

    competences_flat = flatten_competences(competences_yaml_str)

    membres_out = []
    for membre in (fiche.get("membres") or []):
        if not isinstance(membre, dict):
            continue

        slug = (membre.get("collaborateur") or "").strip()
        role = (membre.get("role") or "").strip()
        domaines = membre.get("domaines") or []
        poids = membre.get("poids", 3)
        realisations = membre.get("realisations") or []
        competences_cp = [c for c in (membre.get("competences") or []) if isinstance(c, str)]
        competences_nouvelles = [c for c in (membre.get("competences_nouvelles") or []) if isinstance(c, dict)]

        entry: dict[str, Any] = {
            "slug": slug,
            "file_id": None,
            "display": slug,
            "found": False,
            "role": role,
            "new_projet_entry": None,
            "new_projet_entry_yaml": "",
            "competences_ok": [],
            "new_competences_for_collab": [],
            "new_competences_for_referentiel": [],
            "warnings": [],
        }

        collab = collab_lookup.get(slug)
        if collab:
            entry["file_id"] = collab["file_id"]
            entry["display"] = collab["display"]
            entry["found"] = True

            # Compétences actuelles du collaborateur (set de libellés)
            existing_items: set[str] = set()
            for cat_block in (collab["fiche"].get("competences") or []):
                for item in (cat_block.get("items") or []):
                    if isinstance(item, str):
                        existing_items.add(item)

            # Construire l'entrée projet
            new_projet = {
                "id": projet.get("id") or slug + "-projet",
                "role": role,
                "client": projet.get("client") or "",
                "periode": projet.get("periode") or "",
                "contexte": (projet.get("contexte") or "").strip(),
                "competences": competences_cp,
                "realisations": realisations,
                "domaines": domaines,
                "secteur": projet.get("secteur") or "public",
                "poids": poids,
            }
            entry["new_projet_entry"] = new_projet
            entry["new_projet_entry_yaml"] = _render_projet_yaml(new_projet)

            # Diff compétences
            for comp in competences_cp:
                if comp in existing_items:
                    entry["competences_ok"].append(comp)
                elif comp in competences_flat:
                    # Connue du référentiel mais pas dans la fiche collab
                    family = _get_family_for_competence(comp, competences_yaml_str)
                    entry["new_competences_for_collab"].append({
                        "nom": comp,
                        "categorie": family,
                        "domaines": domaines,
                    })
                else:
                    entry["warnings"].append(
                        f"Compétence '{comp}' absente du référentiel — "
                        "ajoute-la dans competences_nouvelles ou corrige le libellé."
                    )

            # Nouvelles compétences à ajouter au référentiel
            for comp_new in competences_nouvelles:
                nom = (comp_new.get("nom") or "").strip()
                if not nom:
                    continue
                categorie = (comp_new.get("categorie") or "").strip()
                comp_domaines = comp_new.get("domaines") or domaines

                if nom not in competences_flat:
                    entry["new_competences_for_referentiel"].append({
                        "nom": nom,
                        "categorie": categorie,
                        "domaines": comp_domaines,
                    })
                # Aussi ajouter à la fiche collab si absent
                if nom not in existing_items:
                    # Eviter doublon avec new_competences_for_collab
                    already = any(c["nom"] == nom for c in entry["new_competences_for_collab"])
                    if not already:
                        entry["new_competences_for_collab"].append({
                            "nom": nom,
                            "categorie": categorie,
                            "domaines": comp_domaines,
                        })
        else:
            if slug:
                entry["warnings"].append(
                    f"Collaborateur '{slug}' introuvable dans Drive. "
                    "Vérifier le slug (minuscules, tirets)."
                )
            else:
                entry["warnings"].append("Champ 'collaborateur' vide ou absent.")

        membres_out.append(entry)

    return {
        "projet": projet,
        "membres": membres_out,
        "errors": errors,
    }


def _render_projet_yaml(projet: dict) -> str:
    """Sérialise l'entrée projet en YAML lisible pour le frontend."""
    lines = [
        f"- id: {projet['id']}",
        f"  role: {projet['role']}",
        f"  client: {projet['client']}",
        f"  periode: {projet['periode']}",
        f"  contexte: >",
    ]
    contexte = projet.get("contexte", "")
    for line in textwrap.wrap(contexte, width=70):
        lines.append(f"    {line}")
    lines.append("  competences:")
    for c in (projet.get("competences") or []):
        lines.append(f"    - {c}")
    lines.append("  realisations:")
    for r in (projet.get("realisations") or []):
        lines.append(f"  - {r!r}")
    domaines = projet.get("domaines") or []
    lines.append(f"  domaines: [{', '.join(domaines)}]")
    lines.append(f"  secteur: {projet.get('secteur', 'public')}")
    lines.append(f"  poids: {projet.get('poids', 3)}")
    return "\n".join(lines)


# ─── Apply ────────────────────────────────────────────────────────────────────

def apply_fiche_cp(
    preview: dict,
    collab_lookup: dict[str, dict],
    competences_yaml_str: str,
) -> tuple[list[dict], str]:
    """
    Applique les changements du preview :
    - Pour chaque membre trouvé : ajoute le projet + nouvelles compétences dans leur YAML
    - Met à jour competences.yaml si nouvelles entrées référentiel

    Retourne (results, updated_competences_yaml_str) :
      results = [{"slug": ..., "display": ..., "ok": bool, "message": ..., "file_id": ..., "new_yaml": str}]
      updated_competences_yaml_str = nouveau contenu de competences.yaml (ou "" si inchangé)
    """
    results = []
    new_competences_yaml = competences_yaml_str

    for membre in (preview.get("membres") or []):
        if not membre.get("found"):
            results.append({
                "slug": membre["slug"],
                "display": membre.get("display", membre["slug"]),
                "file_id": None,
                "ok": False,
                "message": "Collaborateur non trouvé — ignoré",
                "new_yaml": "",
            })
            continue

        slug = membre["slug"]
        file_id = membre["file_id"]
        collab = collab_lookup.get(slug)
        if not collab:
            results.append({
                "slug": slug,
                "display": membre.get("display", slug),
                "file_id": file_id,
                "ok": False,
                "message": "Données collaborateur introuvables",
                "new_yaml": "",
            })
            continue

        try:
            # Charger la fiche raw pour round-trip
            from app import drive as drv
            raw = drv.get_fiche_raw(file_id)
            data = _load_ruamel(raw)

            # 1. Ajouter l'entrée projet
            new_projet = membre.get("new_projet_entry")
            if new_projet:
                if "projets" not in data or data["projets"] is None:
                    data["projets"] = []
                data["projets"].append(new_projet)

            # 2. Ajouter les nouvelles compétences
            for comp_info in (membre.get("new_competences_for_collab") or []):
                _add_competence_to_fiche(data, comp_info)

            # Sérialiser
            new_yaml_str = _dump_ruamel(data)

            results.append({
                "slug": slug,
                "display": membre.get("display", slug),
                "file_id": file_id,
                "ok": True,
                "message": _build_success_msg(membre),
                "new_yaml": new_yaml_str,
            })

        except Exception as e:
            results.append({
                "slug": slug,
                "display": membre.get("display", slug),
                "file_id": file_id,
                "ok": False,
                "message": f"Erreur : {e}",
                "new_yaml": "",
            })

    # Mettre à jour competences.yaml si nouvelles entrées
    all_new_ref = []
    for membre in (preview.get("membres") or []):
        all_new_ref.extend(membre.get("new_competences_for_referentiel") or [])

    if all_new_ref:
        try:
            new_competences_yaml = _add_to_referentiel(competences_yaml_str, all_new_ref)
        except Exception as e:
            # Non bloquant — on signale mais on continue
            for r in results:
                if r["ok"]:
                    r["message"] += f" (⚠ competences.yaml non mis à jour : {e})"

    return results, new_competences_yaml


def _add_competence_to_fiche(data: dict, comp_info: dict) -> None:
    """
    Ajoute une compétence dans la section `competences:` d'une fiche.
    Cherche la catégorie correspondante ou crée une nouvelle entrée.
    """
    nom = comp_info.get("nom", "")
    categorie = comp_info.get("categorie")
    domaines = comp_info.get("domaines") or []

    if not nom:
        return

    competences = data.get("competences") or []

    # Chercher une catégorie correspondante
    target_cat = None
    if categorie:
        for cat_block in competences:
            if cat_block.get("categorie") == categorie:
                target_cat = cat_block
                break

    # Chercher par domaines si pas trouvé par nom de catégorie
    if target_cat is None and domaines:
        for cat_block in competences:
            cat_domaines = cat_block.get("domaines") or []
            if any(d in domaines for d in cat_domaines):
                target_cat = cat_block
                break

    if target_cat is not None:
        # Vérifier que la compétence n'y est pas déjà
        items = target_cat.get("items") or []
        if nom not in items:
            items.append(nom)
            target_cat["items"] = items
    else:
        # Créer une nouvelle catégorie
        new_cat = {
            "categorie": categorie or "Compétences projet",
            "domaines": domaines,
            "items": [nom],
        }
        if "competences" not in data or data["competences"] is None:
            data["competences"] = []
        data["competences"].append(new_cat)


def _add_to_referentiel(competences_yaml_str: str, new_items: list[dict]) -> str:
    """
    Ajoute de nouvelles compétences à competences.yaml.
    Regroupe par categorie (= nom de famille YAML).
    """
    data = _load_ruamel(competences_yaml_str) if competences_yaml_str.strip() else {}
    if data is None:
        data = {}

    for item in new_items:
        nom = item.get("nom", "").strip()
        famille = (item.get("categorie") or "ajouts_cp").strip().lower().replace(" ", "_")
        if not nom:
            continue
        if famille not in data:
            data[famille] = []
        if nom not in data[famille]:
            data[famille].append(nom)

    return _dump_ruamel(data)


def _build_success_msg(membre: dict) -> str:
    nb_comp = len(membre.get("new_competences_for_collab") or [])
    parts = ["Projet ajouté"]
    if nb_comp:
        parts.append(f"{nb_comp} compétence(s) ajoutée(s)")
    return " · ".join(parts)
