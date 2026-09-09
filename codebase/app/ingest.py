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
import re
import textwrap
from typing import Any

import yaml
from ruamel.yaml import YAML as RuamelYAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

# Importé pour les seules règles de normalisation des liens (lien de
# publication, adresses de contact) : elles décrivent ce qui fait un lien
# cliquable dans le PDF, et ce module en est la source unique.
from app import reference_renderer


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


CHAPITRE_KEYS = ("contexte_complet", "technique", "visuel", "ergonomie", "environnement", "resultats")

# Unités proposées à la saisie du budget — même liste que côté formulaire et
# côté rendu (cf. reference_renderer.BUDGET_UNITES) : le montant est stocké nu,
# l'unité à part, et ce n'est qu'au rendu que les deux se recomposent.
BUDGET_UNITES = ("€", "K€", "M€")


def _as_budget_montant(value):
    """Montant du budget tel qu'il doit vivre dans le registre : un NOMBRE, ou
    "" s'il n'est pas renseigné. Jamais une chaîne formatée — la mise en forme
    (séparateurs de milliers, liaison à l'unité) appartient au rendu.

    Tolère l'espacement et la virgule décimale d'un montant recopié à la main,
    et retombe sur "" plutôt que de propager une valeur illisible : un budget
    absent est un cas normal, une cellule de faits en moins.
    """
    if value is None:
        return ""
    brut = str(value).strip().replace(",", ".")
    for espace in (" ", "\u00a0", "\u202f", "\u2009"):
        brut = brut.replace(espace, "")
    if not brut:
        return ""
    try:
        nombre = float(brut)
    except ValueError:
        return ""
    if nombre <= 0:
        return ""
    return int(nombre) if nombre == int(nombre) else nombre


def _as_budget_unite(value) -> str:
    unite = _as_text(value).strip()
    return unite if unite in BUDGET_UNITES else BUDGET_UNITES[0]


# Un seul lien de publication par projet (« le lien direct est unique, il n'y a
# pas possibilité de renseigner plus d'un lien »), au plus MAX_CONTACTS points
# de contact — le plafond, la validation d'une adresse et la complétion du
# schéma d'une URL vivent dans app/reference_renderer (ce sont les règles de ce
# qui fait un lien exploitable dans le PDF) ; on les applique ICI pour que le
# registre ne stocke jamais autre chose que du normalisé.
MAX_CONTACTS = reference_renderer.MAX_CONTACTS


def _as_lien_projet(value) -> str:
    return reference_renderer.normaliser_lien(_as_text(value))


def _as_contacts(value) -> list[dict]:
    return reference_renderer.normaliser_contacts(value)


def _as_text(value) -> str:
    """Force un scalaire YAML en chaîne pour le formulaire d'édition.

    YAML relit `periode: 2024` en entier, `secteur: on` en booléen,
    `periode: 2024-01` en date : le front, lui, fait des `.split()`/`.trim()`
    dessus. Un seul champ typé autrement suffisait à faire planter tout le
    pré-remplissage — et donc à ouvrir un formulaire vide sur un projet plein.
    Les fichiers déjà écrits avec un type numérique sont ainsi réparés à la
    lecture, et réécrits en chaîne au prochain enregistrement.
    """
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value)


# ─── Parse ────────────────────────────────────────────────────────────────────

def parse_fiche_cp(
    fiche_yaml_str: str,
    collab_lookup: dict[str, dict],
    competences_yaml_str: str,
    projet_file_id: str = "",
) -> dict:
    """
    Analyse la fiche CP et construit un dict preview.

    collab_lookup : {slug: {"file_id": ..., "fiche": dict, "display": str, "filename": str}}
    competences_yaml_str : contenu brut de competences.yaml
    projet_file_id : file_id Drive du projet en cours d'édition (Administration >
      Projets). Fourni, il court-circuite la recherche par nom : c'est CE fichier
      qui est relu puis réécrit, même si un homonyme traîne dans projets/.
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

    # ── Registre projet transversal ────────────────────────────────────────
    # projet.id (composé côté formulaire à partir désignation+client+année, cf.
    # static/index.html buildFicheYAML) sert de clé de jonction vers
    # projets/<id>.yaml. On charge l'existant s'il y en a un, pour préparer la
    # fusion + détecter si une synchro vers l'équipe déjà liée sera nécessaire.
    # _as_text partout où un .strip() suivait : un scalaire relu en nombre
    # (periode: 2024) ou en booléen faisait planter l'analyse en AttributeError,
    # donc un 500 sur /api/fiche/parse au lieu d'un aperçu.
    projet_id = _as_text(projet.get("id")).strip()
    client_ref_val = _as_text(projet.get("client_ref")).strip()

    existing_projet: dict | None = None
    existing_file_id: str = ""
    if projet_id:
        from app import drive as drv
        try:
            existing_file_id = projet_file_id or (drv.find_projet_file_id(projet_id) or "")
            if existing_file_id:
                existing_projet = drv.get_projet(existing_file_id)
        except Exception as e:
            existing_projet = None
            if projet_file_id:
                # Édition d'un projet identifié : sans son contenu actuel, la
                # fusion ci-dessous repartirait de zéro et l'enregistrement
                # écraserait équipe, chapitres et images déjà en place. On
                # bloque plutôt que de sauvegarder une version amputée.
                errors.append(
                    f"Projet « {projet_id} » illisible sur le Drive ({e}) — "
                    "enregistrement annulé pour ne rien écraser."
                )

    registre_domaines: set[str] = set((existing_projet or {}).get("domaines") or [])
    registre_competences: set[str] = set((existing_projet or {}).get("competences") or [])
    equipe_by_slug: dict[str, dict] = {}
    for m in ((existing_projet or {}).get("equipe") or []):
        if isinstance(m, dict) and m.get("collaborateur"):
            equipe_by_slug[m["collaborateur"]] = {
                "collaborateur": m["collaborateur"], "role": m.get("role", "")
            }

    # Retraits explicites (écran Administration > Projets, jamais déduit —
    # cf. static/index.html toggleFicheCollab, confirmation obligatoire avant
    # d'ajouter un slug ici). Ne modifie pas l'agrégat domaines/competences
    # (limite acceptée : il peut rester légèrement sur-large après un retrait).
    membres_retires = [str(s).strip() for s in (fiche.get("membres_retires") or []) if str(s).strip()]
    for slug in membres_retires:
        equipe_by_slug.pop(slug, None)

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
            # client_custom reste vide à la création (le CP ne choisit que le client_ref,
            # dans le formulaire) : l'affichage retombe par défaut sur client_ref/sous_entite,
            # client_custom n'étant qu'une surcharge éditoriale ajoutée plus tard en admin.
            new_projet = {
                "id": _as_text(projet.get("id")) or slug + "-projet",
                "designation": _as_text(projet.get("designation")),
                "role": role,
                "client_custom": "",
                "client_ref": [client_ref_val] if client_ref_val else [],
                "sous_entite": _as_text(projet.get("sous_entite")).strip(),
                # En chaîne aussi dans les fiches collaborateurs : une période
                # numérique s'y propageait et allait casser l'éditeur de fiche
                # et le scoring, pas seulement l'édition de projet.
                "periode": _as_text(projet.get("periode")),
                "contexte": _as_text(projet.get("contexte")).strip(),
                "competences": competences_cp + new_comp_names,
                "realisations": realisations,
                "domaines": domaines,
                "secteur": projet.get("secteur") or "public",
                "poids": poids,
            }
            entry["new_projet_entry"] = new_projet
            entry["new_projet_entry_yaml"] = _render_projet_yaml(new_projet)

            # Alimente le registre projet transversal (union domaines/compétences,
            # équipe) — indépendamment du fait que ce membre soit déjà lié ou non.
            if projet_id:
                registre_domaines.update(domaines)
                registre_competences.update(competences_cp)
                registre_competences.update(new_comp_names)
                equipe_by_slug[slug] = {"collaborateur": slug, "role": role}

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

    # Chapitres/images ne transitent jamais par le formulaire de déclaration
    # CP (qui ne les affiche pas) — sans ce report, une simple déclaration de
    # nouveau membre effacerait le travail éditorial fait depuis
    # Administration > Projets. Les images sont gérées exclusivement par leurs
    # propres endpoints (upload/suppression), jamais par ce flux : toujours
    # reportées telles quelles depuis l'existant.
    existing_chapitres = (existing_projet or {}).get("chapitres") or {}
    submitted_chapitres = projet.get("chapitres")
    if isinstance(submitted_chapitres, dict):
        chapitres = {k: _as_text(submitted_chapitres.get(k)).strip() for k in CHAPITRE_KEYS}
    else:
        chapitres = {k: _as_text(existing_chapitres.get(k)) for k in CHAPITRE_KEYS}
    images = (existing_projet or {}).get("images") or []

    # Contacts et lien de publication : même règle de report que les chapitres.
    # Une clé ABSENTE du YAML soumis reprend l'existant (un flux qui ne les
    # affiche pas ne doit pas les effacer) ; une clé PRÉSENTE fait foi, même
    # vide — c'est ainsi qu'on retire un contact ou un lien depuis le
    # formulaire, qui les envoie toujours.
    if "lien_projet" in projet:
        lien_projet = _as_lien_projet(projet.get("lien_projet"))
    else:
        lien_projet = _as_lien_projet((existing_projet or {}).get("lien_projet"))
    if "contacts" in projet:
        contacts = _as_contacts(projet.get("contacts"))
    else:
        contacts = _as_contacts((existing_projet or {}).get("contacts"))

    registry = None
    if projet_id:
        registry = {
            "id": projet_id,
            # Fichier Drive effectivement relu ci-dessus : _upsert_projet écrira
            # dedans sans refaire de recherche par nom (cf. find_projet_file_id).
            "file_id": existing_file_id,
            "designation": _as_text(projet.get("designation")),
            "client_ref": ([client_ref_val] if client_ref_val
                           else [_as_text(c) for c in ((existing_projet or {}).get("client_ref") or [])]),
            "sous_entite": _as_text(projet.get("sous_entite")).strip(),
            "budget_montant": _as_budget_montant(projet.get("budget_montant")),
            "budget_unite": _as_budget_unite(projet.get("budget_unite")),
            # Toujours écrit en chaîne : c'est ici que se répare un registre où
            # la période avait été stockée en nombre (cf. _as_text).
            "periode": _as_text(projet.get("periode")),
            "lien_projet": lien_projet,
            "contacts": contacts,
            "secteur": _as_text(projet.get("secteur")) or "public",
            "contexte": _as_text(projet.get("contexte")).strip(),
            "domaines": sorted(registre_domaines),
            "competences": sorted(registre_competences),
            "equipe": list(equipe_by_slug.values()),
            "chapitres": chapitres,
            "images": images,
            "existe_deja": existing_projet is not None,
            "removed_membres": membres_retires,
        }
        if existing_projet is not None:
            shared_keys = ("designation", "client_ref", "sous_entite", "periode", "secteur", "contexte")
            registry["needs_sync"] = any(
                registry[k] != ((existing_projet.get(k) or []) if k == "client_ref" else (existing_projet.get(k) or ""))
                for k in shared_keys
            )
        else:
            registry["needs_sync"] = False

    return {
        "projet": projet,
        "membres": membres_out,
        "errors": errors,
        "registry": registry,
    }


def _render_projet_yaml(projet: dict) -> str:
    """Sérialise l'entrée projet en YAML lisible pour le frontend."""
    lines = [
        f"- id: {projet['id']}",
        f"  designation: {projet.get('designation', '')}",
        f"  role: {projet['role']}",
        f"  client_custom: {projet.get('client_custom', '')}",
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


# ─── Détail projet (édition) ─────────────────────────────────────────────────

def hydrate_projet_detail(projet: dict, collab_lookup: dict[str, dict]) -> dict:
    """Enrichit un projet du registre avec les champs individuels de chaque
    membre de l'équipe (role, poids, domaines, competences, realisations),
    lus dans sa propre fiche (entrée `projets[]` dont `id == projet['id']`).
    Fonction pure (pas d'accès Drive), consommée par l'écran Administration >
    Projets pour pré-remplir le formulaire d'édition avec les mêmes panneaux
    membre que la déclaration."""
    projet_id = _as_text(projet.get("id"))
    membres = []
    for m in (projet.get("equipe") or []):
        if not isinstance(m, dict) or not m.get("collaborateur"):
            continue
        slug = m["collaborateur"]
        collab = collab_lookup.get(slug)
        entry = {
            "collaborateur": slug,
            "display": collab["display"] if collab else slug,
            "found": False,
            "role": _as_text(m.get("role")),
            "poids": 2,
            "domaines": [],
            "competences": [],
            "realisations": [],
        }
        if collab:
            for p in (collab["fiche"].get("projets") or []):
                if isinstance(p, dict) and p.get("id") == projet_id:
                    entry["found"] = True
                    entry["role"] = _as_text(p.get("role")) or entry["role"]
                    entry["poids"] = p.get("poids", 2)
                    entry["domaines"] = p.get("domaines") or []
                    entry["competences"] = p.get("competences") or []
                    entry["realisations"] = p.get("realisations") or []
                    break
        membres.append(entry)

    return {
        "id": projet_id,
        "designation": _as_text(projet.get("designation")),
        "client_ref": [_as_text(c) for c in (projet.get("client_ref") or [])],
        "sous_entite": _as_text(projet.get("sous_entite")),
        "budget_montant": _as_budget_montant(projet.get("budget_montant")),
        "budget_unite": _as_budget_unite(projet.get("budget_unite")),
        "periode": _as_text(projet.get("periode")),
        "secteur": _as_text(projet.get("secteur")) or "public",
        "contexte": _as_text(projet.get("contexte")),
        # Normalisés à la LECTURE aussi : un registre écrit à la main (lien sans
        # schéma, contact sans email) revient au formulaire dans la forme que
        # celui-ci sait pré-remplir, et sera réécrit propre au prochain
        # enregistrement — même logique que _as_text pour la période.
        "lien_projet": _as_lien_projet(projet.get("lien_projet")),
        "contacts": _as_contacts(projet.get("contacts")),
        "chapitres": {k: _as_text((projet.get("chapitres") or {}).get(k)) for k in CHAPITRE_KEYS},
        "images": projet.get("images") or [],
        "membres": membres,
    }


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
    *,
    ecrire_cv: bool = True,
) -> tuple[list[dict], str]:
    """
    Applique les changements du preview et ÉCRIT sur Drive.

    ecrire_cv=False : le registre projet (+ sync des champs partagés + retraits
    + référentiel compétences) est toujours écrit, mais aucune entrée projet
    n'est ajoutée/mise à jour dans les fiches collaborateurs (cf.
    PLAN-dissocier-validation.md §3, tableau de portée).

    Retourne (results, updated_competences_yaml_str).
    """
    from app import drive as drv

    results = []
    new_competences_yaml = competences_yaml_str

    registry_result = _upsert_projet(preview.get("registry"), collab_lookup, drv)
    if registry_result is not None:
        if registry_result["ok"]:
            was_existing = bool((preview.get("registry") or {}).get("existe_deja"))
            msg = ("Registre projet mis à jour (équipe synchronisée)" if was_existing
                   else "Registre projet créé")
        else:
            msg = registry_result["message"]
        results.append({
            "slug": "_registre_",
            "display": f"Projet « {registry_result['id']} »",
            "file_id": registry_result.get("file_id"),
            "ok": registry_result["ok"],
            "message": msg,
            "new_yaml": "",
        })

    removed = (preview.get("registry") or {}).get("removed_membres") or []
    if removed:
        projet_id_for_removal = (preview.get("registry") or {}).get("id")
        results.extend(_apply_removed_membres(projet_id_for_removal, removed, collab_lookup, drv))

    if ecrire_cv:
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

                # 1. Ajouter l'entrée projet — ou la mettre à jour en place si ce
                # membre était déjà lié (même id) : évite un doublon si l'on
                # resoumet un projet existant pour éditer un membre déjà présent.
                new_projet = membre.get("new_projet_entry")
                if new_projet:
                    if "projets" not in data or data["projets"] is None:
                        data["projets"] = CommentedSeq()
                    existing_entry = next(
                        (p for p in data["projets"] if p.get("id") == new_projet.get("id")), None)
                    if existing_entry is not None:
                        for k, v in new_projet.items():
                            existing_entry[k] = v
                    else:
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
    else:
        results.append({
            "slug": "_cv_ignore_",
            "display": "Fiches collaborateurs (CV)",
            "file_id": None,
            "ok": True,
            "message": "Non modifiées — enregistrement du projet seul",
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


def _upsert_projet(registry: dict | None, collab_lookup: dict[str, dict], drv) -> dict | None:
    """Crée ou met à jour projets/<id>.yaml (registre transversal), puis — si le
    projet existait déjà et qu'un champ partagé a changé — propage ces champs
    vers les fiches des membres déjà liés (jamais d'ajout/retrait d'équipe ici,
    ça reste porté par la boucle par membre de apply_fiche_cp)."""
    if not registry or not registry.get("id"):
        return None

    projet_id = registry["id"]
    # `budget_montant` / `budget_unite`, `lien_projet` et `contacts` figurent ici
    # (le registre projet les porte, la fiche portefolio les rend) mais PAS dans
    # _sync_projet_to_equipe : les fiches collaborateurs n'ont ni champ budget ni
    # champ contact, et un CV ne les affiche nulle part — les y propager
    # n'ajouterait que des clés inconnues à leur schéma.
    shared = {k: registry[k] for k in (
        "id", "designation", "client_ref", "sous_entite",
        "budget_montant", "budget_unite", "periode",
        "secteur", "contexte", "lien_projet", "contacts",
        "domaines", "competences", "equipe",
        "chapitres", "images",
    )}

    try:
        # Le file_id relu à l'analyse (projet en cours d'édition) prime sur toute
        # recherche par nom : Drive accepte deux fichiers « <id>.yaml » dans le
        # même dossier, donc re-chercher ici pourrait viser un homonyme — ou
        # n'en trouver aucun (index de recherche en retard) et créer un doublon
        # de plus, l'édition suivante repartant alors sur l'un ou l'autre.
        file_id = registry.get("file_id") or drv.find_projet_file_id(projet_id)
        yaml_str = _dump_ruamel(_dict_to_commented(shared))
        if file_id:
            drv.save_projet_content(file_id, yaml_str)
        else:
            file_id = drv.create_projet(projet_id, yaml_str)
    except Exception as e:
        return {"id": projet_id, "ok": False, "message": f"Registre projet non sauvegardé : {e}"}

    if registry.get("needs_sync"):
        _sync_projet_to_equipe(projet_id, shared, registry.get("equipe") or [], collab_lookup, drv)

    # file_id renvoyé au front : indispensable pour uploader une image juste
    # après la création d'un nouveau projet (aucun id de fichier Drive
    # n'existe avant ce tout premier enregistrement — cf. file d'attente
    # d'images côté formulaire de déclaration).
    return {"id": projet_id, "ok": True, "file_id": file_id}


def _sync_projet_to_equipe(projet_id, shared, equipe, collab_lookup, drv) -> None:
    """Propage les champs partagés du registre vers chaque fiche déjà liée
    (entrée `projets[]` dont `id == projet_id`). Best-effort : un membre
    introuvable, ou sans entrée correspondante, est ignoré silencieusement —
    la boucle principale de apply_fiche_cp gère déjà l'ajout des nouveaux membres."""
    shared_fields = ("designation", "client_ref", "sous_entite", "periode", "secteur", "contexte")
    for membre in equipe:
        slug = membre.get("collaborateur") if isinstance(membre, dict) else None
        if not slug:
            continue
        collab = collab_lookup.get(slug)
        if not collab:
            continue
        try:
            raw = drv.get_fiche_raw(collab["file_id"])
            data = _load_ruamel(raw)
            matched = False
            for p_entry in (data.get("projets") or []):
                if p_entry.get("id") == projet_id:
                    for k in shared_fields:
                        p_entry[k] = shared[k]
                    matched = True
                    break
            if not matched:
                continue
            drv.save_fiche_content(collab["file_id"], _dump_ruamel(data))
        except Exception:
            continue


def _apply_removed_membres(projet_id, removed_slugs, collab_lookup: dict[str, dict], drv) -> list[dict]:
    """Retire l'entrée `projets[]` (id == projet_id) de la fiche de chaque
    collaborateur listé dans removed_slugs — jamais déduit d'une absence dans
    la soumission, uniquement rempli explicitement par l'écran Administration
    > Projets après confirmation utilisateur (static/index.html,
    toggleFicheCollab). Action destructrice : supprime aussi les réalisations
    propres à ce membre pour ce projet."""
    results = []
    for slug in removed_slugs:
        collab = collab_lookup.get(slug)
        if not collab:
            results.append({
                "slug": slug, "display": slug, "file_id": None, "ok": False,
                "message": "Collaborateur introuvable — retrait ignoré", "new_yaml": "",
            })
            continue
        try:
            raw = drv.get_fiche_raw(collab["file_id"])
            data = _load_ruamel(raw)
            projets = data.get("projets") or []
            remaining = [p for p in projets if p.get("id") != projet_id]
            removed_count = len(projets) - len(remaining)
            data["projets"] = remaining
            drv.save_fiche_content(collab["file_id"], _dump_ruamel(data))
            results.append({
                "slug": slug, "display": collab.get("display", slug), "file_id": collab["file_id"],
                "ok": True,
                "message": "Retiré du projet" if removed_count else "Aucune entrée correspondante trouvée",
                "new_yaml": "",
            })
        except Exception as e:
            results.append({
                "slug": slug, "display": collab.get("display", slug), "file_id": collab["file_id"],
                "ok": False, "message": f"Erreur lors du retrait : {e}", "new_yaml": "",
            })
    return results


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
