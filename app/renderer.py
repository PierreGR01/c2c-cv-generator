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


def render_cv(data: dict, output_path: Path, max_projets: int = 4, max_pages: int = 1) -> int:
    """
    Génère le PDF.

    max_projets : nombre max de projets (0 = tous)
    max_pages   : limite de pages (0 = sans limite, pas de réduction)

    Retourne le nombre de projets effectivement inclus.
    """
    tous = data["projets"]
    max_p = len(tous) if max_projets == 0 else min(max_projets, len(tous))

    # Sans limite de pages : rendu direct, aucune réduction
    if max_pages == 0:
        _render_once({**data, "projets": tous[:max_p]}, output_path)
        return max_p

    min_p = min(MIN_PROJETS, len(tous))

    for n in range(max_p, min_p - 1, -1):
        tentative = {**data, "projets": tous[:n]}
        _render_once(tentative, output_path)
        pages = _count_pages(output_path)
        if pages <= max_pages:
            return n
        if n <= min_p:
            # Plancher atteint, on livre quand même
            return n

    return min_p


def render_cv_to_bytes(data: dict, max_projets: int = 4, max_pages: int = 1) -> tuple[bytes, int]:
    """
    Génère le PDF en mémoire.
    Retourne (pdf_bytes, nb_projets_utilisés).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "cv.pdf"
        n = render_cv(data, out, max_projets=max_projets, max_pages=max_pages)
        return out.read_bytes(), n
