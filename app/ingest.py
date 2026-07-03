"""
Moteur d'ingestion des fiches fin de projet CP (app fusionnée).

Workflow :
  1. parse_fiche_cp()  — analyse la fiche YAML du CP, compare avec les fiches
     collaborateurs et le référentiel de compétences. Retourne un "preview".
  2. apply_fiche_cp()  — applique le preview :
     - Ajoute l'entrée projet dans chaque fiche collaborateur (round-trip ruamel)
     - Ajoute les nouvelles compétences dans les fiches collaborateurs
     - Met à jour competences.yaml si nouvelles entrées référentiel
     ...ET ÉCRIT le résultat sur Drive via app.drive (save_fiche_content /
     save_competences). C'est cette écriture qui rend l'ingestion automatique.
"""
import io
import textwrap
from typing import Any

import yaml
from ruamel.yaml import YAML as RuamelYAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


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
    # YAML interdit les tabs — on les remplace par des espaces au cas où
    return buf.getvalue().replace('\t', '  ')


# ─── Référentiel compétences ─────────────────────────────────────────────────

def flatten_competences(competences_yaml_str: str) -> set[str]:
    """Aplatit competences.yaml en un set de tous les libellés autorisés."""
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

            # Compétences actuelles du collaborateur
            existing_items: set[str] = set()
            for cat_block in (collab["fiche"].get("competences") or []):
                for item in (cat_block.get("items") or []):
                    if isinstance(item, str):
                        existing_items.add(item)

            # Nouvelles compétences (hors référentiel) — SECTION OBLIGATOIRE (aucun fourre-tout).
            # Une compétence sans section est refusée (erreur bloquante), jamais reclassée.
            new_comp_names = []
            for comp_new in competences_nouvelles:
                nom = (comp_new.get("nom") or "").strip()
                if not nom:
                    continue
                section = (comp_new.get("section") or comp_new.get("categorie") or "").strip()
                if not section:
                    errors.append(
                        f"Compétence « {nom} » ({slug}) : une section (famille) est obligatoire."
                    )
                    continue
                new_comp_names.append(nom)
                if nom not in competences_flat:
                    entry["new_competences_for_referentiel"].append({"nom": nom, "section": section})
                if nom not in existing_items:
                    already = any(c["nom"] == nom for c in entry["new_competences_for_collab"])
                    if not already:
                        entry["new_competences_for_collab"].append({"nom": nom, "section": section})

            # Entrée projet : les compétences du projet incluent les compétences du
            # référentiel cochées ET les nouvelles compétences déclarées (mobilisées ici).
            # client/client_ref sont identiques à la création (le CP choisit une entrée
            # unique du référentiel clients dans le formulaire).
            client_ref_val = (projet.get("client_ref") or "").strip()
            new_projet = {
                "id": projet.get("id") or slug + "-projet",
                "designation": projet.get("designation") or "",
                "role": role,
                "client": client_ref_val,
                "client_ref": [client_ref_val] if client_ref_val else [],
                "sous_entite": (projet.get("sous_entite") or "").strip(),
                "periode": projet.get("periode") or "",
                "contexte": (projet.get("contexte") or "").strip(),
                "competences": competences_cp + new_comp_names,
                "realisations": realisations,
                "domaines": domaines,
                "secteur": projet.get("secteur") or "public",
                "poids": poids,
            }
            entry["new_projet_entry"] = new_projet
            entry["new_projet_entry_yaml"] = _render_projet_yaml(new_projet)

            # Diff des compétences du référentiel cochées
            for comp in competences_cp:
                if comp in existing_items:
                    entry["competences_ok"].append(comp)
                elif comp in competences_flat:
                    family = _get_family_for_competence(comp, competences_yaml_str)
                    entry["new_competences_for_collab"].append({
                        "nom": comp,
                        "categorie": family,
                        "domaines": domaines,
                    })
                else:
                    entry["warnings"].append(
                        f"Compétence '{comp}' absente du référentiel — "
                        "présente dans competences_nouvelles ou corriger le libellé."
                    )
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
        f"  client_ref: [{', '.join(projet.get('client_ref') or [])}]",
    ]
    if projet.get("sous_entite"):
        lines.append(f"  sous_entite: {projet['sous_entite']}")
    lines += [
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


# ─── Helpers ruamel ──────────────────────────────────────────────────────────

def _dict_to_commented(obj):
    """Convertit récursivement un dict/list Python en CommentedMap/CommentedSeq
    pour que ruamel produise une indentation correcte dans les listes."""
    if isinstance(obj, dict):
        cm = CommentedMap()
        for k, v in obj.items():
            cm[k] = _dict_to_commented(v)
        return cm
    if isinstance(obj, list):
        cs = CommentedSeq()
        for item in obj:
            cs.append(_dict_to_commented(item))
        return cs
    return obj


# ─── Apply ────────────────────────────────────────────────────────────────────

def apply_fiche_cp(
    preview: dict,
    collab_lookup: dict[str, dict],
    competences_yaml_str: str,
) -> tuple[list[dict], str]:
    """
    Applique les changements du preview et ÉCRIT sur Drive.
    Retourne (results, updated_competences_yaml_str).
    """
    from app import drive as drv

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

        try:
            raw = drv.get_fiche_raw(file_id)
            data = _load_ruamel(raw)

            # 1. Ajouter l'entrée projet
            new_projet = membre.get("new_projet_entry")
            if new_projet:
                if "projets" not in data or data["projets"] is None:
                    data["projets"] = CommentedSeq()
                data["projets"].append(_dict_to_commented(new_projet))

            # 2. Ajouter les nouvelles compétences
            for comp_info in (membre.get("new_competences_for_collab") or []):
                _add_competence_to_fiche(data, comp_info)

            new_yaml_str = _dump_ruamel(data)

            # 3. Sauvegarder sur Drive
            drv.save_fiche_content(file_id, new_yaml_str)

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
            drv.save_competences(new_competences_yaml)
        except Exception as e:
            for r in results:
                if r["ok"]:
                    r["message"] += f" (⚠ competences.yaml non mis à jour : {e})"

    return results, new_competences_yaml


def _add_competence_to_fiche(data: dict, comp_info: dict) -> None:
    """Ajoute une compétence dans la section `competences:` d'une fiche."""
    nom = comp_info.get("nom", "")
    # "section" = clé de famille du référentiel (ex: ia_ml) ou ancien champ "categorie"
    section = comp_info.get("section") or comp_info.get("categorie")

    if not nom:
        return

    competences = data.get("competences") or []
    target_cat = None

    if section:
        for cat_block in competences:
            if cat_block.get("categorie") == section:
                target_cat = cat_block
                break

    if target_cat is not None:
        items = target_cat.get("items") or []
        if nom not in items:
            items.append(nom)
            target_cat["items"] = items
    else:
        new_cat = {
            "categorie": section or "nouvelles_competences",
            "items": [nom],
        }
        if "competences" not in data or data["competences"] is None:
            data["competences"] = []
        data["competences"].append(new_cat)


def _add_to_referentiel(competences_yaml_str: str, new_items: list[dict]) -> str:
    """Ajoute de nouvelles compétences à competences.yaml dans la bonne section."""
    data = _load_ruamel(competences_yaml_str) if competences_yaml_str.strip() else {}
    if data is None:
        data = {}

    for item in new_items:
        nom = item.get("nom", "").strip()
        # "section" est la clé de famille exacte (ex: ia_ml, design_ui)
        famille = (item.get("section") or item.get("categorie") or "ajouts_cp").strip()
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
