"""
Moteur de scoring et projection AO → données CV.
Porté depuis build-cv.py du skill c2c-cv-generator.
"""
import datetime
import re
import unicodedata


# ---------------------------------------------------------------------------
# Normalisation des domaines
# ---------------------------------------------------------------------------

def _norm_domain(d: str) -> str:
    """Normalise un label de domaine pour comparaison insensible aux accents/casse/séparateurs.

    Exemples :
        "Géospatial"     → "geospatial"
        "open source"    → "open-source"
        "risques naturels" → "risques-naturels"
        "développement"  → "developpement"
    """
    d = d.lower().strip()
    # Supprimer les accents (NFD + strip combining chars)
    d = ''.join(c for c in unicodedata.normalize('NFD', d)
                if unicodedata.category(c) != 'Mn')
    # Normaliser les séparateurs (espaces, underscores → tirets)
    d = re.sub(r'[\s_]+', '-', d)
    return d


# ---------------------------------------------------------------------------
# Scoring projet
# ---------------------------------------------------------------------------

def _annee_projet(projet: dict) -> int | None:
    """Extrait l'année la plus récente du champ 'periode' (ex: '2024', '2023-2025', 'Jan 2026')."""
    periode = str(projet.get("periode", "") or "")
    annees = re.findall(r'\b(20\d{2}|19\d{2})\b', periode)
    return max(int(a) for a in annees) if annees else None


def score_projet(projet: dict, cible: dict) -> float:
    s = projet.get("poids", 1)

    # Récence : bonus fort et dégressif pour que les projets récents
    # apparaissent toujours en priorité sur 1 page
    # age 0→+10, 1→+7, 2→+5, 3→+3, 4→+1, 5+→+0
    annee = _annee_projet(projet)
    if annee:
        age = max(0, datetime.date.today().year - annee)
        recency_bonus = [10, 7, 5, 3, 1, 0]
        s += recency_bonus[min(age, 5)]

    # Domaines : comparaison normalisée (insensible accents/casse/séparateurs)
    dom_ao = {_norm_domain(d) for d in cible.get("domaines", [])}
    dom_p = {_norm_domain(d) for d in projet.get("domaines", [])}
    s += 3 * len(dom_ao & dom_p)

    tech_ao = {t.lower() for t in cible.get("technologies_cles", cible.get("technologies", []))}
    # supporte le nouveau champ "competences" (renommage de "technologies")
    tech_p = {t.lower() for t in projet.get("competences", projet.get("technologies", []))}
    s += 2 * len(tech_ao & tech_p)

    if cible.get("secteur") and projet.get("secteur") == cible.get("secteur"):
        s += 2

    return s


def resolve_client_display(p: dict) -> str:
    """Résout le libellé 'client' affiché sur le CV à partir de client_custom/client_ref/sous_entite.

    - Par défaut : client_ref (plusieurs valeurs jointes par ", "), avec la sous-entité
      ajoutée sous la forme "client_ref — sous-entité" si un seul client_ref est renseigné.
    - client_custom, s'il est renseigné, se substitue entièrement à ce libellé par défaut.
    """
    custom = (p.get("client_custom") or "").strip()
    if custom:
        return custom
    refs = p.get("client_ref") or []
    if isinstance(refs, str):
        refs = [refs]
    sous_entite = (p.get("sous_entite") or "").strip()
    if len(refs) == 1 and sous_entite:
        return f"{refs[0]} — {sous_entite}"
    return ", ".join(refs)


def sans_meta(p: dict, hide_designation: bool = False) -> dict:
    # "technologies" est l'ancien nom du champ, remplacé par "competences" — on l'exclut
    # pour éviter qu'il ne soit transmis au template si les deux coexistent.
    # "client_custom"/"client_ref"/"sous_entite" sont des méta-champs de ciblage/résolution,
    # pas transmis tels quels : seul le "client" résolu (resolve_client_display) l'est.
    result = {
        k: v for k, v in p.items()
        if k not in ("id", "domaines", "secteur", "poids", "technologies",
                     "client_custom", "client_ref", "sous_entite")
    }
    result["client"] = resolve_client_display(p)
    if hide_designation:
        result.pop("designation", None)
    # Normalise periode en string — YAML peut parser "2026" comme entier
    # ce qui ferait planter la comparaison periode != "" dans le template Typst
    if "periode" in result:
        result["periode"] = str(result["periode"])
    return result


# ---------------------------------------------------------------------------
# Compétences
# ---------------------------------------------------------------------------

def _score_competence(cat: dict, dom_ao: set) -> int:
    dom_c = {d.lower() for d in cat.get("domaines", [])}
    return len(dom_ao & dom_c)


def projeter_competences(master: dict, cible: dict | None = None) -> list:
    cats = master.get("competences", [])
    if cible is not None:
        dom_ao = {d.lower() for d in cible.get("domaines", [])}
        if dom_ao:
            cats = sorted(cats, key=lambda c: _score_competence(c, dom_ao), reverse=True)
    return [{k: v for k, v in c.items() if k != "domaines"} for c in cats]


# ---------------------------------------------------------------------------
# Expérience
# ---------------------------------------------------------------------------

def calculer_experience_ans(master: dict) -> int:
    id_section = master.get("identite", {})
    annee_debut = id_section.get("annee_debut_carriere")
    if annee_debut:
        return datetime.date.today().year - int(annee_debut)
    return id_section.get("experience_ans", 0)


# ---------------------------------------------------------------------------
# Projection principale
# ---------------------------------------------------------------------------

def projeter_cible(master: dict, cible: dict) -> dict:
    """Produit le dict de données CV à partir de la fiche maître + cible AO."""
    projets = master.get("projets", [])
    inclure = set(cible.get("inclure", []))
    exclure = set(cible.get("exclure", []))
    max_p = cible.get("max_projets", 4)
    annee_min = cible.get("annee_min") or 0

    hide_designation = bool(cible.get("masquer_designations"))
    candidats = [p for p in projets if p.get("id") not in exclure]
    # Filtre par année minimum (exclut les projets trop anciens)
    if annee_min:
        candidats = [p for p in candidats if (_annee_projet(p) or 0) >= annee_min]
    forces = [p for p in candidats if p.get("id") in inclure]
    autres = [p for p in candidats if p.get("id") not in inclure]

    client_refs = set(cible.get("client_refs") or [])
    if client_refs:
        # Priorise les projets réalisés avec un des clients sélectionnés, triés par poids
        # entre eux, puis complète avec le reste des projets (pondération classique).
        prio = [p for p in autres if client_refs & set(p.get("client_ref") or [])]
        reste = [p for p in autres if p not in prio]
        prio.sort(key=lambda p: score_projet(p, cible), reverse=True)
        reste.sort(key=lambda p: score_projet(p, cible), reverse=True)
        autres = prio + reste
    else:
        autres.sort(key=lambda p: score_projet(p, cible), reverse=True)

    # 0 = tous les projets, pas de limite
    selection = (forces + autres) if max_p == 0 else (forces + autres)[:max_p]

    # Profil
    profil = master.get("profil", master.get("profil_general", ""))
    variante = cible.get("profil_cle") or cible.get("profil")
    if variante:
        profils_cibles = master.get("profils_cibles", {})
        if variante in profils_cibles:
            profil = profils_cibles[variante]

    # Inclus par défaut, sauf si explicitement désactivé avec inclure_parcours: false
    inclure_parcours = cible.get("inclure_parcours", True)
    parcours = master.get("parcours", []) if inclure_parcours else []
    comps = projeter_competences(master, cible)

    identite = dict(master["identite"])
    identite["experience_ans"] = calculer_experience_ans(master)

    result = {
        "identite": identite,
        "profil": profil,
        "competences": comps,
        "certifications": master.get("certifications", []),
        "projets": [sans_meta(p, hide_designation) for p in selection],
        "parcours": parcours,
    }
    if "comp_items_font" in master:
        result["comp_items_font"] = master["comp_items_font"]
    return result


def projeter_simple(master: dict, max_p: int = 4, annee_min: int = 0) -> dict:
    """Projection sans cible : tri par récence puis poids décroissants."""
    projets = master.get("projets", [])
    annee_courante = datetime.date.today().year
    if annee_min:
        projets = [p for p in projets if (_annee_projet(p) or 0) >= annee_min]
    def _score_simple(p):
        annee = _annee_projet(p) or 0
        age = max(0, annee_courante - annee) if annee else 99
        recency_bonus = [10, 7, 5, 3, 1, 0]
        return (recency_bonus[min(age, 5)], p.get("poids", 1))
    tries = sorted(projets, key=_score_simple, reverse=True)[:max_p]

    profil = master.get("profil", master.get("profil_general", ""))
    comps = projeter_competences(master, None)

    identite = dict(master["identite"])
    identite["experience_ans"] = calculer_experience_ans(master)

    result = {
        "identite": identite,
        "profil": profil,
        "competences": comps,
        "certifications": master.get("certifications", []),
        "projets": [sans_meta(p) for p in tries],
        "parcours": master.get("parcours", []),
    }
    if "comp_items_font" in master:
        result["comp_items_font"] = master["comp_items_font"]
    return result


# ---------------------------------------------------------------------------
# Utilitaire : info rapide sur les projets scorés (pour debug)
# ---------------------------------------------------------------------------

def scorer_projets(master: dict, cible: dict) -> list[dict]:
    """Retourne la liste des projets avec leur score, triés."""
    projets = master.get("projets", [])
    scored = [{"id": p.get("id"), "client_custom": p.get("client_custom"), "score": score_projet(p, cible)} for p in projets]
    return sorted(scored, key=lambda x: x["score"], reverse=True)
