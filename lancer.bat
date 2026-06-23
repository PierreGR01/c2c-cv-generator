@echo off
cd /d "%~dp0"

docker info >nul 2>&1
if errorlevel 1 (
    echo Docker n'est pas lance. Ouvre Docker Desktop puis relance ce fichier.
    pause
    exit /b 1
)

echo Demarrage du CV Generator...
start "" "http://localhost:8000"
docker compose up --build
