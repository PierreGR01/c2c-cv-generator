#!/usr/bin/env python3
"""
embed_inter.py — Embarque la police Inter dans un PPTX existant.

pptxgenjs ne sait pas embarquer de police nativement. Ce script effectue le
post-processing : il insère les fichiers Inter-*.ttf (situés dans le meme
repertoire que ce script) directement dans l'archive .pptx, en respectant le
format d'embedding OOXML attendu par PowerPoint.

Usage :
    python3 assets/embed_inter.py presentation.pptx
    python3 assets/embed_inter.py presentation.pptx sortie_avec_inter.pptx

Dependances : Python 3.8+ (stdlib uniquement). Aucune lib externe.
"""

import os
import re
import shutil
import sys
import zipfile

# typeface PowerPoint -> fichier TTF (dans le repertoire de ce script).
# Inter SemiBold et Inter Black sont des familles nommees distinctes : on les
# embarque comme tel pour qu'un deck referencant "Inter SemiBold" / "Inter Black"
# (ou "Inter" gras) trouve toujours la bonne fonte.
FONT_MAP = [
    {"typeface": "Inter",          "regular": "Inter-Regular.ttf", "bold": "Inter-Bold.ttf"},
    {"typeface": "Inter SemiBold", "regular": "Inter-SemiBold.ttf"},
    {"typeface": "Inter Black",    "regular": "Inter-Black.ttf"},
]

CT_PATH = "[Content_Types].xml"
PRES_PATH = "ppt/presentation.xml"
RELS_PATH = "ppt/_rels/presentation.xml.rels"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
FONT_REL_TYPE = f"{REL_NS}/font"


def _here():
    return os.path.dirname(os.path.abspath(__file__))


def _read(z, name):
    return z.read(name).decode("utf-8")


def _next_rid(rels_xml):
    ids = [int(m) for m in re.findall(r'Id="rId(\d+)"', rels_xml)]
    n = max(ids) + 1 if ids else 1
    while True:
        yield f"rId{n}"
        n += 1


def embed(src, dst):
    here = _here()

    # 1. Verifier la presence de tous les TTF requis.
    needed = set()
    for entry in FONT_MAP:
        for slot in ("regular", "bold", "italic", "boldItalic"):
            if entry.get(slot):
                needed.add(entry[slot])
    missing = [f for f in sorted(needed) if not os.path.exists(os.path.join(here, f))]
    if missing:
        sys.exit("Polices manquantes dans assets/ : " + ", ".join(missing))

    with zipfile.ZipFile(src, "r") as z:
        names = set(z.namelist())
        ct = _read(z, CT_PATH)
        pres = _read(z, PRES_PATH)
        rels = _read(z, RELS_PATH)
        payload = {n: z.read(n) for n in names}

    # 2. [Content_Types].xml : declarer l'extension fntdata.
    if 'Extension="fntdata"' not in ct:
        ct = ct.replace(
            "</Types>",
            '<Default Extension="fntdata" ContentType="application/x-fontdata"/></Types>',
        )

    # 3. Ajouter chaque fonte comme part + relationship, et construire la liste.
    rid_gen = _next_rid(rels)
    new_rels = []
    font_parts = {}          # nom de part -> octets
    embedded_fonts_xml = []
    idx = 1

    for entry in FONT_MAP:
        font_el = [f'<p:embeddedFont><p:font typeface="{entry["typeface"]}"/>']
        for slot in ("regular", "bold", "italic", "boldItalic"):
            ttf = entry.get(slot)
            if not ttf:
                continue
            part = f"ppt/fonts/inter{idx}.fntdata"
            idx += 1
            font_parts[part] = open(os.path.join(here, ttf), "rb").read()
            rid = next(rid_gen)
            new_rels.append(
                f'<Relationship Id="{rid}" Type="{FONT_REL_TYPE}" '
                f'Target="fonts/{os.path.basename(part)}"/>'
            )
            font_el.append(f'<p:{slot} r:id="{rid}"/>')
        font_el.append("</p:embeddedFont>")
        embedded_fonts_xml.append("".join(font_el))

    rels = rels.replace("</Relationships>", "".join(new_rels) + "</Relationships>")

    # 4. presentation.xml : attribut embedTrueTypeFonts + bloc embeddedFontLst.
    if "embedTrueTypeFonts" not in pres:
        pres = re.sub(r"(<p:presentation\b)", r'\1 embedTrueTypeFonts="1"', pres, count=1)

    lst = "<p:embeddedFontLst>" + "".join(embedded_fonts_xml) + "</p:embeddedFontLst>"
    if "<p:embeddedFontLst>" not in pres:
        # Respecter l'ordre du schema CT_Presentation : embeddedFontLst se place
        # apres sldSz/notesSz/smartTags, avant custShowLst/.../extLst.
        inserted = False
        for tag in ("<p:custShowLst", "<p:custDataLst", "<p:kinsoku",
                    "<p:defaultTextStyle", "<p:extLst"):
            pos = pres.find(tag)
            if pos != -1:
                pres = pres[:pos] + lst + pres[pos:]
                inserted = True
                break
        if not inserted:
            pres = pres.replace("</p:presentation>", lst + "</p:presentation>")

    # 5. Reecrire l'archive.
    payload[CT_PATH] = ct.encode("utf-8")
    payload[PRES_PATH] = pres.encode("utf-8")
    payload[RELS_PATH] = rels.encode("utf-8")
    payload.update(font_parts)

    tmp = dst + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in payload.items():
            z.writestr(name, data)
    shutil.move(tmp, dst)
    print(f"OK — Inter embarquee dans {dst} ({len(font_parts)} fontes).")


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 embed_inter.py entree.pptx [sortie.pptx]")
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    if not os.path.exists(src):
        sys.exit(f"Fichier introuvable : {src}")
    embed(src, dst)


if __name__ == "__main__":
    main()
