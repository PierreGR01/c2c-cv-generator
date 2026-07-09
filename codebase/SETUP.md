# C2C Tenders App — Prise en main

Générer des CVs PDF à la charte Camptocamp, ciblés sur un appel d'offre, en quelques clics.

> **Authentification OAuth.** Tu t'authentifies avec ton propre compte Google
> — aucun secret d'accès aux données n'est distribué. La configuration Google
> Cloud (à faire une fois par l'admin) et le partage des dossiers Drive sont
> décrits dans **[`SETUP-OAUTH.md`](SETUP-OAUTH.md)** — lis-le d'abord si
> c'est la première installation dans l'équipe.

---

## Ce dont tu as besoin

| Quoi | Où |
|---|---|
| **Python 3** | [python.org/downloads](https://www.python.org/downloads/) — installe-le une seule fois |
| **Le code** | Demande l'accès au repo GitHub à Pierre |
| **`client_secret.json`** | LastPass → note sécurisée **`CV Generator – OAuth`** |

---

## Installation (une seule fois)

### 1. Installe Python 3

Télécharge et installe Python depuis python.org. Sur Windows, coche
**« Add Python to PATH »** pendant l'installation.

### 2. Récupère le code

Clone le dépôt ou télécharge-le en ZIP, puis décompresse-le où tu veux.

### 3. Dépose le client OAuth

Récupère **`client_secret.json`** dans LastPass et place-le dans ce dossier
`codebase/` (à côté de `SETUP-OAUTH.md`). Rien d'autre à configurer : `.env`
est déjà présent ici et pré-rempli (IDs des dossiers Drive) — tu n'as besoin
de l'ouvrir que pour changer le port local (voir plus bas).

> ⚠️ Ne committe jamais `client_secret.json` (déjà couvert par `.gitignore`).

---

## Utilisation au quotidien

### Lancer le service

- **Windows** — double-clique sur `lancer.bat`
- **Mac** — double-clique sur `lancer.sh` _(1re fois : clic droit → Ouvrir)_

`lancer.bat`/`lancer.sh` vivent à la racine du dépôt (pas dans `codebase/`) et
savent retrouver le reste tout seuls. Envie d'une icône personnalisée sur ton
Bureau plutôt qu'un double-clic dans le dossier ? Clic droit sur `lancer.bat`
→ *Envoyer vers → Bureau (créer un raccourci)*, puis clic droit sur ce
raccourci → *Propriétés → Changer d'icône* → parcourir jusqu'à
`codebase/static/favicon.ico`.

Le premier lancement installe les dépendances (~1-2 min) puis ouvre le
navigateur pour le **consentement Google** : connecte-toi avec ton compte
**`@camptocamp.com`**. Les fois suivantes, c'est direct.

Le navigateur s'ouvre sur **http://localhost:8002**.

> **Le port 8002 est déjà utilisé par un autre projet ?** Ajoute `PORT=8010`
> (ou tout autre numéro libre) dans ton fichier `.env`, ou lance le script
> avec le port en argument : `./lancer.sh 8010` (Mac) ou `lancer.bat 8010`
> (Windows, depuis un terminal).

### Générer un CV

1. **Sélectionne un ou plusieurs collaborateurs** dans la liste de gauche
2. **Dépose le fichier YAML de l'appel d'offre** (optionnel — sans AO, le CV est générique)
3. **Ajuste les options** si besoin (nombre de projets, pages max, parcours)
4. Clique sur **Générer**

Le PDF se télécharge automatiquement. Pour plusieurs collaborateurs, tu reçois un ZIP.

### Arrêter le service

Ferme la fenêtre de terminal, ou fais `Ctrl+C` dedans.

---

## Ajouter ou mettre à jour un collaborateur

Les fiches collaborateurs sont des fichiers YAML stockés sur **Google Drive**.
Le service les lit directement — pas besoin de toucher au code. Dépose ou édite
le `.yaml` dans le dossier `collaborateurs/` sur Drive ; il apparaît au prochain
chargement (cache de 5 min). Ta capacité à écrire dépend de tes droits Drive.

---

## Problèmes courants

**« Client OAuth manquant »**
→ `client_secret.json` absent du dossier, ou `GOOGLE_OAUTH_CLIENT_SECRET_FILE`
mal renseigné dans `.env`.

**La liste de collaborateurs est vide**
→ Ton compte Google n'a pas accès au dossier `collaborateurs/` sur Drive, ou les
IDs dans `.env` sont incorrects.

**Le PDF dépasse une page**
→ Réduis le nombre de projets max dans les options (essaie 3).

**Détails et dépannage OAuth** → voir [`SETUP-OAUTH.md`](SETUP-OAUTH.md).
