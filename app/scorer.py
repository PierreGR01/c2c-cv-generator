"""
Moteur de scoring et projection AO → données CV.
Porté depuis build-cv.py du skill c2c-cv-generator.
"""
import datetime


# ---------------------------------------------------------------------------
# Scoring projet
# ---------------------------------------------------------------------------

def score_projet(projet: dict, cible: dict) -> float:
    s = projet.get("poids", 1)
    dom_ao = {d.lower() for d in cible.get("domaines", [])}
    dom_p = {d.lower() for d in projet.get("domaines", [])}
    s += 3 * len(dom_ao & dom_p)
    tech_ao = {t.lower() for t in cible.get("technologies_cles", cible.get("technologies", []))}
    # supporte le nouveau champ "competences" (renommage de "technologies")
    tech_p = {t.lower() for t in projet.get("competences", projet.get("technologies", []))}
    s += 2 * len(tech_ao & tech_p)
    if cible.get("secteur") and projet.get("secteur") == cible.get("secteur"):
        s += 2
    return s


def sans_meta(p: dict) -> dict:
    # "technologies" est l'ancien nom du champ, remplacé par "competences" — on l'exclut
    # pour éviter qu'il ne soit transmis au template si les deux coexistent.
    return {k: v for k, v in p.items() if k not in ("id", "domaines", "secteur", "poids", "technologies")}


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

    candidats = [p for p in projets if p.get("id") not in exclure]
    forces = [p for p in candidats if p.get("id") in inclure]
    autres = [p for p in candidats if p.get("id") not in inclure]
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
        "projets": [sans_meta(p) for p in selection],
        "parcours": parcours,
    }
    if "comp_items_font" in master:
        result["comp_items_font"] = master["comp_items_font"]
    return result


def projeter_simple(master: dict, max_p: int = 4) -> dict:
    """Projection sans cible : tri par poids décroissant."""
    projets = master.get("projets", [])
    tries = sorted(projets, key=lambda p: p.get("poids", 1), reverse=True)[:max_p]

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
    scored = [{"id": p.get("id"), "client": p.get("client"), "score": score_projet(p, cible)} for p in projets]
    return sorted(scored, key=lambda x: x["score"], reverse=True)
