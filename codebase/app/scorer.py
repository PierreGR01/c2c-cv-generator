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


# Nombre de clients au-delà duquel la liste est synthétisée (illisible sinon sur un CV).
MAX_CLIENTS_CITES = 3

# Libellé générique parfois utilisé en client_ref pour des clients non identifiés
# individuellement : jamais cité nommément, il ne fait que gonfler le nombre de clients.
_CLIENT_PLACEHOLDER = "clients divers"

# Suffixe de synthèse quand la liste de clients dépasse MAX_CLIENTS_CITES, par langue.
_CLIENTS_SUFFIX = {
    "fr": "et divers autres clients",
    "en": "and other clients",
}


def _cite_clients(items: list, priority_refs: set, lang: str = "fr") -> str:
    """Cite au plus MAX_CLIENTS_CITES clients (le(s) priorisé(s) par l'AO en tête s'ils en
    font partie), suivis du suffixe de synthèse (langue `lang`)."""
    nommables = [c for c in items if c.strip().lower() != _CLIENT_PLACEHOLDER]
    prioritaires = [c for c in nommables if c in priority_refs]
    autres = [c for c in nommables if c not in priority_refs]
    cites = (prioritaires + autres)[:MAX_CLIENTS_CITES]
    return ", ".join(cites) + " " + _CLIENTS_SUFFIX.get(lang, _CLIENTS_SUFFIX["fr"])


def resolve_client_display(p: dict, priority_refs: set | None = None, lang: str = "fr") -> str:
    """Résout le libellé 'client' affiché sur le CV à partir de client_custom/client_ref/sous_entite.

    - Par défaut : client_ref (plusieurs valeurs jointes par ", "), avec la sous-entité
      ajoutée sous la forme "client_ref — sous-entité" si un seul client_ref est renseigné.
    - client_custom, s'il est renseigné, se substitue entièrement à ce libellé par défaut —
      sauf s'il s'agit lui-même d'une liste de clients trop longue (texte libre hérité de
      l'ancien champ "client:", pré-datant client_ref) : même règle de troncature que ci-dessous.
    - Au-delà de MAX_CLIENTS_CITES clients, la liste devient illisible sur un CV : on n'en
      cite plus que MAX_CLIENTS_CITES (le client priorisé par l'AO en tête s'il figure dans
      la liste), suivis de "et divers autres clients".
    """
    priority_refs = priority_refs or set()

    custom = (p.get("client_custom") or "").strip()
    if custom:
        parts = [c.strip() for c in custom.split(",") if c.strip()]
        if len(parts) <= MAX_CLIENTS_CITES:
            return custom
        return _cite_clients(parts, priority_refs, lang)

    refs = p.get("client_ref") or []
    if isinstance(refs, str):
        refs = [refs]
    sous_entite = (p.get("sous_entite") or "").strip()
    if len(refs) == 1 and sous_entite:
        return f"{refs[0]} — {sous_entite}"
    if len(refs) <= MAX_CLIENTS_CITES:
        return ", ".join(refs)

    return _cite_clients(refs, priority_refs, lang)


def _collapse_periode_duplicate(periode: str) -> str:
    """Si periode répète la même année de part et d'autre du tiret (ex: "2026 – 2026",
    "2026-2026"), ne garde qu'une seule valeur pour éviter l'affichage "AAAA-AAAA"."""
    s = (periode or "").strip()
    m = re.match(r'^(\d{4})\s*[-–—]\s*(\d{4})$', s)
    if m and m.group(1) == m.group(2):
        return m.group(1)
    return s


def sans_meta(p: dict, hide_designation: bool = False, priority_refs: set | None = None, lang: str = "fr") -> dict:
    # "technologies" est l'ancien nom du champ, remplacé par "competences" — on l'exclut
    # pour éviter qu'il ne soit transmis au template si les deux coexistent.
    # "client_custom"/"client_ref"/"sous_entite" sont des méta-champs de ciblage/résolution,
    # pas transmis tels quels : seul le "client" résolu (resolve_client_display) l'est.
    # "role_en"/"designation_en"/"contexte_en"/"realisations_en" ont déjà été fusionnés dans
    # les champs FR par localize_master() avant l'appel — on ne les transmet pas bruts.
    result = {
        k: v for k, v in p.items()
        if k not in ("id", "domaines", "secteur", "poids", "technologies",
                     "client_custom", "client_ref", "sous_entite",
                     "role_en", "designation_en", "contexte_en", "realisations_en")
    }
    result["client"] = resolve_client_display(p, priority_refs, lang)
    if hide_designation:
        result.pop("designation", None)
    # Normalise periode en string — YAML peut parser "2026" comme entier
    # ce qui ferait planter la comparaison periode != "" dans le template Typst
    if "periode" in result:
        result["periode"] = _collapse_periode_duplicate(str(result["periode"]))
    return result


# ---------------------------------------------------------------------------
# Compétences
# ---------------------------------------------------------------------------

# Libellés lisibles pour les clés de famille du référentiel (ex: "design_ux").
# Ingest.py peut écrire ces clés brutes telles quelles comme "categorie" dans une
# fiche collaborateur (nouvelle compétence auto-ajoutée) : on les nettoie ici, au
# moment de la génération du CV, pour ne jamais afficher de underscore à l'écran.
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
    "nouvelles_competences":    "Nouvelles compétences",
    "ajouts_cp":                "Ajouts CP",
}

# Miroir anglais de _FAMILY_LABELS (mêmes clés référentiel snake_case).
_FAMILY_LABELS_EN = {
    "cartographie_web":         "Web mapping",
    "serveurs_carto":           "Map servers",
    "sig_desktop":              "Desktop GIS",
    "catalogues_metadonnees":   "Catalogues & Metadata",
    "bases_de_donnees":         "Databases",
    "etl_donnees":              "ETL & Data",
    "infrastructure":           "Infrastructure",
    "langages":                 "Languages",
    "frameworks_backend":       "Backend Frameworks",
    "frameworks_frontend":      "Frontend Frameworks",
    "ia_ml":                    "AI & Machine Learning",
    "mobile":                   "Mobile",
    "tests":                    "Testing",
    "outils_dev":               "Dev Tools",
    "cms":                      "CMS",
    "3d_visualisation":         "3D & Visualisation",
    "monitoring_bi":            "Monitoring & BI",
    "reseau_telecom_securite":  "Network, Telecom & Security",
    "design_systems":           "Design Systems",
    "design_ui":                "UI Design",
    "design_ux":                "UX Design",
    "gestion_conseil":          "Management & Consulting",
    "erp_odoo":                 "ERP & Odoo",
    "nouvelles_competences":    "New skills",
    "ajouts_cp":                "Additions",
}

_FAMILY_LABELS_BY_LANG = {"fr": _FAMILY_LABELS, "en": _FAMILY_LABELS_EN}


def _clean_categorie_label(categorie: str, lang: str = "fr") -> str:
    """Convertit une clé brute de référentiel (snake_case) en libellé propre.
    Les catégories déjà lisibles (avec espaces, majuscules...) passent inchangées."""
    if not categorie or "_" not in categorie:
        return categorie
    labels = _FAMILY_LABELS_BY_LANG.get(lang, _FAMILY_LABELS)
    return labels.get(categorie, categorie.replace("_", " ").title())


def _score_competence(cat: dict, dom_ao: set) -> int:
    dom_c = {d.lower() for d in cat.get("domaines", [])}
    return len(dom_ao & dom_c)


def projeter_competences(master: dict, cible: dict | None = None, lang: str = "fr") -> list:
    cats = master.get("competences", [])
    if cible is not None:
        dom_ao = {d.lower() for d in cible.get("domaines", [])}
        if dom_ao:
            cats = sorted(cats, key=lambda c: _score_competence(c, dom_ao), reverse=True)
    result = []
    for c in cats:
        cleaned = {k: v for k, v in c.items() if k not in ("domaines", "categorie_en")}
        categorie = c.get("categorie_en") if lang == "en" and c.get("categorie_en") else c.get("categorie")
        if "categorie" in cleaned:
            cleaned["categorie"] = _clean_categorie_label(categorie, lang)
        result.append(cleaned)
    return result


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
# Localisation FR/EN
# ---------------------------------------------------------------------------

# Table de correspondance statique pour identite.langues[] (texte libre FR sur la
# quasi-totalité des fiches). Valeur absente de la table -> passage inchangé (jamais
# d'invention d'une traduction) ; l'éditeur Admin signale ce cas dans ses "gaps".
_LANGUE_LABELS_EN = {
    "Français": "French",
    "Anglais": "English",
    "Allemand": "German",
    "Espagnol": "Spanish",
    "Italien": "Italian",
    "Portugais": "Portuguese",
    "Néerlandais": "Dutch",
    "Suisse allemand": "Swiss German",
}

_NIVEAU_LABELS_EN = {
    "Langue maternelle": "Native",
    "Bilingue": "Bilingual",
    "Courant": "Fluent",
    "Courant (C2)": "Fluent (C2)",
    "Usage professionnel (B2)": "Professional working proficiency (B2)",
    "Usage professionnel": "Professional working proficiency",
    "Très bonnes connaissances": "Very good knowledge",
    "Bonnes connaissances": "Good knowledge",
    "Connaissances de base": "Basic knowledge",
    "Niveau scolaire": "Basic / school level",
    "Fluide": "Fluent",
}


def _localize_langues(langues: list) -> list:
    out = []
    for entry in langues:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        langue = entry.get("langue", "")
        niveau = entry.get("niveau", "")
        out.append({
            **entry,
            "langue": _LANGUE_LABELS_EN.get(langue, langue),
            "niveau": _NIVEAU_LABELS_EN.get(niveau, niveau),
        })
    return out


def _pick(d: dict, fr_key: str, en_key: str, lang: str):
    """Retourne d[en_key] si lang == 'en' et non vide, sinon d[fr_key] (jamais de trou)."""
    if lang == "en":
        en_val = d.get(en_key)
        if en_val:
            return en_val
    return d.get(fr_key)


def _localize_projet(p: dict, lang: str) -> dict:
    if lang != "en":
        return p
    return {
        **p,
        "role": _pick(p, "role", "role_en", lang),
        "designation": _pick(p, "designation", "designation_en", lang),
        "contexte": _pick(p, "contexte", "contexte_en", lang),
        "realisations": _pick(p, "realisations", "realisations_en", lang),
    }


def localize_master(master: dict, lang: str) -> dict:
    """Retourne une copie de `master` où les champs de prose (profil, profils_cibles,
    poste, langues, projets[], parcours[], certifications[]) ont été remplacés par leur
    variante `_en` (repli sur la valeur FR si absente/vide). No-op si lang == "fr" — le
    reste du pipeline (scoring, sélection, sans_meta) continue de lire les mêmes clés
    qu'aujourd'hui, sans jamais avoir besoin de connaître la langue."""
    if lang != "en":
        return master

    m = dict(master)

    identite = dict(master.get("identite", {}))
    identite["poste"] = _pick(identite, "poste", "poste_en", lang)
    identite["langues"] = _localize_langues(identite.get("langues", []) or [])
    m["identite"] = identite

    # Ne pose la clé "profil" que si une valeur existe : sinon on laisse la clé
    # absente pour que le repli sur "profil_general" (florian-necas.yaml) continue
    # de fonctionner en aval, exactement comme en français.
    profil_localise = _pick(master, "profil", "profil_en", lang)
    if profil_localise:
        m["profil"] = profil_localise
    else:
        m.pop("profil", None)

    profils_cibles_fr = master.get("profils_cibles", {}) or {}
    profils_cibles_en = master.get("profils_cibles_en", {}) or {}
    m["profils_cibles"] = {
        k: (profils_cibles_en.get(k) or v) for k, v in profils_cibles_fr.items()
    }

    m["projets"] = [_localize_projet(p, lang) for p in master.get("projets", [])]

    m["parcours"] = [
        {**x, "poste": _pick(x, "poste", "poste_en", lang)}
        for x in master.get("parcours", [])
    ]

    m["certifications"] = [
        {**c, "intitule": _pick(c, "intitule", "intitule_en", lang)}
        for c in master.get("certifications", [])
    ]

    return m


# ---------------------------------------------------------------------------
# Projection principale
# ---------------------------------------------------------------------------

def projeter_cible(master: dict, cible: dict, lang: str = "fr") -> dict:
    """Produit le dict de données CV à partir de la fiche maître + cible AO.

    `lang` ("fr" ou "en") ne change ni le scoring ni la sélection des projets
    (uniquement basés sur des champs structurés) : localize_master() ne fait que
    substituer le texte de prose avant que le reste de la fonction ne s'exécute
    exactement comme en français.
    """
    master = localize_master(master, lang)
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
    comps = projeter_competences(master, cible, lang)

    identite = dict(master["identite"])
    identite["experience_ans"] = calculer_experience_ans(master)

    result = {
        "identite": identite,
        "profil": profil,
        "competences": comps,
        "certifications": master.get("certifications", []),
        "projets": [sans_meta(p, hide_designation, client_refs, lang) for p in selection],
        "parcours": parcours,
        "lang": lang,
    }
    if "comp_items_font" in master:
        result["comp_items_font"] = master["comp_items_font"]
    return result


def projeter_simple(master: dict, max_p: int = 4, annee_min: int = 0, lang: str = "fr") -> dict:
    """Projection sans cible : tri par récence puis poids décroissants."""
    master = localize_master(master, lang)
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
    comps = projeter_competences(master, None, lang)

    identite = dict(master["identite"])
    identite["experience_ans"] = calculer_experience_ans(master)

    result = {
        "identite": identite,
        "profil": profil,
        "competences": comps,
        "certifications": master.get("certifications", []),
        "projets": [sans_meta(p, lang=lang) for p in tries],
        "parcours": master.get("parcours", []),
        "lang": lang,
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
