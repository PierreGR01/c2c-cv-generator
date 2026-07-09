@echo off
cd /d "%~dp0"

:: Verifie que Python est disponible
python --version >nul 2>&1
if errorlevel 1 (
    echo Python n'est pas installe ou pas dans le PATH.
    echo Installe Python 3 depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Verifie que .env existe
if not exist ".env" (
    echo Fichier .env manquant. Copie .env.example en .env et renseigne les valeurs.
    pause
    exit /b 1
)

:: Installe les dependances si besoin
echo Installation des dependances...
pip install -r requirements.txt --quiet

:: Authentification Google (consentement navigateur au premier lancement)
echo Authentification Google...
python authorize.py
if errorlevel 1 (
    echo Echec de l'authentification. Verifie client_secret.json et .env.
    pause
    exit /b 1
)

:: Determine le port : PORT= dans .env, sinon argument passe au script, sinon 8002 par defaut
set PORT=8002
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /i "PORT=" ".env" 2^>nul`) do set PORT=%%B
if not "%~1"=="" set PORT=%~1

:: Libere le port si un ancien serveur y tourne encore (evite de servir du code perime)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT% ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

echo Demarrage de C2C Tenders App sur le port %PORT%...
start "" "http://localhost:%PORT%"
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
