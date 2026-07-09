#!/bin/bash
cd "$(dirname "$0")/codebase"

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

# Détermine le port : PORT= dans .env, sinon argument passé au script, sinon 8002 par défaut
PORT=8002
ENV_PORT=$(grep -E '^PORT=' .env | tail -1 | cut -d '=' -f2 | tr -d ' \r')
if [ -n "$ENV_PORT" ]; then PORT="$ENV_PORT"; fi
if [ -n "$1" ]; then PORT="$1"; fi

# Libère le port si un ancien serveur y tourne encore
lsof -ti tcp:$PORT 2>/dev/null | xargs kill -9 2>/dev/null || true

echo "Démarrage de C2C Tenders App sur le port $PORT..."
(open "http://localhost:$PORT" 2>/dev/null || xdg-open "http://localhost:$PORT" 2>/dev/null || true) &
python3 -m uvicorn app.main:app --host 127.0.0.1 --port $PORT
