#!/bin/bash
cd "$(dirname "$0")"

if ! docker info > /dev/null 2>&1; then
    echo "Docker n'est pas lancé. Ouvre Docker Desktop puis relance ce script."
    exit 1
fi

echo "Démarrage du CV Generator..."
open "http://localhost:8000" 2>/dev/null || xdg-open "http://localhost:8000" 2>/dev/null || true
docker compose up --build
