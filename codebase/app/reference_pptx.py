"""
Rendu PPTX des références projets — charte slides Camptocamp.

PARTI PRIS GRAPHIQUE — identique au gabarit PDF : la grille modulaire en aplats
francs, jouée sur des mesures variables. Rien n'est encadré ni souligné ; tout
se lit en blocs pleins posés sur du blanc. Déclinaisons :
  · numéro de projet en gros chiffre orange — ancrage à surface minime
  · faits du projet en cellules modulaires juxtaposées
  · technologies en grille de tuiles de largeur égale
  · chapitres numérotés par pastille carrée orange
  · un seul bloc focus par projet : bord gauche orange sur les résultats
  · équipe en pastilles d'initiales grises

RYTHME DE COMPOSITION — aucun chapitre n'a la mesure de son voisin. Chacun porte
un `motif` décidé en amont par reference_renderer.py, donc le PDF et le PPTX se
lisent au même rythme. Les blocs pleine largeur (deux colonnes, bande grise
débordante, mise en regard d'un visuel) alternent avec des demi-largeurs calées
à gauche ou à droite, et le bloc focus ferme la fiche sur une mesure réduite.
Le placement passe par un flux à deux curseurs de colonne (cf. `_flow`) : un
bloc pleine largeur les remet au même niveau, un bloc de demi-largeur s'empile
dans sa colonne et bascule dans l'autre si la sienne est pleine.

Codes de charte appliqués (c2c-brand-master / c2c-brand-designer) :
  fond #FFFFFF sur toutes les slides · Inter (embarquée en post-traitement)
  bandeau orange plein de 0,10" en BAS de chaque slide, même position partout
  logo Camptocamp inséré en image, haut-gauche, sur fond blanc uni
  angles droits, zéro ombre (le `<p:style>` de thème est retiré), zéro dégradé
  deux couleurs actives : orange #FF680A + gris #7A7F82 · blocs sur #F5F5F5
  sentence case · puces natives · photo montagne réservée à la slide de titre

Structure : 1 slide de titre, puis par projet
  1 slide d'ouverture — identité, faits, contexte, technologies, visuel, équipe
  1 slide de chapitres (2 si la sélection est volumineuse)

Aucun texte ne peut déborder : il est mesuré aux métriques réelles d'Inter et
l'interligne est posé en points absolus. La taille de corps retenue est la plus
grande du barème parmi celles qui donnent le nombre de slides minimal.
"""
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ASSETS = Path(__file__).parent.parent / "engine" / "assets"

# --- Jetons de marque (palette exhaustive autorisée) ------------------
ORANGE = RGBColor(0xFF, 0x68, 0x0A)
GREY = RGBColor(0x7A, 0x7F, 0x82)
INK = RGBColor(0x1A, 0x1A, 0x1A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TINT = RGBColor(0xF5, 0xF5, 0xF5)

FONT = "Inter"

# --- Grille de composition (16:9) ------------------------------------
SLIDE_W = 13.333
SLIDE_H = 7.5
MARGIN_X = 0.75
BANNER_H = 0.10           # ancrage identitaire : 6–10 px, jamais plus épais
LOGO_W = 1.35
LOGO_Y = 0.40
CONTENT_BOTTOM = 7.02     # limite basse du contenu (au-dessus du bandeau)

COL_GUTTER = 0.60
COL_W = (SLIDE_W - 2 * MARGIN_X - COL_GUTTER) / 2

# Slides de chapitres : la pastille numérotée occupe une gouttière fixe.
CHAP_TOP = 1.66
PASTILLE = 0.20
PASTILLE_GAP = 0.14
CHAP_TEXT_W = COL_W - PASTILLE - PASTILLE_GAP
FOCUS_RULE_W = 0.035      # bord gauche orange du bloc focus
FOCUS_INSET = 0.16
DUO_IMG_H = 2.40          # hauteur max du visuel mis en regard d'un chapitre
APLAT_PAD = 0.22          # respiration interne de la bande grise, haut et bas

# --- Typographie (hiérarchie master §2) ------------------------------
SIZE_TITLE = 22
SIZE_SUBTITLE = 18
SIZE_NUM = 54             # gros chiffre d'ancrage
SIZE_CLIENT = 22
SIZE_DESIGNATION = 13
SIZE_HEADING = 11
SIZE_LABEL = 6.5          # libellé de cellule de faits, en capitales
SIZE_TILE = 8.5
SIZE_CAPTION = 8

BODY_SIZE_LADDER = (10, 9.5, 9, 8.5, 8)
# Interligne en points absolus (spcPts) et non en pourcentage : le pourcentage
# est relatif à la hauteur de ligne intrinsèque de la fonte, qui varie d'un
# moteur de rendu à l'autre — la mesure ne correspondrait plus au rendu.
LINE_FACTOR = 1.35
HEADING_BLOCK_H = 0.28    # titre de chapitre + son espace inférieur
CHAPTER_GAP = 0.18


# ---------------------------------------------------------------------------
# Mesure de texte — métriques réelles d'Inter, pour interdire tout débordement
# ---------------------------------------------------------------------------

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_SPLIT_ESPACES = re.compile(r"[ \t\r\f\v]+")   # ne coupe pas sur l'insécable


def _pil_font(weight: str, size_pt: float) -> ImageFont.FreeTypeFont:
    px = max(1, int(round(size_pt * 96 / 72)))
    key = (weight, px)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(ASSETS / f"Inter-{weight}.ttf"), px)
    return _font_cache[key]


def _wrap(text: str, size_pt: float, width_in: float, weight: str = "Regular") -> list[str]:
    font = _pil_font(weight, size_pt)
    max_px = width_in * 96
    lines: list[str] = []
    for raw in text.split("\n"):
        cur = ""
        # Découpe sur les espaces sécables uniquement : `str.split()` couperait
        # aussi sur les insécables posées par reference_renderer._typographie,
        # et la mesure ne correspondrait plus au rendu de PowerPoint.
        for word in _SPLIT_ESPACES.split(raw.strip()):
            if not word:
                continue
            trial = f"{cur} {word}".strip()
            if not cur or font.getlength(trial) <= max_px:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _line_h(size_pt: float) -> float:
    return size_pt * LINE_FACTOR / 72


def _text_height(text: str, size_pt: float, width_in: float, weight: str = "Regular") -> float:
    if not text:
        return 0.0
    return len(_wrap(text, size_pt, width_in, weight)) * _line_h(size_pt)


def _split_at_lines(text: str, size_pt: float, width_in: float, n_lines: int) -> tuple[str, str]:
    """Coupe le texte après `n_lines` lignes rendues, sur une frontière de mot."""
    lines = _wrap(text, size_pt, width_in)
    return " ".join(lines[:n_lines]), " ".join(lines[n_lines:])


def _text_width(text: str, size_pt: float, weight: str = "Regular") -> float:
    return _pil_font(weight, size_pt).getlength(text) / 96


# ---------------------------------------------------------------------------
# Pagination des chapitres en colonnes (garantit l'absence de débordement)
# ---------------------------------------------------------------------------

def _bloc_geom(ch: dict, size: float) -> dict:
    """
    Géométrie du bloc d'un chapitre selon son motif : largeur occupée, colonne
    d'ancrage, et hauteur totale. Le motif vient de reference_renderer.py — les
    deux formats partagent donc le même rythme de composition.

    `span` vaut 2 pour un bloc pleine largeur (il repart d'une ligne propre) et
    1 pour un bloc de demi-largeur, qui s'empile dans sa colonne.
    """
    motif = ch.get("motif") or "demi-gauche"
    im = ch.get("image")
    if motif in ("duo", "duo-inverse") and not im:
        motif = "demi-gauche"

    if motif in ("colonnes", "aplat"):
        # Texte réparti sur deux sous-colonnes de la largeur d'une colonne :
        # même mesure de lecture, mais le bloc occupe toute la largeur.
        lines = len(_wrap(ch["texte"], size, COL_W))
        h = HEADING_BLOCK_H + -(-lines // 2) * _line_h(size)
        if motif == "aplat":
            h += 2 * APLAT_PAD
        return {"motif": motif, "span": 2, "col": 0, "w": SLIDE_W - 2 * MARGIN_X, "h": h}

    if motif in ("duo", "duo-inverse"):
        # Le texte garde la mesure d'une colonne : c'est le visuel qui prend la
        # largeur restante, pas la ligne de texte, qui deviendrait illisible.
        w = SLIDE_W - 2 * MARGIN_X
        iw = w - COL_GUTTER - COL_W
        th = HEADING_BLOCK_H + _text_height(ch["texte"], size, CHAP_TEXT_W)
        _, ratio = _prepare(im)
        ih = min(iw / ratio, DUO_IMG_H)
        if im.get("legende"):
            ih += 0.14 + _text_height(im["legende"], SIZE_CAPTION, min(iw, ih * ratio))
        return {"motif": motif, "span": 2, "col": 0, "w": w,
                "h": max(th, ih), "image_w": iw}

    inset = FOCUS_INSET if motif == "focus" else 0.0
    h = HEADING_BLOCK_H + _text_height(ch["texte"], size, CHAP_TEXT_W - inset)
    if motif == "focus":
        # La conclusion occupe sa propre rangée : mesure réduite, mais rien ne
        # vient se poser à côté d'elle.
        return {"motif": motif, "span": 2, "col": 0, "w": COL_W, "h": h}
    return {
        "motif": motif, "span": 1, "col": 1 if motif == "demi-droite" else 0,
        "w": COL_W, "h": h,
    }


def _preparer(chapitres: list[dict], size: float) -> list[dict]:
    """
    Numérote les chapitres et scinde ceux dont le bloc dépasserait la hauteur
    utile d'une slide. Le formulaire n'impose aucune limite de saisie : sans ce
    garde-fou, un chapitre fleuve déborderait de la slide.
    """
    usable = CONTENT_BOTTOM - CHAP_TOP
    out: list[dict] = []
    for i, ch in enumerate(chapitres):
        item = {**ch, "num": f"{i + 1:02d}"}
        g = _bloc_geom(item, size)
        if g["h"] <= usable:
            out.append(item)
            continue
        # Capacité d'un bloc entier, en lignes rendues, à la mesure du motif.
        par_colonne = max(1, int((usable - HEADING_BLOCK_H) / _line_h(size)))
        if g["motif"] in ("colonnes", "aplat"):
            largeur, capacite = COL_W, par_colonne * 2
        elif g["motif"] == "focus":
            largeur, capacite = CHAP_TEXT_W - FOCUS_INSET, par_colonne
        else:
            largeur, capacite = CHAP_TEXT_W, par_colonne
        reste, label, premier = item["texte"], item["label"], True
        while reste:
            tete, reste = _split_at_lines(reste, size, largeur, capacite)
            out.append({**item, "label": label, "texte": tete,
                        "image": item.get("image") if premier else None})
            label, premier = f"{item['label']} (suite)", False
    return out


def _flow(chapitres: list[dict], size: float) -> list[list[dict]]:
    """
    Répartit les blocs en slides selon un flux par rangées.

    Une rangée se remplit de gauche à droite, et se ferme dès qu'un bloc
    viserait une colonne déjà dépassée. C'est ce qui garantit l'ordre de
    lecture : sans cette règle, un chapitre calé à gauche pourrait se poser à
    côté — donc AVANT à l'œil — d'un chapitre précédent calé à droite, et la
    numérotation se lirait dans le désordre. Un bloc pleine largeur ferme
    toujours la rangée en cours et occupe la sienne seul.

    Retourne une liste de slides, chaque slide étant une liste de blocs
    positionnés {geom, ch, x, y}.
    """
    if not chapitres:
        return []
    slides: list[list[dict]] = [[]]
    rangee_y, rangee_h, derniere_col = CHAP_TOP, 0.0, -1

    for item in _preparer(chapitres, size):
        g = _bloc_geom(item, size)

        if g["span"] == 2 or g["col"] <= derniere_col:
            if rangee_h > 0:
                rangee_y += rangee_h + CHAPTER_GAP
            rangee_h, derniere_col = 0.0, -1

        if rangee_y + g["h"] > CONTENT_BOTTOM and (rangee_h > 0 or rangee_y > CHAP_TOP):
            slides.append([])
            rangee_y, rangee_h, derniere_col = CHAP_TOP, 0.0, -1

        col = 0 if g["span"] == 2 else g["col"]
        slides[-1].append({
            "geom": g, "ch": item,
            "x": MARGIN_X + col * (COL_W + COL_GUTTER), "y": rangee_y,
        })
        rangee_h = max(rangee_h, g["h"])
        derniere_col = 1 if g["span"] == 2 else col

    return [s for s in slides if s]


def _count_slides(projets: list[dict], size: float) -> int:
    total = 1  # slide de titre
    for p in projets:
        total += 1 + len(_flow(p.get("chapitres", []), size))
    return total


def _pick_body_size(projets: list[dict]) -> float:
    """
    Taille de corps unique pour tout le deck : la plus grande du barème parmi
    celles qui donnent le nombre de slides minimal. Réduire la typographie n'a
    d'intérêt que si cela économise une slide — sinon on garde le corps de 10 pt
    de la charte.
    """
    best_size, best_slides = BODY_SIZE_LADDER[-1], None
    for size in BODY_SIZE_LADDER:          # du plus grand au plus petit
        slides = _count_slides(projets, size)
        if best_slides is None or slides < best_slides:
            best_slides, best_size = slides, size
    return best_size


# ---------------------------------------------------------------------------
# Primitives de slide
# ---------------------------------------------------------------------------

def _rect(slide, x, y, w, h, color):
    """Aplat plein, angles droits, sans contour ni ombre."""
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False
    # `<p:style>` référence les effets du thème PowerPoint (effectRef idx=2 =
    # ombre portée) : un effectLst vide ne suffit pas à la neutraliser dans
    # tous les moteurs de rendu. On retire donc le style de thème.
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    return shape


def _textbox(slide, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return tf


def _para(tf, text, size, color, weight="Regular", space_after=0, first=False,
          align=PP_ALIGN.LEFT):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.line_spacing = Pt(size * LINE_FACTOR)
    p.space_after = Pt(space_after)
    run = p.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = weight in ("Bold", "Black", "SemiBold")
    return p


def _one_line(slide, x, y, w, text, size, color, weight="Regular",
              align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    h = _line_h(size) + 0.04
    tf = _textbox(slide, x, y, w, h, anchor=anchor)
    _para(tf, text, size, color, weight, first=True, align=align)
    return y + h


# --- Modules de la grille ---------------------------------------------

def _pastille(slide, x, y, num, size=PASTILLE):
    """Aplat orange carré portant un numéro blanc."""
    _rect(slide, x, y, size, size, ORANGE)
    tf = _textbox(slide, x, y + 0.028, size, size, anchor=MSO_ANCHOR.TOP)
    _para(tf, num, 7.5, WHITE, "Black", first=True, align=PP_ALIGN.CENTER)


def _initiales(nom: str) -> str:
    parts = [p for p in nom.split(" ") if p]
    return "".join(p[0].upper() for p in parts[:2])


def _fait_cell(slide, x, y, w, h, label, value):
    """Cellule modulaire : libellé gris en capitales + valeur."""
    _rect(slide, x, y, w, h, TINT)
    tf = _textbox(slide, x + 0.13, y + 0.09, w - 0.26, h - 0.18)
    p = _para(tf, label.upper(), SIZE_LABEL, GREY, "Bold", space_after=2, first=True)
    p.runs[0].font._rPr.set("spc", "60")   # tracking léger, lisibilité en capitales
    _para(tf, value, 9.5, INK, "SemiBold")


def _tuiles(slide, items, x, y, w, cols=3, gap=0.045):
    """Grille de tuiles de largeur égale — l'expression la plus directe de l'ADN
    pixel-art : des modules, pas une énumération séparée par des points."""
    tile_w = (w - (cols - 1) * gap) / cols
    tile_h = _line_h(SIZE_TILE) + 0.16
    for i, item in enumerate(items):
        cx = x + (i % cols) * (tile_w + gap)
        cy = y + (i // cols) * (tile_h + gap)
        _rect(slide, cx, cy, tile_w, tile_h, TINT)
        tf = _textbox(slide, cx + 0.10, cy + 0.07, tile_w - 0.20, tile_h - 0.14)
        _para(tf, item, SIZE_TILE, INK, first=True)
    rows = -(-len(items) // cols)
    return y + rows * tile_h + max(0, rows - 1) * gap


def _equipe(slide, equipe, x, y, w):
    """Membres en pastilles d'initiales grises + nom et rôle."""
    tile = 0.24
    row_h = 0.31
    for i, m in enumerate(equipe):
        cy = y + i * row_h
        _rect(slide, x, cy, tile, tile, GREY)
        tf = _textbox(slide, x, cy + 0.045, tile, tile)
        _para(tf, _initiales(m["nom"]), 6.5, WHITE, "Bold", first=True, align=PP_ALIGN.CENTER)
        tf = _textbox(slide, x + tile + 0.12, cy + 0.025, w - tile - 0.12, 0.24)
        p = _para(tf, m["nom"], 9.5, INK, "SemiBold", first=True)
        if m.get("role"):
            run = p.add_run()
            run.text = f" — {m['role']}"
            run.font.name = FONT
            run.font.size = Pt(9)
            run.font.color.rgb = GREY
    return y + len(equipe) * row_h


def _flatten(content: bytes) -> tuple[bytes, float]:
    """Aplatit toute image à canal alpha sur blanc (obligatoire avant insertion
    en PPTX) et retourne (octets PNG, ratio largeur/hauteur)."""
    im = Image.open(io.BytesIO(content))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.split()[3])
        im = flat
    else:
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), im.width / im.height


def _prepare(im: dict) -> tuple[bytes, float]:
    """Aplatissement mémoïsé : la pagination interroge le ratio de chaque visuel
    pour chaque taille du barème, décoder l'image à chaque fois serait absurde."""
    if "_flat" not in im:
        im["_flat"] = _flatten(im["content"])
    return im["_flat"]


def _picture_fit(slide, im: dict, x, y, max_w, max_h) -> float:
    """Insère l'image dans la boîte, ratio conservé, calée à gauche. Retourne le
    bas occupé."""
    data, ratio = _prepare(im)
    w, h = max_w, max_w / ratio
    if h > max_h:
        h, w = max_h, max_h * ratio
    slide.shapes.add_picture(io.BytesIO(data), Inches(x), Inches(y),
                             width=Inches(w), height=Inches(h))
    return y + h


def _new_slide(prs, page_no: int, total: int, background: Path | None = None):
    """Slide vierge conforme : fond blanc, photo de fond éventuelle posée en
    premier (donc sous tout le reste), bandeau orange bas, pagination, logo."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = WHITE
    if background and background.exists():
        slide.shapes.add_picture(str(background), 0, 0,
                                 width=Inches(SLIDE_W), height=Inches(SLIDE_H))
    _rect(slide, 0, SLIDE_H - BANNER_H, SLIDE_W, BANNER_H, ORANGE)
    if page_no:
        _one_line(slide, SLIDE_W - MARGIN_X - 1.2, SLIDE_H - BANNER_H - 0.30, 1.2,
                  f"{page_no} / {total}", SIZE_CAPTION, GREY, align=PP_ALIGN.RIGHT)
    slide.shapes.add_picture(str(ASSETS / "logo-c2c-flat.png"),
                             Inches(MARGIN_X), Inches(LOGO_Y), width=Inches(LOGO_W))
    return slide


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def _titre_projet(p: dict) -> str:
    client, design = p.get("client", ""), p.get("designation", "")
    if client and design:
        return f"{client} — {design}"
    return client or design


def _slide_titre(prs, cover: dict, total: int):
    slide = _new_slide(prs, 0, total, background=ASSETS / "bg-mountain-side.png")
    # Bande orange verticale : ancrage du bloc de titre, texte à droite.
    _rect(slide, MARGIN_X, 2.52, 0.045, 1.28, ORANGE)
    x = MARGIN_X + 0.28
    tf = _textbox(slide, x, 2.52, 6.4, 1.4)
    _para(tf, cover["titre"], SIZE_TITLE, ORANGE, "Black", space_after=9, first=True)
    _para(tf, cover["sous_titre"], SIZE_SUBTITLE, INK, "SemiBold", space_after=8)
    if cover.get("sur_titre"):
        _para(tf, cover["sur_titre"], 11, GREY, "SemiBold")


def _slide_ouverture(prs, p: dict, num: str, page_no: int, total: int):
    """Identité, faits, contexte, technologies à gauche ; visuel et équipe à droite."""
    slide = _new_slide(prs, page_no, total)
    left_x, right_x = MARGIN_X, MARGIN_X + COL_W + COL_GUTTER
    ouverture = p.get("visuel_ouverture")
    left_w = COL_W

    # ── Identité : gros numéro orange + client + désignation ──────────
    top = 0.96
    _one_line(slide, left_x, top - 0.10, 1.15, num, SIZE_NUM, ORANGE, "Black")
    tx = left_x + 1.15
    y = _one_line(slide, tx, top, left_w - 1.15, p.get("client") or p.get("designation", ""),
                  SIZE_CLIENT, INK, "Black")
    if p.get("client") and p.get("designation"):
        y = _one_line(slide, tx, y + 0.04, left_w - 1.15, p["designation"],
                      SIZE_DESIGNATION, ORANGE, "SemiBold")

    # ── Faits en cellules modulaires (2 colonnes) ─────────────────────
    cy = max(y + 0.30, 2.02)
    # Le budget est un fait de projet au même titre que la période ou le
    # secteur (cf. reference_renderer._budget_label, qui compose son libellé) —
    # il ouvre la rangée, la période et le secteur suivent, comme en PDF où il
    # se glisse entre le client et la période.
    faits = [(k, v) for k, v in (
        ("Budget", p.get("budget", "")),
        ("Période", p.get("periode", "")),
        ("Secteur", p.get("secteur", "")),
        ("Sous-entité", p.get("sous_entite", "")),
    ) if v]
    if p.get("equipe"):
        n = len(p["equipe"])
        faits.append(("Équipe C2C", f"{n} personne{'s' if n > 1 else ''}"))
    if faits:
        # Une seule rangée de cellules : la lecture des faits se fait d'un coup
        # d'œil, et la grille reste franche (pas de demi-cellule orpheline).
        gap, cols = 0.05, len(faits)
        cw = (left_w - (cols - 1) * gap) / cols
        chh = 0.56
        for i, (label, value) in enumerate(faits):
            _fait_cell(slide, left_x + i * (cw + gap), cy, cw, chh, label, value)
        cy += chh + 0.20

    # ── Contexte ──────────────────────────────────────────────────────
    if p.get("contexte"):
        h = _text_height(p["contexte"], 10, left_w)
        tf = _textbox(slide, left_x, cy, left_w, h + 0.12)
        _para(tf, p["contexte"], 10, INK, first=True)
        cy += h + 0.30

    # ── Technologies : à gauche sous le contexte quand un visuel occupe la
    #    colonne droite ; sinon reportées à droite, pour que les deux colonnes
    #    portent du contenu au lieu de laisser un demi-cadre vide.
    def bloc_tuiles(x, y, w, cols):
        y = _one_line(slide, x, y, w, "Compétences & technologies",
                      SIZE_HEADING, INK, "Bold") + 0.10
        rows_max = max(1, int((CONTENT_BOTTOM - y) / (_line_h(SIZE_TILE) + 0.205)))
        _tuiles(slide, p["competences"][:rows_max * cols], x, y, w, cols=cols)

    if ouverture and p.get("competences"):
        bloc_tuiles(left_x, cy, left_w, 3)

    # ── Colonne droite ────────────────────────────────────────────────
    ry = 1.00
    if ouverture:
        im = ouverture
        ry = _picture_fit(slide, im, right_x, ry, COL_W, 3.60)
        if im.get("legende"):
            h = _text_height(im["legende"], SIZE_CAPTION, COL_W)
            tf = _textbox(slide, right_x, ry + 0.14, COL_W, h + 0.12)
            para = _para(tf, im["legende"], SIZE_CAPTION, GREY, first=True)
            para.runs[0].font.italic = True
            ry += 0.14 + h
        ry += 0.40

    if p.get("equipe"):
        ry = _one_line(slide, right_x, ry, COL_W, "Équipe Camptocamp",
                       SIZE_HEADING, INK, "Bold") + 0.12
        ry = _equipe(slide, p["equipe"], right_x, ry, COL_W) + 0.34

    if not ouverture and p.get("competences"):
        bloc_tuiles(right_x, ry, COL_W, 2)


def _entete_ligne(slide, x, y, w, num, label):
    """Pastille et libellé sur une même ligne — traitement des blocs pleine
    largeur, dont le texte repart ensuite au fer à gauche du bloc."""
    _pastille(slide, x, y + 0.03, num)
    _one_line(slide, x + PASTILLE + PASTILLE_GAP, y, w - PASTILLE - PASTILLE_GAP,
              label, SIZE_HEADING, INK, "Bold")


def _entete_suspendue(slide, x, y, w, num, label):
    """Pastille en gouttière, libellé et texte alignés en retrait — traitement
    des demi-largeurs, où la gouttière reste lisible."""
    _pastille(slide, x, y + 0.03, num)
    tx = x + PASTILLE + PASTILLE_GAP
    _one_line(slide, tx, y, w, label, SIZE_HEADING, INK, "Bold")
    return tx


def _deux_colonnes(slide, texte, x, y, w, size):
    """Texte réparti sur deux sous-colonnes équilibrées : on coupe à la moitié
    des lignes rendues, pas à la moitié des caractères."""
    gap = COL_GUTTER
    cw = (w - gap) / 2
    lines = _wrap(texte, size, cw)
    moitie = -(-len(lines) // 2)
    gauche, droite = " ".join(lines[:moitie]), " ".join(lines[moitie:])
    for i, part in enumerate((gauche, droite)):
        if not part:
            continue
        h = _text_height(part, size, cw)
        tf = _textbox(slide, x + i * (cw + gap), y, cw, h + 0.12)
        _para(tf, part, size, INK, first=True)
    return moitie * _line_h(size)


def _rendre_bloc(slide, bloc: dict, size: float):
    """Pose un bloc de chapitre selon son motif."""
    g, ch = bloc["geom"], bloc["ch"]
    x, y, motif = bloc["x"], bloc["y"], g["motif"]

    if motif == "aplat":
        # Bande grise débordant les deux marges : c'est le fond qui va au bord,
        # pas le texte — la mesure de lecture reste celle d'une colonne.
        _rect(slide, 0, y, SLIDE_W, g["h"], TINT)
        y += APLAT_PAD
        _entete_ligne(slide, x, y, g["w"], ch["num"], ch["label"])
        _deux_colonnes(slide, ch["texte"], x, y + HEADING_BLOCK_H, g["w"], size)
        return

    if motif == "colonnes":
        _entete_ligne(slide, x, y, g["w"], ch["num"], ch["label"])
        _deux_colonnes(slide, ch["texte"], x, y + HEADING_BLOCK_H, g["w"], size)
        return

    if motif in ("duo", "duo-inverse"):
        # Texte sur la mesure d'une colonne, visuel sur la largeur restante.
        iw_col = g["image_w"]
        if motif == "duo-inverse":
            ix, tx0 = x, x + iw_col + COL_GUTTER
        else:
            tx0, ix = x, x + COL_W + COL_GUTTER
        t_left = _entete_suspendue(slide, tx0, y, CHAP_TEXT_W, ch["num"], ch["label"])
        th = _text_height(ch["texte"], size, CHAP_TEXT_W)
        tf = _textbox(slide, t_left, y + HEADING_BLOCK_H, CHAP_TEXT_W, th + 0.12)
        _para(tf, ch["texte"], size, INK, first=True)

        im = ch["image"]
        iy = _picture_fit(slide, im, ix, y, iw_col, DUO_IMG_H)
        if im.get("legende"):
            h = _text_height(im["legende"], SIZE_CAPTION, iw_col)
            tf = _textbox(slide, ix, iy + 0.12, iw_col, h + 0.12)
            para = _para(tf, im["legende"], SIZE_CAPTION, GREY, first=True)
            para.runs[0].font.italic = True
        return

    # Demi-largeurs : demi-gauche, demi-droite, focus.
    inset = 0.0
    if motif == "focus":
        # Seul accent latéral du projet : bord gauche orange.
        _rect(slide, x, y, FOCUS_RULE_W, g["h"] + 0.06, ORANGE)
        inset = FOCUS_INSET
    bx = x + inset
    tw = CHAP_TEXT_W - inset
    t_left = _entete_suspendue(slide, bx, y, tw, ch["num"], ch["label"])
    th = _text_height(ch["texte"], size, tw)
    tf = _textbox(slide, t_left, y + HEADING_BLOCK_H, tw, th + 0.12)
    _para(tf, ch["texte"], size, INK, first=True)


def _slides_chapitres(prs, p: dict, num_projet: str, size: float,
                      page_no: int, total: int) -> int:
    """Pose les slides de chapitres. Retourne le nombre de slides produites."""
    slides_blocs = _flow(p.get("chapitres", []), size)

    for n, blocs in enumerate(slides_blocs):
        slide = _new_slide(prs, page_no + n, total)
        # Rappel du projet : numéro orange + intitulé, même ancrage que l'ouverture.
        tf = _textbox(slide, MARGIN_X, 1.00, SLIDE_W - 2 * MARGIN_X, 0.40)
        p0 = _para(tf, num_projet, SIZE_HEADING, ORANGE, "Black", first=True)
        run = p0.add_run()
        run.text = f"   {_titre_projet(p)}"
        run.font.name = FONT
        run.font.size = Pt(SIZE_HEADING + 1)
        run.font.bold = True
        run.font.color.rgb = INK

        for bloc in blocs:
            _rendre_bloc(slide, bloc, size)

    return len(slides_blocs)


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------

def render(projets: list[dict], cover: dict) -> bytes:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    size = _pick_body_size(projets)
    total = _count_slides(projets, size)

    _slide_titre(prs, cover, total)
    page = 2
    for i, p in enumerate(projets):
        num = f"{i + 1:02d}"
        _slide_ouverture(prs, p, num, page, total)
        page += 1
        page += _slides_chapitres(prs, p, num, size, page, total)

    buf = io.BytesIO()
    prs.save(buf)
    return _embed_inter(buf.getvalue())


def _embed_inter(pptx_bytes: bytes) -> bytes:
    """
    Embarque Inter dans le PPTX (post-traitement prescrit par la charte :
    PowerPoint chez le destinataire affiche Inter même sans l'avoir installée).
    En cas d'échec, le fichier reste valide — Inter est simplement substituée.
    """
    script = ASSETS / "embed_inter.py"   # doit rester à côté des Inter-*.ttf
    if not script.exists():
        return pptx_bytes
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "deck.pptx"
        src.write_bytes(pptx_bytes)
        try:
            subprocess.run([sys.executable, str(script), str(src)],
                           check=True, capture_output=True, timeout=120)
        except Exception:
            return pptx_bytes
        return src.read_bytes()
