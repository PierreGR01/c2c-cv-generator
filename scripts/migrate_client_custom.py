"""
Migration : renomme la clé projet "client" en "client_custom" dans toutes les
fiches collaborateurs sur Google Drive (source de données unique de l'app).

Renommage par remplacement de texte ciblé (pas de round-trip yaml.safe_load /
yaml.dump), pour ne pas perturber la mise en forme existante des fiches
(commentaires, chaînes multi-lignes "contexte: >", ordre des clés...).

Usage :
    python scripts/migrate_client_custom.py             # dry-run (aucune écriture)
    python scripts/migrate_client_custom.py --apply      # applique + sauvegarde sur Drive

Une sauvegarde du contenu brut de chaque fiche modifiée est écrite dans
backup-client-custom-migration/ avant toute écriture (même principe que
l'ancienne migration "poids", cf. backup-poids-migration/).
"""
import argparse
import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

from dotenv import load_dotenv
load_dotenv(APP_ROOT / ".env")

from app import drive  # noqa: E402

CLIENT_KEY_RE = re.compile(r"(?m)^(  )client:")
BACKUP_DIR = APP_ROOT / "backup-client-custom-migration"


def migrate_text(raw: str) -> tuple[str, int]:
    new_text, n = CLIENT_KEY_RE.subn(r"\1client_custom:", raw)
    return new_text, n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Écrit réellement sur Drive (sinon dry-run)")
    args = parser.parse_args()

    collabs = drive.list_collaborateurs()
    print(f"{len(collabs)} fiche(s) collaborateur trouvée(s) sur Drive.\n")

    if args.apply:
        BACKUP_DIR.mkdir(exist_ok=True)

    total_changed_files = 0
    total_changed_lines = 0

    for c in collabs:
        raw = drive.get_fiche_raw(c["id"])
        new_text, n = migrate_text(raw)
        if n == 0:
            print(f"  - {c['filename']:40s} : aucune occurrence de 'client:' — rien à faire")
            continue

        total_changed_files += 1
        total_changed_lines += n
        print(f"  * {c['filename']:40s} : {n} occurrence(s) de 'client:' -> 'client_custom:'")

        if args.apply:
            (BACKUP_DIR / c["filename"]).write_text(raw, encoding="utf-8")
            drive.save_fiche_content(c["id"], new_text)

    print(f"\n{total_changed_files} fiche(s) modifiée(s), {total_changed_lines} ligne(s) renommée(s).")
    if not args.apply:
        print("Dry-run : aucune écriture effectuée. Relancer avec --apply pour appliquer sur Drive.")
    else:
        print(f"Sauvegarde des versions précédentes dans {BACKUP_DIR}")


if __name__ == "__main__":
    main()
