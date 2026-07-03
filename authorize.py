"""
Pré-authentification OAuth (c2c-tenders-app).

Déclenche ou rafraîchit le consentement Google AVANT le démarrage du serveur,
pour que le premier appel Drive soit déjà authentifié (et pour que le
consentement navigateur ne bloque pas une requête HTTP).

Lancé automatiquement par lancer.bat / lancer.sh.
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from app import drive

try:
    drive.authenticate()
    print("Authentification Google Drive OK.")
except Exception as e:  # noqa: BLE001 — on veut un message clair, pas une stacktrace
    print(f"Échec de l'authentification Google : {e}", file=sys.stderr)
    sys.exit(1)
