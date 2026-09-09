"""
Rendu des références projets — PDF (Typst) et PPTX (python-pptx).

Les deux sorties partagent la même structure de données intermédiaire, produite
par `build_projets_data()` : un dict par projet, déjà filtré selon les options du
formulaire (chapitres retenus, équipe, compétences, images). Les gabarits ne
décident donc jamais du contenu — seulement de la mise en page.

PDF  : engine/reference-projets.typ (codes du gabarit corporate Camptocamp).
PPTX : app/reference_pptx.py (charte slides : Inter, bandeau orange fin).
"""
import io
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import yaml
from PIL import Image

ENGINE_DIR = Path(__file__).parent.parent / "engine"
TEMPLATE = ENGINE_DIR / "reference-projets.typ"
ASSETS = ENGINE_DIR / "assets"

# Chapitres de la fiche projet, dans l'ordre d'affichage, avec le libellé
# exact utilisé dans les livrables (identique côté PDF et PPTX).
CHAPITRE_LABELS = {
    "technique": "Aspects techniques",
    "visuel": "Aspects visuels",
    "ergonomie": "Aspects ergonomiques",
    "environnement": "Environnement",
    "resultats": "Résultats & impact",
}
CHAPITRE_ORDER = list(CHAPITRE_LABELS)

_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_SECTEUR_LABELS = {"public": "Public", "prive": "Privé"}

# --- Résolution de rendu des images ------------------------------------
# Une image du registre arrive à sa taille naturelle (capture d'écran, souvent
# 2500 px de large) et se retrouve posée dans un emplacement de quelques
# centaines de points. Sans rééchantillonnage, c'est le LECTEUR PDF qui réduit,
# au vol et avec un filtre rapide (boîte / plus proche voisin) : sur une
# capture d'interface — traits d'un pixel, petits textes — la réduction 6:1 que
# demandait le visuel de clôture rendait le contenu illisible et crénelé (bug
# signalé : « les images paraissent dégradées et mal rendues »). Le fichier
# embarqué, lui, était bien à pleine résolution : le défaut n'était pas dans la
# compression mais dans le facteur de réduction laissé au lecteur.
#
# On réduit donc NOUS-MÊMES, une fois, en Lanczos, à la taille exacte que le
# visuel occupe dans la page, à RENDER_DPI. Le lecteur n'a plus qu'un facteur
# modeste à absorber, et la finesse qui créne­lait a déjà été filtrée
# proprement. Effet de bord : le PDF passe de ~13 Mo à ~2 Mo.
#
# Jamais d'agrandissement : une image plus petite que sa cible est laissée
# telle quelle (l'interface de saisie, elle, refuse en amont ce qui est trop
# petit — cf. FP_DPI_MIN côté static/index.html).
#
# 200 et non 300 : mesuré sur le rendu, à l'endroit le plus exigeant du
# document — une capture d'interface réduite dans l'emplacement de clôture,
# donc du texte fin. En agrandissant le PDF à la loupe :
#   ·  72 dpi — libellés illisibles, aplats en escalier. C'est la définition
#              d'un point PDF, pas une cible : le lecteur RÉAGRANDIT ensuite
#              (1,3x sur un écran ordinaire, 2,7x sur un écran HiDPI, 4,2x à
#              l'impression). Le défaut corrigé plus haut se reproduirait, à
#              l'envers.
#   · 110 dpi — encore illisible.
#   · 150 dpi — lisible mais mou.
#   · 200 dpi — net, y compris les mentions les plus petites.
#   · 300 dpi — indiscernable de 200 à la lecture, pour deux fois le poids.
# Le plafond utile est fixé par le TEXTE des captures ; une photographie se
# contenterait de bien moins.
RENDER_DPI = 200

# Largeur RENDUE de chaque emplacement, en points — dérivée des mêmes
# constantes que le gabarit (cf. reference-projets.typ) :
#   page-w 595.28 ; marge-x 56.7 ; texte-w = page-w - 2*marge-x ; gouttiere 22.
_PAGE_W_PT = 595.28
_MARGE_X_PT = 56.7
_TEXTE_W_PT = _PAGE_W_PT - 2 * _MARGE_X_PT
_GOUTTIERE_PT = 22.0
LARGEURS_RENDU_PT = {
    # image libre : pleine largeur physique de la page (cf. pave-image-libre)
    "": _PAGE_W_PT,
    # environnement : visuel empilé pleine mesure de texte (cf. visuel-rogne)
    "environnement": _TEXTE_W_PT,
    # mises en regard à taille fixe (cf. largeur-image-large-format)
    "ergonomie": 246.0,
    "visuel": 246.0,
    # clôture débordante : moitié du bloc + la marge franchie jusqu'au bord
    # physique droit (cf. m-duo, branche `bleed`)
    "resultats": _TEXTE_W_PT / 2 + _MARGE_X_PT,
}


def largeur_rendu_px(slot: str) -> int:
    """Largeur cible en pixels d'un visuel, à RENDER_DPI, pour l'emplacement
    donné ("" = image libre). Sert au rééchantillonnage côté rendu et, en
    miroir, au garde-fou de résolution de l'interface de saisie."""
    largeur_pt = LARGEURS_RENDU_PT.get(slot, _TEXTE_W_PT)
    return round(largeur_pt / 72 * RENDER_DPI)


def normaliser_image(content: bytes, mimetype: str, slot: str) -> tuple[bytes, str]:
    """Prépare une image pour l'embarquement PDF : réduction Lanczos à la
    taille de son emplacement (cf. RENDER_DPI) et abandon d'un canal alpha
    inutile.

    L'alpha n'est retiré que s'il est INTÉGRALEMENT opaque : une capture aux
    coins arrondis pose une vraie transparence, et les visuels des chapitres
    reposent sur un aplat teinté (gris ou pêche) — les aplatir sur du blanc y
    ferait apparaître des coins blancs. Quand il est opaque partout, en
    revanche, Typst émettait quand même un masque de fusion pleine résolution
    par image : autant de poids, et un chemin de rendu composité inutile.

    Le format d'origine est conservé (PNG reste PNG, JPEG reste JPEG) : ces
    visuels sont des captures d'interface, où une recompression JPEG ferait
    baver les textes. En cas d'échec de lecture, l'original est renvoyé tel
    quel — mieux vaut un visuel non optimisé qu'un rendu qui échoue.
    """
    try:
        with Image.open(io.BytesIO(content)) as im:
            im.load()
            fmt = (im.format or "").upper()
            opaque = True
            if im.mode in ("RGBA", "LA") or "transparency" in im.info:
                alpha = im.convert("RGBA").getchannel("A")
                opaque = alpha.getextrema()[0] == 255
            im = im.convert("RGB" if opaque else "RGBA")

            cible = largeur_rendu_px(slot)
            if im.width > cible:
                hauteur = max(1, round(im.height * cible / im.width))
                im = im.resize((cible, hauteur), Image.LANCZOS)

            buf = io.BytesIO()
            if fmt in ("JPEG", "JPG") and opaque:
                im.save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
                return buf.getvalue(), "image/jpeg"
            im.save(buf, "PNG", optimize=True)
            return buf.getvalue(), "image/png"
    except Exception:
        return content, mimetype

# --- Rythme de composition -------------------------------------------
# Le répertoire de motifs est décidé ici, une fois, et non dans les gabarits :
# les deux formats donnent ainsi la même lecture, et la décision reste testable.
#   colonnes    — pleine largeur, texte en deux colonnes
#   aplat       — bande grise pleine largeur, texte en deux colonnes
#   duo         — texte en demi-largeur, visuel en regard à droite
#   duo-inverse — visuel à gauche, texte à droite
#   demi-droite — texte en demi-largeur, calé à droite (moitié gauche vide)
#   demi-gauche — texte en demi-largeur, calé à gauche
#   focus       — mesure réduite, bord gauche orange : la conclusion de la fiche
MOTIF_CYCLE = ("duo", "aplat", "demi-droite", "duo-inverse", "demi-gauche")
LONG_CHAPITRE = 450          # seuil au-delà duquel deux colonnes se justifient (PPTX)

# --- Mise en page PDF -------------------------------------------------
# Calcul strictement séparé de _assign_motifs (qui reste au service du PPTX,
# inchangé) : le PDF suit désormais un ordre et un habillage propres, décidés
# par l'identité du chapitre plutôt que par une rotation générique. Mesuré au
# pixel près sur la référence (test-rennes.pdf) :
#   · ordre fixe : environnement prolonge le contexte (faits du projet), les
#     trois chapitres de récit suivent, resultats ferme toujours la fiche ;
#   · CHAQUE chapitre porte un aplat plein — gris par défaut, pêche pour les
#     deux chapitres identité (environnement, resultats) — jamais decidé par
#     la longueur du texte ;
#   · l'aplat reste confiné aux marges du texte, SAUF celui de resultats, qui
#     déborde pleine largeur (bande de clôture du document) — MAIS avec une
#     marge interne identique à gauche et à droite (cf. bloc-plein cote
#     Typst) : une premiere version laissait une marge nulle a droite (image
#     collee au bord reel) contre la marge normale a gauche (texte), asymetrie
#     signalee et corrigee — le texte garde donc toujours l'ordre normal
#     (jamais en duo-inverse) pour rester du meme cote que sur les autres
#     chapitres.
#   · chaque image est rattachee explicitement a UN chapitre par l'interface
#     de saisie (champ `chapitre` sur l'image — pas de pool ni de rotation) :
#     au plus 4 images "de chapitre" (environnement, ergonomie, visuel,
#     resultats — jamais technique), plus une 5e image "libre" (sans
#     `chapitre`) optionnelle. Cf. _reshape_chapitres_pdf.
CHAPITRE_ORDER_PDF = ["environnement", "ergonomie", "technique", "visuel", "resultats"]
CHAPITRES_TEINTES = {"environnement", "resultats"}
CHAPITRE_DEBORDANT = "resultats"
CHAPITRE_IMAGE_KEYS = ("environnement", "ergonomie", "visuel", "resultats")
LONG_CHAPITRE_PDF = 900       # nettement au-dessus de la cible de redaction (400-650
                              # caracteres, cf. GUIDE-REDACTION.md) : un repli rare,
                              # pas la norme — le texte plein est la mise en page par defaut


def _reshape_chapitres_pdf(entry: dict) -> list[dict]:
    """
    Reconstruit, pour le seul PDF, l'ordre et l'habillage des chapitres à
    partir de l'entrée déjà produite par build_projets_data (source :
    key/label/texte de `entry["chapitres"]`). Chaque image de `entry["images"]`
    porte un champ `chapitre` (posé par l'interface de saisie) qui la rattache
    à AU PLUS un chapitre parmi CHAPITRE_IMAGE_KEYS ; une image sans ce champ
    (ou vide) est l'unique image "libre" tolérée.

    L'image libre s'affiche dans l'un des deux cas suivants (jamais les deux :
    la première condition, prioritaire, l'emporte) :
      1. la fiche ne porte AUCUNE rangée de qualification (ni compétences ni
         équipe, faute de contenu ou parce que les deux options d'inclusion
         sont décochées), OU aucun des quatre chapitres-image ne manque
         (l'image n'a alors nulle part où s'insérer dans le flux) — l'image
         est promue en tête de fiche, pleine largeur, et le chapeau vient se
         poser DESSUS : elle ne coûte donc aucune hauteur de page, ce qui
         laisse « Environnement » tenir en page 1 ;
      2. sinon, si au moins un des quatre chapitres-image est absent (aucun
         texte saisi pour lui) — elle prend alors la place du PREMIER chapitre
         manquant dans l'ordre d'affichage, en pleine largeur mais plafonnée
         en hauteur (cf. `image-libre` cote Typst).
    L'image libre n'est jamais ignorée : l'un des deux cas s'applique toujours
    dès qu'elle existe (le cas 1 couvre, entre autres, celui où les quatre
    chapitres-image sont tous rédigés).

    Dans le cas 2, quand le chapitre manquant est le PREMIER du flux
    ("environnement"), l'image libre porte en plus le fanion `ouverture_aeree` :
    elle ferme alors la page 1 et tous les chapitres commencent page 2 (cf. le
    commentaire à l'endroit où ce fanion est calculé).

    Retourne une liste ordonnée de blocs à rendre : soit un chapitre
    ({"type": "chapitre", ...}), soit l'image libre ({"type": "image_libre",
    "image": ..., "ouverture_aeree": bool}).
    """
    by_key = {c["key"]: c for c in entry.get("chapitres", [])}
    images = entry.get("images") or []
    images_par_chapitre = {}
    for im in images:
        cle = im.get("chapitre")
        if cle in CHAPITRE_IMAGE_KEYS and cle not in images_par_chapitre:
            images_par_chapitre[cle] = im
    image_libre = next((im for im in images if not im.get("chapitre")), None)

    manquants = [k for k in CHAPITRE_IMAGE_KEYS if k not in by_key]
    premier_manquant = manquants[0] if manquants else None

    duo_bascule = False
    blocs: list[dict] = []
    image_libre_placee = False
    # « Aucun bloc de qualification a afficher » — et non « pas d'equipe » :
    # c'est bien l'absence de la RANGEE (competences ET equipe) qui laisse la
    # tete de fiche assez nue pour qu'une image pleine largeur y trouve sa
    # place. Decocher « Equipe Camptocamp » en gardant les competences (cas
    # courant) vidait `equipe` et suffisait donc a promouvoir l'image : le
    # chapeau se posait dessus, l'ouverture aeree ne se declenchait plus, et le
    # premier chapitre remontait en page 1 — sans qu'aucun controle de la
    # boucle ne s'en apercoive (cf. `env_check_needed` / `ouverture_aeree` dans
    # render_pdf, tous deux inoperants dans cette configuration). Bug signale.
    sans_qualification = not entry.get("equipe") and not entry.get("competences")
    # Deux situations mènent à la promotion sous le chapeau — la seule position
    # qui ne coûte AUCUNE hauteur de page, l'image courant derrière un bloc qui
    # existe de toute façon (cf. chapeau-sur-image côté gabarit) :
    #   · la fiche ne porte aucune rangée de qualification ;
    #   · aucun chapitre-image ne manque, l'image n'a donc aucun créneau dans
    #     le flux des chapitres. Lui faire fermer la page 1 (ouverture aérée,
    #     essayé) repoussait « Environnement » en page 2 — inacceptable, c'est
    #     la première contrainte de la boucle (bug signalé sur la fiche
    #     Rennes, dont les quatre chapitres-image sont tous rédigés).
    image_libre_promue = image_libre is not None and (
        sans_qualification or premier_manquant is None
    )

    # « Ouverture aérée » — le cas de la fiche dont le chapitre
    # « Environnement » n'est pas rédigé alors qu'une équipe l'est.
    #
    # L'image libre prend alors la place du TOUT PREMIER chapitre du flux, et
    # le suivant venait se glisser juste dessous : la page 1 portait le titre,
    # les faits, la qualification, le contexte, l'image ET deux chapitres,
    # pendant que la page 2 n'en portait que deux, au milieu du blanc. Le
    # contenu ne suffit pas à remplir deux pages denses, il suffit largement à
    # en remplir une — d'où ce déséquilibre.
    #
    # Le gabarit traite ce cas à part (cf. image-libre-ouverture) : l'image
    # ferme la page 1, tous les chapitres commencent page 2, et le blanc gagné
    # sert à aérer la page plutôt qu'à s'accumuler sous l'image.
    #
    # `premier_manquant == "environnement"` et non « environnement absent » :
    # c'est bien la POSITION de l'image dans le flux qui crée le déséquilibre.
    # Manquerait-il un chapitre plus loin que l'image s'y insérerait sans rien
    # déséquilibrer, et la mise en page ordinaire reste la bonne.
    # L'ouverture aérée — l'image ferme la page 1, tous les chapitres commencent
    # page 2 — ne concerne donc plus que le cas où le PREMIER chapitre du flux
    # (« Environnement ») n'est pas rédigé : l'image prend sa place, et aucun
    # chapitre ne réclame la page 1.
    ouverture_aeree = (
        not image_libre_promue
        and image_libre is not None
        and premier_manquant == CHAPITRE_ORDER_PDF[0]
    )
    if image_libre_promue:
        # `sous_contexte` : le gabarit ne pose pas cette image dans le flux, il
        # la SUPERPOSE au chapeau (« Contexte complet du projet »), qui vient
        # se poser dessus — cf. chapeau-sur-image. Dans l'autre cas de figure
        # (l'image prend la place d'un chapitre-image manquant, plus bas), elle
        # reste un pave a part entiere dans le flux.
        blocs.append({"type": "image_libre", "image": image_libre, "sous_contexte": True})
        image_libre_placee = True
    elif ouverture_aeree:
        # Posée AVANT la boucle, et non à l'itération du chapitre manquant :
        # c'est la seule position qui couvre les deux cas de figure d'un coup —
        # le premier chapitre manque (l'image occupait déjà cette place, en
        # première itération : ordre inchangé), ou aucun ne manque (la boucle
        # n'aurait alors jamais eu d'occasion de la poser, et l'image se
        # perdait).
        blocs.append({"type": "image_libre", "image": image_libre, "ouverture_aeree": True})
        image_libre_placee = True
    for k in CHAPITRE_ORDER_PDF:
        if not image_libre_placee and k == premier_manquant and image_libre is not None:
            # Un chapitre-image manquant, mais pas le premier du flux :
            # l'image s'insère à sa place, dans le flux, sans saut de page —
            # rien à rééquilibrer, la mise en page ordinaire reste la bonne.
            blocs.append({
                "type": "image_libre",
                "image": image_libre,
                "ouverture_aeree": False,
            })
            image_libre_placee = True
            continue
        if k not in by_key:
            continue
        ch = dict(by_key[k])
        ch["fill"] = "peach" if k in CHAPITRES_TEINTES else "grey"
        ch["bleed"] = k == CHAPITRE_DEBORDANT
        # `ancre_bas` : « Environnement » se cale au BAS de sa page, le blanc
        # restant se reportant entre l'image libre et lui (demande explicite).
        # Uniquement quand l'image libre est effectivement promue en tete de
        # fiche : c'est de cet espace-la qu'il s'agit. Sans elle, ancrer le
        # chapitre en bas ne deplacerait qu'un trou du bas vers le haut.
        ch["ancre_bas"] = k == "environnement" and image_libre_promue
        im = images_par_chapitre.get(k) if k in CHAPITRE_IMAGE_KEYS else None
        if im is None:
            ch["layout"] = "colonnes" if len(ch["texte"]) >= LONG_CHAPITRE_PDF else "full"
            ch["images"] = []
        elif k == "environnement":
            # Chapitre identite : toujours la pile titre/texte/image, jamais
            # la mise en regard (signature graphique propre aux chapitres a
            # fond peche).
            ch["layout"] = "stack"
            ch["images"] = [{**im, "bleed": False}]
        elif ch["bleed"]:
            ch["layout"] = "duo"
            ch["images"] = [im]
        else:
            ch["layout"] = "duo-inverse" if duo_bascule else "duo"
            duo_bascule = not duo_bascule
            ch["images"] = [im]
        blocs.append({"type": "chapitre", **ch})

    return blocs


def _assign_motifs(chapitres: list[dict], images_libres: list[int]) -> list[int]:
    """
    Attribue à chaque chapitre son motif de composition et, pour les mises en
    regard, l'index du visuel associé. Retourne les visuels non consommés.

    Le rythme découle du contenu, il n'est pas décoratif :
      · le dernier chapitre porte toujours le bloc focus — c'est la conclusion ;
      · le chapitre le plus long, s'il est vraiment long, passe en deux colonnes
        pleine largeur : seule mesure qui absorbe un pavé sans fatiguer l'œil ;
      · les autres alternent demi-largeurs et bandes pleine largeur, en
        consommant les visuels disponibles pour les mises en regard.
    """
    if not chapitres:
        return list(images_libres)

    dispo = list(images_libres)
    for ch in chapitres:
        ch["motif"] = None
        ch["image_idx"] = None

    chapitres[-1]["motif"] = "focus"

    reste = list(range(len(chapitres) - 1))
    if reste:
        i_long = max(reste, key=lambda i: len(chapitres[i]["texte"]))
        if len(chapitres[i_long]["texte"]) >= LONG_CHAPITRE:
            chapitres[i_long]["motif"] = "colonnes"

    k = 0
    for i in reste:
        if chapitres[i]["motif"]:
            continue
        # On avance dans le cycle jusqu'à un motif applicable : les mises en
        # regard sont écartées dès qu'il n'y a plus de visuel disponible.
        for _ in range(len(MOTIF_CYCLE)):
            motif = MOTIF_CYCLE[k % len(MOTIF_CYCLE)]
            k += 1
            if motif in ("duo", "duo-inverse") and not dispo:
                continue
            chapitres[i]["motif"] = motif
            if motif in ("duo", "duo-inverse"):
                chapitres[i]["image_idx"] = dispo.pop(0)
            break
        if not chapitres[i]["motif"]:
            chapitres[i]["motif"] = "aplat"

    return dispo


_NBSP = " "
# Unités susceptibles de suivre un nombre dans une fiche projet. Liste courte
# et explicite : une règle générique collerait aussi des mots ordinaires.
_UNITES = r"(?:%|‰|€|[kMG]?€|Md€|k?m²?|km|ha|[kMG]?[oO]ctets?|[GTM]o|[kM]?Wc|ETP|j|h)"


def _typographie(txt: str) -> str:
    """
    Espaces insécables du français : séparateur de milliers, et unité liée à
    son nombre. Sans cela « 500 000 » et « 1 M€ » se coupent en fin de ligne,
    ce qui arrive vite sur les mesures étroites des motifs en demi-largeur.
    """
    txt = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", _NBSP, txt)
    txt = re.sub(rf"(?<=\d) (?={_UNITES}(?![\w²]))", _NBSP, txt)
    return txt


def _clean(value) -> str:
    return _typographie(str(value).strip()) if value is not None else ""


# Unités du budget, telles que proposées à la saisie. L'ordre fait foi côté
# interface (liste déroulante) comme ici (contrôle de ce qui est accepté).
BUDGET_UNITES = ("€", "K€", "M€")


def _budget_label(projet: dict) -> str:
    """« 555 000 € », « 55 K€ », « 8 M€ » — le montant est saisi en nombre et
    l'unité choisie à part (cf. le formulaire de déclaration) : c'est ici, et
    nulle part ailleurs, que les deux se recomposent en un libellé.

    Espaces insécables partout (séparateur de milliers ET liaison au symbole) :
    une cellule de faits est étroite, un budget qui se coupe en fin de ligne y
    est illisible. Un montant absent, nul ou illisible ne produit pas de
    cellule du tout — la rangée de faits filtre déjà les valeurs vides.
    """
    montant = projet.get("budget_montant")
    if montant is None or str(montant).strip() == "":
        return ""
    # Le champ de saisie est numérique, mais un montant recopié d'ailleurs
    # peut arriver espacé (« 555 000 ») ou à virgule décimale.
    brut = str(montant).replace(",", ".")
    for espace in (" ", "\u00a0", "\u202f", "\u2009"):
        brut = brut.replace(espace, "")
    try:
        valeur = float(brut)
    except ValueError:
        return ""
    if valeur <= 0:
        return ""
    if valeur == int(valeur):
        chiffres = f"{int(valeur):,}".replace(",", _NBSP)
    else:
        chiffres = f"{valeur:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    unite = str(projet.get("budget_unite") or "").strip() or BUDGET_UNITES[0]
    if unite not in BUDGET_UNITES:
        unite = BUDGET_UNITES[0]
    return f"{chiffres}{_NBSP}{unite}"


def _client_label(projet: dict) -> str:
    """`client_ref` est une liste (groupement possible) — un seul libellé lisible."""
    refs = projet.get("client_ref") or []
    if isinstance(refs, str):
        refs = [refs]
    refs = [_clean(r) for r in refs if _clean(r)]
    return " / ".join(refs)


# ─── Liens cliquables d'une fiche : lien de publication et contacts ──────────
# Ces regles vivent ICI, et non cote ingestion, parce qu'elles decrivent ce qui
# fait un lien EXPLOITABLE dans le PDF — app/ingest.py les importe pour
# normaliser a l'ecriture (cf. _as_lien_projet / _as_contacts). Deux copies
# auraient fini par diverger, et c'est le rendu qui l'aurait paye.

# Au plus trois points de contact sur une fiche : la cellule « Contacts » fait
# une demi-mesure de texte, au-dela elle deborderait.
MAX_CONTACTS = 3

# Validation volontairement large : le but n'est pas de certifier une adresse,
# c'est d'eviter qu'un `mailto:` mort ne devienne cliquable dans une fiche
# deja partie chez le client.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
# Prefixe « schema: » d'une URL. Sert a distinguer un schema REEL d'un
# « example.fr:8080 », dont le deux-points annonce un port : les caracteres
# autorises dans un schema (RFC 3986) incluent le point, un hote suivi de son
# port a donc exactement la meme forme.
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.IGNORECASE)


def normaliser_lien(value) -> str:
    """URL prête à devenir une annotation cliquable dans le PDF — ou "" si
    rien d'exploitable.

    Une adresse recopiée depuis la barre du navigateur arrive souvent sans
    schéma (« geo.example.fr/portail ») : Typst en ferait un lien RELATIF,
    donc mort dès l'ouverture du PDF (constaté : annotation présente, URI
    nulle). Le schéma est donc complété — https, jamais http par défaut — et
    tout ce qui n'est pas http(s) est refusé plutôt que rafistolé : un
    « https://mailto:… » serait un lien mort de plus, mais cliquable.
    """
    url = "" if value is None else str(value).strip()
    if not url:
        return ""
    scheme = _SCHEME_RE.match(url)
    if scheme:
        if scheme.group(1).lower() in ("http", "https"):
            pass  # déjà une adresse web complète
        elif url[scheme.end():scheme.end() + 1].isdigit():
            url = "https://" + url  # pas un schéma mais un port
        else:
            return ""
    elif url.startswith("//"):
        url = "https:" + url
    else:
        url = "https://" + url
    return url if _URL_RE.match(url) else ""


def normaliser_email(value) -> str:
    """Adresse e-mail, ou "" si elle ne peut pas faire une cible `mailto:`."""
    email = "" if value is None else str(value).strip()
    return email if _EMAIL_RE.match(email) else ""


def normaliser_contacts(value) -> list[dict]:
    """Points de contact d'une fiche : au plus MAX_CONTACTS entrées
    {nom, email}, dans l'ordre de saisie.

    Une entrée sans nom NI email est ignorée (ligne de formulaire laissée
    vide). Un email illisible est écarté SANS jeter le nom qui l'accompagne :
    la fiche affiche alors le contact, simplement pas cliquable — mieux qu'une
    ligne disparue en silence.
    """
    if not isinstance(value, list):
        return []
    contacts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        nom = "" if item.get("nom") is None else str(item["nom"]).strip()
        email = normaliser_email(item.get("email"))
        if not nom and not email:
            continue
        contacts.append({"nom": nom, "email": email})
        if len(contacts) >= MAX_CONTACTS:
            break
    return contacts


def _lien_label(url: str) -> str:
    """Libellé affiché d'une URL : sans son schéma, sans son `www.` et sans sa
    barre finale — « geo.example.fr/portail » plutôt que
    « https://geo.example.fr/portail/ ».

    La cellule qui l'accueille fait une demi-mesure de texte : le schéma y
    coûterait une ligne de repli pour une information que personne ne lit,
    l'URL complète restant de toute façon la CIBLE du lien (cf. `lien_projet`,
    passé à part au gabarit).
    """
    label = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    label = re.sub(r"^www\.", "", label)
    return label.rstrip("/")


def _contacts(projet: dict) -> list[dict]:
    """Contacts prêts pour le gabarit. Le NOM passe par _clean (c'est du texte
    composé) ; l'email jamais — les espaces insécables de _typographie n'y
    auraient rien à faire, et c'est aussi la cible du `mailto:`, qui doit
    rester exactement ce qui a été saisi."""
    return [
        {"nom": _clean(c["nom"]), "email": c["email"]}
        for c in normaliser_contacts(projet.get("contacts"))
    ]


def build_projets_data(projets: list[dict], options: dict) -> list[dict]:
    """
    Normalise les projets du registre Drive en structure de rendu.

    projets : projets hydratés (contenu du YAML du registre) enrichis de
              `images_bytes` : [{content: bytes, mimetype: str, legende: str}]
              et `equipe_display` : [{nom: str, role: str}]
    options : chapitres (list[str]), inclure_equipe, inclure_competences,
              inclure_images (bool)
    """
    chapitres_retenus = [k for k in CHAPITRE_ORDER if k in (options.get("chapitres") or [])]
    result = []

    for projet in projets:
        chapitres_src = projet.get("chapitres") or {}
        # Le contexte long vit dans chapitres.contexte_complet ; le contexte
        # court (celui des CV) sert de repli si le long n'est pas rédigé.
        contexte = _clean(chapitres_src.get("contexte_complet")) or _clean(projet.get("contexte"))
        # Normalisé ICI aussi, pas seulement à l'écriture : un registre écrit à
        # la main ou par une version antérieure peut porter une URL sans
        # schéma, dont Typst ferait un lien relatif — annotation présente,
        # cible nulle (constaté sur le rendu).
        lien_projet = normaliser_lien(projet.get("lien_projet"))

        entry = {
            "client": _client_label(projet),
            "designation": _clean(projet.get("designation")),
            "sous_entite": _clean(projet.get("sous_entite")),
            "budget": _budget_label(projet),
            "periode": _clean(projet.get("periode")),
            "secteur": _SECTEUR_LABELS.get(_clean(projet.get("secteur")).lower(), _clean(projet.get("secteur"))),
            # Seconde ligne des éléments clés : contacts d'un côté, projet
            # publié de l'autre. `lien_projet` est la cible du lien (URL
            # entière, telle qu'ingest._as_lien_projet l'a normalisée),
            # `lien_projet_label` ce qui s'affiche — le gabarit ne recompose
            # rien, il pose l'un dans l'autre.
            "lien_projet": lien_projet,
            "lien_projet_label": _lien_label(lien_projet) if lien_projet else "",
            "contacts": _contacts(projet),
            "contexte": contexte,
            "chapitres": [
                {"key": key, "label": CHAPITRE_LABELS[key], "texte": _clean(chapitres_src.get(key))}
                for key in chapitres_retenus
                if _clean(chapitres_src.get(key))
            ],
            "competences": [],
            "equipe": [],
            "images": [],
        }

        if options.get("inclure_competences"):
            entry["competences"] = [_clean(c) for c in (projet.get("competences") or []) if _clean(c)]

        if options.get("inclure_equipe"):
            for m in (projet.get("equipe_display") or []):
                nom = _clean(m.get("nom"))
                if nom:
                    entry["equipe"].append({"nom": nom, "role": _clean(m.get("role"))})

        if options.get("inclure_images"):
            entry["images"] = [
                im for im in (projet.get("images_bytes") or [])
                if im.get("content")
            ]

        # Répartition des visuels : le premier ouvre la fiche en bande pleine
        # largeur, les suivants alimentent les mises en regard des chapitres,
        # le reliquat va dans la grille de visuels de fin.
        entry["visuel_ouverture"] = entry["images"][0] if entry["images"] else None
        restants = _assign_motifs(entry["chapitres"], list(range(1, len(entry["images"]))))
        for ch in entry["chapitres"]:
            idx = ch.pop("image_idx", None)
            ch["image"] = entry["images"][idx] if idx is not None else None
        entry["visuels"] = [entry["images"][i] for i in restants]

        result.append(entry)

    return result


def _periode_couverte(projets_data: list[dict]) -> str:
    """Amplitude des années couvertes par la sélection, pour la couverture."""
    annees = []
    for p in projets_data:
        for token in _clean(p.get("periode")).replace("–", " ").replace("-", " ").split():
            if len(token) == 4 and token.isdigit():
                annees.append(int(token))
    if not annees:
        return ""
    lo, hi = min(annees), max(annees)
    return str(lo) if lo == hi else f"{lo} – {hi}"


# Libellés de repli des deux titres — employés quand les options n'en portent
# pas (appel direct, ou formulaire d'une fiche isolée, qui n'a pas de
# couverture à nommer).
TITRE_DEFAUT = "Références projets"
SOUS_TITRE_DEFAUT = "Camptocamp SA"


def build_cover(projets_data: list[dict], options: dict) -> dict:
    """Lignes de couverture / en-tête, communes aux deux formats.

    `titre` et `sous_titre` sont saisis à la génération (cf. l'endpoint
    /api/portefolio/generate) : le premier nomme le document — grand titre de
    couverture, et mention reprise en pied de page de chaque fiche —, le second
    nomme la sélection.

    `sur_titre`, lui, reste CALCULÉ et non saisi : « 3 projets · 2022 – 2025 »
    est un constat sur le contenu, pas un intitulé. Le rendre modifiable
    permettrait de le mettre en contradiction avec les fiches qui suivent.
    """
    titre = _clean(options.get("titre")) or TITRE_DEFAUT
    sous_titre = _clean(options.get("sous_titre")) or SOUS_TITRE_DEFAUT
    n = len(projets_data)
    periode = _periode_couverte(projets_data)
    resume = f"{n} projet{'s' if n > 1 else ''}"
    if periode:
        resume += f" · {periode}"
    return {
        "titre": titre,
        "sous_titre": sous_titre,
        "sur_titre": resume,
        # Rappel de projet en haut des pages de suite, quand aucun titre de
        # fiche ne précède sur la page — donc le nom du document.
        "label_entete": titre,
    }


# ---------------------------------------------------------------------------
# PDF — Typst
# ---------------------------------------------------------------------------

# --- Boucle de verification -------------------------------------------
# Deux contraintes, verifiees dans cet ordre, chacune avec sa propre sequence
# de repli — ecrite ici et nulle part ailleurs (le gabarit ne fait qu'appliquer
# les valeurs reçues) :
#
#   1. « Environnement » tient sur UNE seule page. Quand l'equipe n'est pas
#      renseignee (donc ni bloc equipe ni bloc competences avant lui), cette
#      page doit etre la PAGE 1. On part des valeurs les plus genereuses de
#      tous les leviers, et on ne resserre qu'au fur et a mesure des echecs.
#   2. Le document tient en 2 pages AU PLUS (1 page est bon aussi). Ne jouent
#      alors que les leviers portant sur ce qui SUIT « Environnement ».
#
# Ce n'est pas une recherche du meilleur reglage parmi tous : c'est une
# sequence conditionnelle, qui s'arrete au premier reglage satisfaisant. Une
# version anterieure explorait chaque levier independamment puis detendait ;
# elle etait a la fois plus couteuse (une compilation par palier de chaque
# echelle) et moins previsible — impossible de dire d'avance ce qui serait
# sacrifie. Cf. render_pdf pour la sequence elle-meme.
#
# Convention : chaque echelle est ordonnee du PLUS GENEREUX au PLUS SERRE, et
# celles que la sequence appelle par « valeur moyenne » comptent exactement
# trois paliers — [0] max, [1] moyenne, [2] min — pour que le code puisse les
# designer sans arithmetique.

# --- Contrainte 1 : « Environnement » sur une seule page ---------------
# Corps de texte des chapitres (pt), par pas de 0.5 jusqu'au plancher.
BODY_SIZE_LADDER_PDF = (9, 8.5, 8)
# Marges internes de l'aplat « Contexte complet du projet » (pt). 20.8 = +30 %
# sur la mesure de reference des aplats (16pt), demande explicite ; 16 = retour
# au traitement des autres chapitres.
PADDING_CHAPEAU_LADDER = (20.8, 18.4, 16)
# Blanc entre le bloc de titre de la fiche et la rangee d'elements cles (pt).
# 45 = marge-haut-page cote gabarit : au nominal, le bloc de titre a donc
# exactement le meme blanc au-dessus (la marge haute de la page) et en dessous
# (ce gap) — demande explicite. Les deux valeurs doivent rester egales.
GAP_TITRE_LADDER = (45, 34, 24)
# Blanc entre le bas du chapitre « Environnement » et la mention (c) +
# pagination (pt). 60 = le quadruple du blanc que le pied de page menage
# lui-meme (gap-standard, ~14.7pt) : double a la premiere demande, redouble a
# la seconde, pour reprendre le blanc qui persistait entre l'image vitrine et
# le chapitre.
MARGE_ENV_BAS_LADDER = (60, 45, 30)
# Plancher de rognage du visuel d'« Environnement », en fraction de sa hauteur
# naturelle (cf. `plancher-visuel-empile` cote gabarit) : [0] pas de rognage
# du tout (leviers 1 a 5 ci-dessus, avant tout recadrage — demande explicite,
# « avant de cropper, diminuer les espaces autour du bloc titre ») ; [1] au
# plus 20 % de rognage ; [2] au plus 30 %, reserve aux paliers les plus denses
# de la sequence (cf. plus bas). Seuils relaches de 10 points par rapport au
# premier reglage (10 %/20 %) — demande explicite.
PLANCHER_VISUEL_LADDER = (1.0, 0.80, 0.70)
# Rognage de l'image "libre" (vitrine, sous le chapeau), en fraction de sa
# hauteur CIBLE nominale (cf. `image-libre-echelle` cote gabarit) : [0] pas de
# rognage ; [1] au plus 30 % ; [2] au plus 40 %, au palier le plus dense.
# Contrairement au visuel d'« Environnement », ce n'etait PAS un levier de la
# sequence jusqu'ici (le gabarit sacrifiait plutot le visuel de cloture) —
# demande explicite de l'introduire ici, dans cette seule sequence. Seuils
# relaches de 10 points par rapport au premier reglage (20 %/30 %) — demande
# explicite.
IMAGE_LIBRE_CROP_LADDER = (1.0, 0.70, 0.60)

# --- Contrainte 2 : 2 pages au plus -----------------------------------
# Facteur sur le blanc entre deux chapitres, par paliers de 10 % de reduction,
# jusqu'a -70 % (demande explicite).
GAP_CHAPITRES_LADDER = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3)
# Marges internes haut/bas de l'aplat de cloture (« Resultats & impact »), en
# pt : elles centrent le contenu du chapitre dans son aplat. Le pied de page
# embarque de ce chapitre ne bouge pas pour autant, il reste cale par l'inset
# BAS de l'aplat (cf. ligne-pied cote gabarit).
MARGE_RESULTATS_LADDER = (40, 32, 24)
# Largeur des visuels mis en regard du texte (« Aspects ergonomiques »,
# « Aspects visuels »), en facteur de leur taille nominale.
#
# Ce cran ne figure PAS dans la sequence demandee : je l'ajoute juste avant le
# dernier repli, parce qu'il vaut mieux retrecir deux visuels que d'en
# supprimer un. Il rend d'ailleurs ce dernier repli inutile sur la fiche la
# plus dense que l'on puisse rediger. A retirer si la sequence doit rester
# strictement celle du cahier des charges.
DUO_SCALE_LADDER = (1.0, 0.9, 0.8)
# Dernier repli, et le seul qui retire du contenu : le chapitre de cloture perd
# son visuel et passe en texte seul.


def _pied_coherent(pdf_bytes: bytes) -> bool:
    """Un pied de page (normal ou embarque) au plus par page — jamais deux.

    Garde-fou contre un defaut Typst signale sur les fiches a redaction
    longue : l'ancrage bas d'« Environnement » (pave-ancre, cf. le gabarit)
    peut, combine a un bloc de qualification (competences/equipe) au-dessus,
    produire un pied de page duplique et une pagination incoherente. La
    mention « Camptocamp | » est presente dans les DEUX variantes du pied
    (running-footer et ligne-pied embarquee) : plus d'une occurrence sur une
    meme page signe ce defaut, jamais un cas legitime."""
    import fitz
    with fitz.open(stream=pdf_bytes, filetype="pdf") as f:
        return all(page.get_text().count("Camptocamp |") <= 1 for page in f)


def render_pdf(projets_data: list[dict], options: dict, annee: str = "") -> bytes:
    """
    Produit la fiche d'un projet, ou le document d'un lot (couverture + index +
    une fiche par projet).

    Un lot n'est PAS compilé d'un seul tenant : chaque projet est composé seul,
    avec ses propres leviers de remplissage (cf. `converger`), puis les
    fragments sont assemblés (cf. `_assembler`). C'est la seule façon de tenir
    la règle « un projet rend pareil seul et en lot » — des leviers communs à
    tout le document faisaient payer à chaque projet la densité du plus chargé.

    Le répertoire de build est créé SOUS engine/ : Typst refuse tout chemin
    hors de son `root`, donc les images doivent y être matérialisées — une
    seule fois, puis réutilisées par toutes les compilations (seuls les leviers
    de mise en page et la pagination changent d'un essai à l'autre).
    """
    import typst

    if not projets_data:
        raise ValueError("Aucun projet à rendre.")

    build_dir = ENGINE_DIR / f".build_ref_{uuid.uuid4().hex[:8]}"
    img_dir = build_dir / "img"
    try:
        img_dir.mkdir(parents=True, exist_ok=True)

        compteur = [0]

        def ecrire(content: bytes, mimetype: str) -> str:
            """Écrit des octets sous engine/ et retourne leur chemin, relatif au
            root Typst, pour le gabarit."""
            compteur[0] += 1
            ext = _EXT_BY_MIME.get(mimetype, ".png")
            name = f"im{compteur[0]}{ext}"
            (img_dir / name).write_bytes(content)
            return f"{build_dir.name}/img/{name}"

        def materialiser(im: dict | None, slot: str) -> dict | None:
            """Un fichier, rééchantillonné à la taille de son emplacement (cf.
            normaliser_image / RENDER_DPI). Tous les RECADRAGES (mise en regard
            4:3, image vitrine 911x370, visuel de « Environnement » ajusté à la
            place restante) restent faits par le gabarit, à la géométrie
            exacte : seule la définition est traitée ici, jamais le cadrage.

            `slot` est la clé du chapitre qui porte l'image, ou "" pour l'image
            libre — c'est elle qui donne la largeur rendue."""
            if not im:
                return None
            content, mimetype = normaliser_image(
                im["content"], im.get("mimetype", ""), slot
            )
            return {
                "fichier": ecrire(content, mimetype),
                "legende": _clean(im.get("legende")),
            }

        projets_yaml = []
        # Fanion de mise en page de la page 1, relevé projet par projet pendant
        # la construction des blocs plutôt que recalculé plus bas : la règle qui
        # le décide vit dans _reshape_chapitres_pdf, et nulle part ailleurs.
        ouverture_aeree_par_projet: list[bool] = []
        for idx, p in enumerate(projets_data):
            # Plus de visuel d'ouverture pleine largeur en PDF (economie d'une
            # page demandee) : chaque image est desormais rattachee a un
            # chapitre precis par l'interface de saisie, ou libre (cf.
            # _reshape_chapitres_pdf) — plus de pool ni de galerie de fin.
            entry = {k: v for k, v in p.items() if k not in ("images", "chapitres", "visuels", "visuel_ouverture")}
            # Numero affiche dans le bloc de titre : la position REELLE dans le
            # lot, pas l'index local au fragment (toujours 0, chaque projet
            # etant compile seul — cf. render_pdf). Sans cette cle, un lot de
            # plusieurs projets affichait "01" sur chacun (bug signale).
            entry["numero"] = idx + 1
            blocs = _reshape_chapitres_pdf(p)
            ouverture_aeree_par_projet.append(
                any(bl.get("ouverture_aeree") for bl in blocs)
            )
            blocs_pdf = []
            for bl in blocs:
                if bl["type"] == "image_libre":
                    # Tout le bloc est recopie (`**bl`), pas seulement son type :
                    # il porte aussi `sous_contexte`, que le gabarit lit pour
                    # savoir s'il doit superposer le chapeau a cette image
                    # (cf. chapeau-sur-image). Une premiere version reconstruisait
                    # un dict a deux cles et perdait ce fanion en silence — la
                    # superposition ne se produisait jamais.
                    blocs_pdf.append({**bl, "image": materialiser(bl["image"], "")})
                    continue
                images = [
                    {**materialiser(im, bl.get("key", "")), "bleed": im.get("bleed", False)}
                    for im in bl.get("images", [])
                ]
                blocs_pdf.append({**{k: v for k, v in bl.items() if k != "images"}, "images": images})
            entry["blocs"] = blocs_pdf
            projets_yaml.append(entry)

        cover = build_cover(projets_data, options)
        doc_commun = {
            **cover,
            # Mention du pied de page : « © Camptocamp | 2026 | <document> ».
            # C'est le nom du document, donc son titre — fige a « Références
            # projets », il contredisait la couverture des le titre change.
            "document_name": cover["titre"],
            "annee": annee,
        }

        def compiler(doc: dict) -> bytes:
            """Compile UN fragment — un projet, ou la couverture seule."""
            data_file = build_dir / "data.yaml"
            data_file.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
            with tempfile.TemporaryDirectory() as tmpdir:
                out = Path(tmpdir) / "references.pdf"
                typst.compile(
                    str(TEMPLATE),
                    output=str(out),
                    root=str(ENGINE_DIR),
                    font_paths=[str(ASSETS)],
                    sys_inputs={"data": f"{build_dir.name}/data.yaml"},
                )
                return out.read_bytes()

        def converger(projet: dict, entry: dict, ouverture_aeree: bool) -> tuple[bytes, dict, int]:
            """Boucle de vérification pour UN projet, composé seul.

            Retourne (pdf du fragment, leviers retenus, nombre de pages).

            Composé seul, et non au sein du lot : les leviers sont propres au
            projet. Un lot les partageait, si bien que le projet le plus dense
            imposait ses réductions à tous les autres — et comme la contrainte
            « 2 pages » y était comprise comme « 2 pages pour tout le document »,
            un lot de trois projets la déclarait perdue d'avance et déroulait
            toute la séquence de repli, jusqu'à retirer le visuel de clôture de
            chaque projet (bug signalé : « le rendu multiprojets casse les
            projets »).
            """
            nom = entry.get("designation") or entry.get("client") or "projet"

            def essayer(desactiver_ancre: bool) -> tuple[bytes, dict, int]:
                """Un passage complet des deux contraintes. `desactiver_ancre`
                coupe l'ancrage bas d'« Environnement » (cf. le garde-fou plus
                bas, et `desactiver-ancre-environnement` cote gabarit)."""
                return _converger_un_passage(
                    projet, entry, ouverture_aeree, nom, desactiver_ancre,
                    doc_commun, compiler,
                )

            pdf, reglages, pages = essayer(False)
            if not _pied_coherent(pdf):
                print(
                    f"[render_pdf] AVERTISSEMENT : {nom} — pied de page duplique / "
                    "pagination incoherente detectee (defaut Typst lie a l'ancrage bas "
                    "d'Environnement, cf. m-stack/pave-ancre) ; nouvel essai avec cet "
                    "ancrage desactive.",
                    flush=True,
                )
                pdf2, reglages2, pages2 = essayer(True)
                if _pied_coherent(pdf2):
                    return pdf2, reglages2, pages2
                print(
                    f"[render_pdf] AVERTISSEMENT : {nom} — le defaut persiste meme "
                    "ancrage desactive ; conservation du premier rendu.",
                    flush=True,
                )
            return pdf, reglages, pages

        # --- Un fragment par projet, chacun avec ses propres leviers --------
        fragments = [
            converger(p, entry, aeree)
            for p, entry, aeree in zip(projets_data, projets_yaml, ouverture_aeree_par_projet)
        ]

        # Projet unique : le fragment EST le document (ni couverture ni index).
        if len(fragments) == 1:
            return fragments[0][0]

        return _assembler(fragments, projets_yaml, doc_commun, compiler)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)


def _converger_un_passage(
    projet: dict, entry: dict, ouverture_aeree: bool, nom: str,
    desactiver_ancre_environnement: bool, doc_commun: dict, compiler,
) -> tuple[bytes, dict, int]:
    """Un passage complet de la boucle de verification (contraintes 1 puis 2)
    pour UN projet, a `desactiver_ancre_environnement` fixe. Extrait de
    `converger` pour pouvoir en rejouer un second passage — avec l'ancrage
    desactive — sans dupliquer toute la sequence de repli (cf. son appelant).
    """
    # --- Ce que la page 1 doit porter -----------------------------
    # Cas A — « Environnement » doit tenir en page 1. Ne s'applique que
    # si son bloc n'est pas precede du bloc equipe/competences (equipe
    # non renseignee) ET, evidemment, que le chapitre est redige : sans
    # cette seconde condition, une fiche sans « Environnement » ne
    # pouvait jamais satisfaire le controle (le texte cherche n'existait
    # nulle part), et TOUTE la sequence de repli se deroulait pour rien.
    # Le seul critere est que le chapitre soit REDIGE. Il a longtemps
    # ete conditionne a l'absence d'equipe (puis de qualification), au
    # motif que la place n'y serait plus sinon — mais la place, c'est
    # justement ce que la sequence de repli fabrique, jusqu'a rogner le
    # visuel du chapitre. « Environnement » en page 1 est une
    # obligation, pas une preference : demande explicite (« il est
    # obligatoire qu'il reste en P1, c'est la premiere contrainte de la
    # boucle de verification »).
    env_check_needed = any(
        c["key"] == "environnement" for c in (projet.get("chapitres") or [])
    )
    # Cas B — « ouverture aeree » : l'image libre ferme la page 1, aucun
    # chapitre ne doit s'y trouver (cf. _reshape_chapitres_pdf et
    # image-libre-ouverture cote gabarit). Le gabarit renonce de lui-meme
    # au saut de page quand le pave ne tient pas ; c'est ce renoncement
    # que ce controle detecte, pour que la sequence resserre l'amont.
    labels_chapitres = [c["label"] for c in (projet.get("chapitres") or [])]

    def mesurer(pdf_bytes: bytes) -> tuple[int, bool, bool]:
        """(nombre de pages, la page 1 porte-t-elle ce qu'elle doit, pied de
        page coherent)."""
        import fitz
        with fitz.open(stream=pdf_bytes, filetype="pdf") as f:
            n = f.page_count
            page1_ok = True
            if env_check_needed:
                page1_ok = False
                for page in f:
                    if page.search_for("Environnement"):
                        page1_ok = page.number == 0
                        break
            elif ouverture_aeree:
                page1_ok = not any(
                    f[0].search_for(label) for label in labels_chapitres
                )
        return n, page1_ok, _pied_coherent(pdf_bytes)

    # Etat courant des leviers : on part du reglage le plus genereux de
    # chacun, et la sequence de repli est CUMULATIVE — chaque etape
    # conserve les reductions consenties par les precedentes.
    reglages = {
        "corps_size": BODY_SIZE_LADDER_PDF[0],
        "padding_chapeau": PADDING_CHAPEAU_LADDER[0],
        "gap_titre": GAP_TITRE_LADDER[0],
        "marge_env_bas": MARGE_ENV_BAS_LADDER[0],
        "plancher_visuel_empile": PLANCHER_VISUEL_LADDER[0],
        "echelle_gap_chapitres": GAP_CHAPITRES_LADDER[0],
        "marge_resultats": MARGE_RESULTATS_LADDER[0],
        "echelle_duo": DUO_SCALE_LADDER[0],
        "sans_image_resultats": False,
        "desactiver_ancre_environnement": desactiver_ancre_environnement,
        "image_libre_echelle": IMAGE_LIBRE_CROP_LADDER[0],
        "environnement_full_pied": False,
        "masquer_image_libre": False,
    }
    etat: dict = {}

    def tenter(etape: str, **maj) -> tuple[int, bool]:
        """Applique `maj`, compile, mesure, journalise. Retourne (pages,
        conforme) — `conforme` exige a la fois que la page 1 porte ce qu'elle
        doit ET que le pied de page soit coherent (cf. mesurer / _pied_coherent).

        Fusionner les deux ICI, plutot que de ne verifier le pied qu'une fois
        la sequence entiere terminee (comme le fait `converger`), est ce qui
        donne enfin une chance a la sequence de repli (rognage, collage au
        pied) d'echapper elle-meme au defaut Typst lie a l'ancrage bas —
        auparavant, un « essai nominal » deja abime par ce defaut mais
        satisfaisant page1_ok en apparence stoppait la sequence avant meme
        qu'elle commence, et tout le repli (rognage inclus) restait lettre
        morte (bug signale : la sequence saute directement au retrait de
        l'image libre, quel que soit le plafond de rognage)."""
        reglages.update(maj)
        pdf = compiler({**doc_commun, "projets": [entry], **reglages})
        n, page1_ok, pied_ok = mesurer(pdf)
        conforme = page1_ok and pied_ok
        etat.update(pdf=pdf, pages=n, page1_ok=page1_ok, pied_ok=pied_ok, conforme=conforme)
        print(
            f"[render_pdf] {nom} — {etape} : {reglages} -> {n} page(s), "
            f"page 1 conforme = {page1_ok}, pied coherent = {pied_ok}",
            flush=True,
        )
        return n, conforme

    # === Contrainte 1 — la page 1 porte ce qu'elle doit ===============
    # Tous les leviers au plus genereux : c'est le reglage voulu, les
    # suivants ne sont que des replis. Deux sequences distinctes, selon
    # ce que la page 1 doit porter (cf. `mesurer`) — jamais un melange
    # des deux : les leviers qui sauvent l'une defont ce que l'autre
    # cherche.
    pages, page1_ok = tenter("essai nominal")

    if not page1_ok and ouverture_aeree:
        # --- Sequence « ouverture aeree » ----------------------------
        # Le gabarit a renonce au saut de page : le pave image ne tenait
        # pas dans ce qui restait sous le contexte. Trois leviers
        # agissent sur cette hauteur — les blancs du bloc de titre,
        # le corps de texte, et les marges internes du chapeau.
        #
        # `gap_titre` etait DELIBEREMENT exclu de cette sequence : les
        # blancs qui entourent le bloc de titre — et celui, egal, qui
        # separe la qualification du contexte — sont precisement ce que
        # cette mise en page cherche a offrir, et les rogner revenait a
        # defaire le resultat vise. Demande explicite de revenir
        # dessus : « il semble pouvoir y avoir la place d'integrer
        # l'image libre en reduisant ces espacements autour du bloc
        # titre ». Mieux vaut en effet un titre moins aere qu'un visuel
        # que le lecteur ne voit pas du tout.
        #
        # Il passe meme en PREMIER, avant le corps de texte : c'est le
        # levier le plus LOCAL des trois. Il ne deplace que la page 1,
        # la ou `corps_size` refait couler le texte de la fiche
        # entiere, chapitres compris — payer la page 1 avec la
        # typographie des pages suivantes est le plus mauvais des
        # echanges. Il rapporte deux fois sa valeur (45 -> 24 pt libere
        # ~42 pt) : il s'applique sous le bloc de titre ET au-dessus du
        # chapeau (cf. `gap-chapeau` cote gabarit).
        #
        # `marge_env_bas` reste absent, pour une raison plus simple :
        # il n'y a pas de chapitre « Environnement » en page 1 dans ce
        # cas de figure, ce levier ne pousse rien.
        for gap in GAP_TITRE_LADDER[1:]:
            if page1_ok:
                break
            pages, page1_ok = tenter(
                "page 1 aeree / repli 1 (blancs du bloc de titre)", gap_titre=gap
            )

        for taille in BODY_SIZE_LADDER_PDF[1:]:
            if page1_ok:
                break
            pages, page1_ok = tenter(
                "page 1 aeree / repli 2 (corps de texte)", corps_size=taille
            )

        for padding in PADDING_CHAPEAU_LADDER[1:]:
            if page1_ok:
                break
            pages, page1_ok = tenter(
                "page 1 aeree / repli 3 (padding chapeau)", padding_chapeau=padding
            )

        if not page1_ok:
            print(
                f"[render_pdf] AVERTISSEMENT : {nom} — la page 1 ne peut pas se "
                "fermer sur l'image libre meme blancs, corps et paddings au "
                "minimum : contexte complet trop long. Le premier chapitre "
                "reste en page 1.",
                flush=True,
            )

    elif not page1_ok:
        # --- Sequence « Environnement en page 1 » --------------------
        # Repli 1 — le corps de texte, par pas de 0.5 jusqu'au plancher.
        for taille in BODY_SIZE_LADDER_PDF[1:]:
            pages, page1_ok = tenter("repli 1 (corps de texte)", corps_size=taille)
            if page1_ok:
                break

        if not page1_ok:
            # Repli 2 — le padding du chapeau, a sa valeur moyenne.
            pages, page1_ok = tenter(
                "repli 2 (padding chapeau moyen)",
                padding_chapeau=PADDING_CHAPEAU_LADDER[1],
            )

        if not page1_ok:
            # Repli 3 — les deux espacements, a leurs valeurs moyennes
            # (le padding moyen et le corps minimum sont conserves).
            pages, page1_ok = tenter(
                "repli 3 (espacements moyens)",
                gap_titre=GAP_TITRE_LADDER[1],
                marge_env_bas=MARGE_ENV_BAS_LADDER[1],
            )

        if not page1_ok:
            # Repli 4 — le padding du chapeau, a son minimum.
            pages, page1_ok = tenter(
                "repli 4 (padding chapeau minimum)",
                padding_chapeau=PADDING_CHAPEAU_LADDER[2],
            )

        if not page1_ok:
            # Repli 5 — tout au minimum. Dernier cran de la sequence.
            pages, page1_ok = tenter(
                "repli 5 (tout au minimum)",
                corps_size=BODY_SIZE_LADDER_PDF[-1],
                gap_titre=GAP_TITRE_LADDER[-1],
                marge_env_bas=MARGE_ENV_BAS_LADDER[-1],
                padding_chapeau=PADDING_CHAPEAU_LADDER[-1],
            )

        # Repli 6 — l'image "libre" (vitrine) se rogne, jusqu'a 30 % de sa
        # hauteur. Avant tout rognage du visuel d'« Environnement » lui-meme
        # (demande explicite : « commencer par cropper l'image libre »).
        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 6 (image libre rognee a 30%)",
                image_libre_echelle=IMAGE_LIBRE_CROP_LADDER[1],
            )

        # Repli 7 — le visuel d'« Environnement » se rogne a son tour, jusqu'a
        # 20 % de sa hauteur (cf. PLANCHER_VISUEL_LADDER). L'image libre reste
        # au repli precedent (cumulatif).
        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 7 (visuel Environnement rogne a 20%)",
                plancher_visuel_empile=PLANCHER_VISUEL_LADDER[1],
            )

        # Repli 8 — le rognage des deux visuels ne suffit pas : on y renonce
        # entierement et on colle plutot le bloc « Environnement » au bord bas
        # REEL de la page (comme le chapitre de cloture), quitte a recouvrir
        # le pied de page normal sur cette page-la — demande explicite : « tu
        # n'appliques plus d'espaces entre le bloc environnement et le pied de
        # page, tu colles ce bloc au pied de page du doc ».
        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 8 (Environnement colle au pied de page reel)",
                image_libre_echelle=IMAGE_LIBRE_CROP_LADDER[0],
                plancher_visuel_empile=PLANCHER_VISUEL_LADDER[0],
                environnement_full_pied=True,
            )

        # Repli 9 a 12 — dans cet etat « colle au pied », on reprend la meme
        # sequence de rognage (libre 30 %, Environnement 20 %), puis on pousse
        # chacun d'un cran de plus (libre 40 %, Environnement 30 %) : la place
        # gagnee en collant au bord reel change ce que chaque palier permet de
        # montrer. Cas le plus dense avec image, demande explicite : espaces
        # du bloc titre au minimum, libre a 40 % de rognage max, Environnement
        # a 30 % max.
        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 9 (colle au pied + image libre rognee a 30%)",
                image_libre_echelle=IMAGE_LIBRE_CROP_LADDER[1],
            )

        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 10 (colle au pied + visuel Environnement rogne a 20%)",
                plancher_visuel_empile=PLANCHER_VISUEL_LADDER[1],
            )

        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 11 (colle au pied + image libre rognee a 40%)",
                image_libre_echelle=IMAGE_LIBRE_CROP_LADDER[2],
            )

        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 12 (colle au pied + visuel Environnement rogne a 30%)",
                plancher_visuel_empile=PLANCHER_VISUEL_LADDER[2],
            )

        # Repli 13 — meme le palier le plus dense ne suffit pas : on revient
        # aux reglages initiaux (espaces du bloc titre, aucun rognage, plus de
        # collage au pied) MAIS on renonce a l'image libre elle-meme — dernier
        # repli qui retire du contenu plutot que de comprimer davantage,
        # demande explicite.
        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 13 (image libre retiree)",
                gap_titre=GAP_TITRE_LADDER[0],
                marge_env_bas=MARGE_ENV_BAS_LADDER[0],
                padding_chapeau=PADDING_CHAPEAU_LADDER[0],
                corps_size=BODY_SIZE_LADDER_PDF[0],
                image_libre_echelle=IMAGE_LIBRE_CROP_LADDER[0],
                plancher_visuel_empile=PLANCHER_VISUEL_LADDER[0],
                environnement_full_pied=False,
                masquer_image_libre=True,
            )

        # Repli 14 — sans l'image libre, on colle a nouveau Environnement au
        # pied de page reel.
        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 14 (sans image libre, colle au pied)",
                environnement_full_pied=True,
            )

        # Repli 15/16 — et si besoin, on rogne le visuel d'« Environnement »
        # selon les memes paliers qu'aux replis 7 et 12 (l'image libre n'a
        # plus lieu d'etre rognee, elle n'est plus affichee).
        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 15 (sans image libre, colle au pied, Environnement rogne a 20%)",
                plancher_visuel_empile=PLANCHER_VISUEL_LADDER[1],
            )

        if not page1_ok:
            pages, page1_ok = tenter(
                "repli 16 (sans image libre, colle au pied, Environnement rogne a 30%)",
                plancher_visuel_empile=PLANCHER_VISUEL_LADDER[2],
            )

        if not page1_ok:
            # Plus aucun repli de la sequence : ce n'est plus une question de
            # place a gagner en page 1, c'est le contenu en amont qui est trop
            # long. Signale plutot que masque ; le fragment est produit avec
            # le reglage le plus serre.
            print(
                f"[render_pdf] AVERTISSEMENT : {nom} — « Environnement » ne tient "
                "pas en page 1 meme tous les replis epuises (espaces au minimum, "
                "image libre rognee puis retiree, Environnement colle au pied de "
                "page et rogne a 30%) : contenu trop long en amont.",
                flush=True,
            )

    # Rendu retenu par la contrainte 1, mis de cote AVANT d'engager la
    # compression : c'est le plus genereux qui satisfasse la page 1, et
    # donc celui sur lequel revenir si la contrainte 2 s'avere hors
    # d'atteinte (cf. le dernier repli).
    reglages_page1 = dict(reglages)
    pdf_page1, pages_page1 = etat["pdf"], etat["pages"]

    # === Contrainte 2 — 2 pages au plus PAR PROJET ====================
    # « Par projet », et non pour le document : c'est la fiche qui doit
    # tenir en deux pages, un lot de N projets en fait naturellement 2N.
    # N'agit que sur ce qui SUIT « Environnement » : les blancs entre
    # chapitres, puis l'aplat de cloture, puis son visuel.
    if pages > 2:
        # Repli 1 — les blancs entre chapitres, par paliers de 10 %.
        for facteur in GAP_CHAPITRES_LADDER[1:]:
            pages, _ = tenter(
                "2 pages / repli 1 (blancs entre chapitres)",
                echelle_gap_chapitres=facteur,
            )
            if pages <= 2:
                break

    if pages > 2:
        # Repli 2 — marges de l'aplat de cloture, valeur moyenne.
        pages, _ = tenter(
            "2 pages / repli 2 (marges cloture moyennes)",
            marge_resultats=MARGE_RESULTATS_LADDER[1],
        )

    if pages > 2:
        # Repli 3 — marges de l'aplat de cloture, minimum.
        pages, _ = tenter(
            "2 pages / repli 3 (marges cloture minimum)",
            marge_resultats=MARGE_RESULTATS_LADDER[2],
        )

    if pages > 2:
        # Repli 4 — retrecir les visuels mis en regard, par paliers.
        # Hors cahier des charges (cf. DUO_SCALE_LADDER) : retrecir deux
        # visuels vaut mieux que d'en supprimer un.
        for facteur in DUO_SCALE_LADDER[1:]:
            pages, _ = tenter(
                "2 pages / repli 4 (visuels en regard retrecis)",
                echelle_duo=facteur,
            )
            if pages <= 2:
                break

    if pages > 2:
        # Repli 5 — le chapitre de cloture perd son visuel. Seul repli de
        # toute la sequence qui retire du contenu, d'ou son rang.
        pages, _ = tenter(
            "2 pages / repli 5 (cloture sans visuel)",
            sans_image_resultats=True,
        )

    if pages > 2:
        # Aucun palier n'a ramene la fiche a deux pages : toute la
        # compression consentie n'a donc RIEN achete — la fiche etait
        # resserree au maximum (blancs entre chapitres a -70 %, aplat de
        # cloture aux marges minimales, visuels en regard retrecis, et
        # jusqu'au visuel de cloture supprime) et faisait quand meme
        # trois pages. Le pire des deux mondes : on revient au rendu de
        # la contrainte 1, le plus genereux qui tienne la page 1.
        # Le nombre de pages est le meme, autant qu'elles soient belles ;
        # c'est a la redaction de raccourcir, et l'avertissement le dit.
        reglages.update(reglages_page1)
        etat.update(pdf=pdf_page1, pages=pages_page1)
        pages = pages_page1
        print(
            f"[render_pdf] AVERTISSEMENT : {nom} — {pages} pages hors d'atteinte "
            "des replis : contenu a raccourcir a la redaction. Retour au rendu "
            "non compresse (la compression ne faisait pas gagner de page).",
            flush=True,
        )

    print(f"[render_pdf] RETENU {nom} : {reglages} -> {etat['pages']} page(s)", flush=True)
    return etat["pdf"], dict(reglages), etat["pages"]


def _titre_index(entry: dict) -> str:
    """Intitulé d'un projet dans l'index de couverture — la même composition
    que le titre de sa fiche (cf. l'ancre `heading` côté gabarit)."""
    client = entry.get("client", "")
    design = entry.get("designation", "")
    if client and design:
        return f"{client} — {design}"
    return client or design


def _assembler(fragments, projets_yaml, doc_commun, compiler) -> bytes:
    """Couverture + un fragment par projet, assemblés en un seul PDF.

    Le document n'est pas compilé d'un tenant : chaque projet l'a été seul,
    avec ses propres leviers de remplissage (cf. `converger`). Il ne reste ici
    qu'à composer la couverture — dont l'index annonce les pages du document
    ASSEMBLÉ — puis à recompiler chaque fragment avec sa pagination définitive
    et à les concaténer.

    La recompilation ne change que le texte du pied de page (« 3 / 8 » au lieu
    de « 1 / 2 ») : celui-ci vit dans la marge, il ne peut pas déplacer le
    contenu. Le contrôle plus bas le vérifie plutôt que de le supposer.
    """
    import fitz

    pages_par_projet = [f[2] for f in fragments]

    # L'index annonce les pages de départ, qui dépendent de la longueur de la
    # couverture, qui dépend de l'index : point fixe, atteint en un tour dès la
    # deuxième itération (une couverture ne change plus de longueur une fois
    # ses entrées connues).
    pages_couverture = 1
    couverture = b""
    for _ in range(3):
        depart, courant = [], pages_couverture + 1
        for n in pages_par_projet:
            depart.append(courant)
            courant += n
        total = courant - 1
        couverture = compiler({
            **doc_commun,
            "projets": [],
            "page_total": total,
            "index": [
                {"titre": _titre_index(e), "page": d}
                for e, d in zip(projets_yaml, depart)
            ],
        })
        with fitz.open(stream=couverture, filetype="pdf") as f:
            n_couv = f.page_count
        if n_couv == pages_couverture:
            break
        pages_couverture = n_couv
    else:
        print(
            "[render_pdf] AVERTISSEMENT : la longueur de la couverture n'est pas "
            "stable ; les pages annoncées par l'index peuvent être décalées.",
            flush=True,
        )

    doc = fitz.open(stream=couverture, filetype="pdf")
    signets = []
    for (_, reglages, n), entry, debut in zip(fragments, projets_yaml, depart):
        fragment = compiler({
            **doc_commun,
            "projets": [entry],
            **reglages,
            "page_offset": debut - 1,
            "page_total": total,
        })
        with fitz.open(stream=fragment, filetype="pdf") as f:
            if f.page_count != n:
                # La pagination ne peut pas déplacer le contenu : si le compte
                # change, c'est que quelque chose d'autre a bougé. On le dit
                # plutôt que de livrer un index qui pointe à côté.
                print(
                    f"[render_pdf] AVERTISSEMENT : {_titre_index(entry)} — {f.page_count} "
                    f"page(s) une fois paginé contre {n} à la composition ; l'index de "
                    "couverture peut être décalé.",
                    flush=True,
                )
            doc.insert_pdf(f)
        signets.append([1, _titre_index(entry), debut])

    doc.set_toc(signets)
    # `garbage=4` : chaque fragment embarque son propre sous-ensemble de polices,
    # identique d'un fragment à l'autre — la déduplication des objets ramène le
    # document à la taille d'une compilation unique.
    assemble = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return assemble


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

def render_pptx(projets_data: list[dict], options: dict) -> bytes:
    from app import reference_pptx
    return reference_pptx.render(projets_data, build_cover(projets_data, options))
