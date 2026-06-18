# Installation locale — CV Generator Camptocamp

## Prérequis

- Python 3.11+
- Accès à LastPass (note sécurisée **`CV Generator – .env`** partagée par Pierre)

---

## 1. Récupérer le code

```bash
git clone https://github.com/<org>/<repo>.git
cd cv-generator
```

---

## 2. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

---

## 3. Configurer les credentials

Dans LastPass, ouvre la note sécurisée **`CV Generator – .env`**, copie son contenu et colle-le dans un nouveau fichier `.env` à la racine de `cv-generator/`.

Le fichier doit ressembler à :

```env
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
GOOGLE_DRIVE_FOLDER_ID=1aBcDeFgHiJkLmNoPqRsTuV
```

> ⚠️ Ne jamais committer `.env` — il est dans `.gitignore`.

---

## 4. Lancer l'application

```bash
uvicorn app.main:app --reload
```

Ouvre [http://localhost:8000](http://localhost:8000).

---

## Mise à jour

```bash
git pull
```

Réinstalle les dépendances uniquement si `requirements.txt` a changé.
