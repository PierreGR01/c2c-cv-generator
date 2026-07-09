"""
Rendu PDF via Typst — même moteur que le skill existant, garanti pixel-identique.
"""
import tempfile
import yaml
from pathlib import Path

import typst
from pypdf import PdfReader

ENGINE_DIR = Path(__file__).parent.parent / "engine"
TEMPLATE = ENGINE_DIR / "cv-template.typ"
ASSETS = ENGINE_DIR / "assets"

MIN_PROJETS = 3


def _render_once(data: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ENGINE_DIR / ".build_tmp.yaml"
    try:
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        typst.compile(
            str(TEMPLATE),
            output=str(out_path),
            root=str(ENGINE_DIR),
            font_paths=[str(ASSETS)],
            sys_inputs={"data": ".build_tmp.yaml"},
        )
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _count_pages(pdf_path: Path) -> int:
    try:
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return 1


def render_cv(data: dict, output_path: Path, max_projets: int = 4, max_pages: int = 1) -> tuple[int, str | None]:
    """
    Génère le PDF en respectant la contrainte de pages (peu importe qu'elle soit
    dépassée d'une page ou de plusieurs : la cascade retest à chaque étape).

    max_projets : nombre max de projets (0 = tous)
    max_pages   : limite de pages (0 = sans limite, rendu direct sans cascade)

    Réduction, dans l'ordre, retest après chaque étape :
      1. Réduction typographique niveau 1 (-0.5pt).
      2. Réduction de l'interlignage (palier unique, -0.05em).
      3. Réduction typographique niveau 2 (-1pt, remplace le niveau 1).
      4. Suppression du parcours professionnel antérieur.
      5. Retrait des projets un par un jusqu'à MIN_PROJETS (plancher).

    Dès que la limite est respectée (à n'importe quelle étape), on relâche les
    contraintes pour maximiser la qualité du rendu sans jamais repasser au-dessus
    de la limite : réintégration du parcours si retiré, puis reset interlignage,
    puis reset police — chacun testé indépendamment, gardé seulement s'il ne fait
    pas remonter le nombre de pages.

    Retourne (nb_projets_effectivement_inclus, warning). `warning` est None si la
    limite est respectée, sinon un message signalant le dépassement résiduel après
    épuisement de tous les leviers.
    """
    tous = data["projets"]
    max_p = len(tous) if max_projets == 0 else min(max_projets, len(tous))

    # Sans contrainte : rendu direct, aucune cascade.
    if max_pages == 0:
        _render_once({**data, "projets": tous[:max_p]}, output_path)
        return max_p, None

    min_p = min(MIN_PROJETS, len(tous))
    parcours_orig = data.get("parcours", [])

    def render_state(n_projets: int, parcours_on: bool, font_level: int, interligne_level: int) -> int:
        t = {**data, "projets": tous[:n_projets], "parcours": parcours_orig if parcours_on else []}
        if font_level:
            t["font_reduction"] = font_level
        if interligne_level:
            t["interligne_reduction"] = interligne_level
        _render_once(t, output_path)
        return _count_pages(output_path)

    def ok(pages: int) -> bool:
        return pages <= max_pages

    n_projets = max_p
    parcours_on = bool(parcours_orig)
    font_level = 0
    interligne_level = 0

    pages = render_state(n_projets, parcours_on, font_level, interligne_level)
    if ok(pages):
        return n_projets, None

    def optimize() -> None:
        """Relâche les leviers un par un (contenu avant typo), ne garde le
        relâchement que s'il ne fait pas remonter le nombre de pages.

        Chaque test réécrit output_path, y compris quand il est rejeté : on
        referme donc systématiquement avec un rendu de l'état final retenu
        pour garantir que le fichier sur disque correspond à ce qui est
        retourné par la fonction.
        """
        nonlocal parcours_on, font_level, interligne_level, pages
        if not parcours_on and parcours_orig:
            test = render_state(n_projets, True, font_level, interligne_level)
            if ok(test):
                parcours_on, pages = True, test
        if interligne_level:
            test = render_state(n_projets, parcours_on, font_level, 0)
            if ok(test):
                interligne_level, pages = 0, test
        if font_level:
            test = render_state(n_projets, parcours_on, 0, interligne_level)
            if ok(test):
                font_level, pages = 0, test
        pages = render_state(n_projets, parcours_on, font_level, interligne_level)

    # --- Étape 1 : police -0.5 ---
    font_level = 1
    pages = render_state(n_projets, parcours_on, font_level, interligne_level)

    # --- Étape 2 : interlignage réduit ---
    if not ok(pages):
        interligne_level = 1
        pages = render_state(n_projets, parcours_on, font_level, interligne_level)

    # --- Étape 3 : police -1 (remplace le niveau 1) ---
    if not ok(pages):
        font_level = 2
        pages = render_state(n_projets, parcours_on, font_level, interligne_level)

    # --- Étape 4 : suppression du parcours ---
    if not ok(pages) and parcours_on:
        parcours_on = False
        pages = render_state(n_projets, parcours_on, font_level, interligne_level)

    if ok(pages):
        optimize()
        return n_projets, None

    # --- Étape 5 : retrait des projets un par un jusqu'au plancher ---
    while n_projets > min_p:
        n_projets -= 1
        pages = render_state(n_projets, parcours_on, font_level, interligne_level)
        if ok(pages):
            optimize()
            return n_projets, None

    # Tous les leviers épuisés : livré quand même, avec warning.
    excess = pages - max_pages
    warning = (
        f"Le CV dépasse encore la limite de {max_pages} page(s) de {excess} page(s) "
        f"malgré la réduction maximale (police, interlignage, parcours retiré, "
        f"{n_projets} projet(s) minimum)."
    )
    return n_projets, warning


def render_cv_to_bytes(data: dict, max_projets: int = 4, max_pages: int = 1) -> tuple[bytes, int, str | None]:
    """
    Génère le PDF en mémoire.
    Retourne (pdf_bytes, nb_projets_utilisés, warning_ou_None).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "cv.pdf"
        n, warning = render_cv(data, out, max_projets=max_projets, max_pages=max_pages)
        return out.read_bytes(), n, warning
