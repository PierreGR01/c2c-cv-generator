#!/bin/bash
cd "$(dirname "$0")"

# Vérifie que Python est disponible
if ! command -v python3 &> /dev/null; then
    echo "Python 3 n'est pas installé. Installe-le depuis https://www.python.org/downloads/"
    exit 1
fi

# Vérifie que .env existe
if [ ! -f ".env" ]; then
    echo "Fichier .env manquant. Copie .env.example en .env et renseigne les valeurs."
    exit 1
fi

# Installe les dépendances si besoin
echo "Installation des dépendances..."
python3 -m pip install -r requirements.txt --quiet

# Authentification Google (consentement navigateur au premier lancement)
echo "Authentification Google..."
if ! python3 authorize.py; then
    echo "Échec de l'authentification. Vérifie client_secret.json et .env."
    exit 1
fi

# Libère le port 8002 si un ancien serveur y tourne encore
lsof -ti tcp:8002 2>/dev/null | xargs kill -9 2>/dev/null || true

echo "Démarrage de C2C Tenders App..."
(open "http://localhost:8002" 2>/dev/null || xdg-open "http://localhost:8002" 2>/dev/null || true) &
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8002
