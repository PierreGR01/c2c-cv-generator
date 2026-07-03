# Configuration Google Cloud (admin — une seule fois)

`c2c-tenders-app` s'authentifie en **OAuth par utilisateur** : chaque personne se
connecte avec son propre compte Google Workspace. Aucun secret d'accès aux
données n'est distribué — l'accès réel est décidé par les **partages Drive**
accordés au compte de chacun, pas par le code de l'application.

> **Rappel sécurité.** La frontière d'accès n'est **pas** dans le code ni dans
> l'interface : elle est dans les **ACL Drive**. Un chef de projet ne peut pas
> écrire dans `collaborateurs/` parce que le Drive le lui refuse — même s'il
> utilisait l'app « en mode admin ». C'est ce qui rend l'interface unique sûre.

Cette page ne concerne que l'**administrateur** (une seule fois, à la mise en
place). Pour l'installation individuelle, voir [`SETUP.md`](SETUP.md).

---

## 1. Projet Google Cloud + API Drive

1. [console.cloud.google.com](https://console.cloud.google.com) → crée (ou
   réutilise) un projet **dans l'organisation `camptocamp.com`**.
2. **APIs & Services → Library** → active :
   - **Google Drive API**
   - **Gmail API** (pour les notifications e-mail internes à l'app)

## 2. Écran de consentement OAuth

1. **APIs & Services → OAuth consent screen**.
2. Type **Internal** (recommandé) → limite l'usage aux comptes `@camptocamp.com`,
   pas de validation Google nécessaire, pas d'écran « app non vérifiée ».
   _(Si « Internal » est indisponible, choisis « External » et ajoute les
   utilisateurs en « Test users ».)_
3. Scopes à déclarer :
   - `https://www.googleapis.com/auth/drive` (lecture/écriture des fiches)
   - `https://www.googleapis.com/auth/gmail.send` (notifications e-mail,
     envoyées sous l'identité de l'utilisateur)

## 3. Créer le client OAuth « application de bureau »

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Type d'application : **Desktop app**.
3. Télécharge le fichier JSON → renomme-le **`client_secret.json`**.

> Ce fichier identifie l'*application*, pas les données. Pour un client
> « desktop », Google considère le `client_secret` comme **non confidentiel** :
> le distribuer (via un vault interne type LastPass) est acceptable. Il ne
> donne accès à rien sans le consentement d'un vrai compte utilisateur.

## 4. Structure du Drive et partages = le vrai contrôle d'accès

C'est **ici** que se joue la sécurité. Crée un dossier racine sur le Drive
(ex. `CV Camptocamp`), avec au minimum :

```
CV Camptocamp/                 (GOOGLE_DRIVE_FOLDER_ID)
├── collaborateurs/            (COLLABORATEURS_FOLDER_ID) — une fiche YAML par personne
├── _competences.yaml          (COMPETENCES_FILE_ID) — référentiel de compétences
├── _clients.yaml              (CLIENTS_FILE_ID) — référentiel clients
└── _app-config.yaml           — rôle admin + notifications (voir plus bas)
```

Récupère l'ID de chaque dossier/fichier dans son URL Drive
(`.../folders/<ID>` ou `.../d/<ID>/edit`) pour renseigner le `.env`
(voir [`SETUP.md`](SETUP.md)).

Partage chaque élément avec les **comptes Google réels** des personnes
(jamais avec un email de compte de service) :

| Élément Drive | Admin | Chefs de projet / collaborateurs |
|---|---|---|
| `collaborateurs/` (fiches maîtres) | **Éditeur** | Lecteur, ou non partagé |
| `_competences.yaml`, `_clients.yaml` | Éditeur | Lecteur |
| `_app-config.yaml` | Éditeur | non partagé |

Tant que `collaborateurs/` n'est pas partagé en écriture avec les CP, ils ne
peuvent pas modifier les fiches maîtres, quel que soit leur usage de l'app.

## 5. Rôle admin & notifications — `_app-config.yaml`

Dépose un fichier `_app-config.yaml` à la racine du dossier Drive (gabarit :
[`_app-config.example.yaml`](_app-config.example.yaml)) :

```yaml
admins:
  - prenom.nom@camptocamp.com
notifications:
  enabled: true
  recipients: []          # vide => notifie les admins ; idéalement un alias de groupe
```

Le rôle admin est ainsi lié à une **liste, pas à un individu codé en dur** :
changer d'admin = éditer ce fichier sur le Drive, sans toucher au code. À
chaque ingestion de fiche ou modification de YAML, un e-mail part **du compte
de l'utilisateur agissant** vers ces destinataires.

> Rappel : le rôle admin ne fait qu'afficher/masquer l'UI (ex. l'éditeur de
> fiches). La vraie barrière d'écriture reste les **ACL Drive**.

---

## Où vit le token utilisateur, comment le révoquer

- Par défaut : `~/.config/cv-c2c/token-c2c-tenders-app.json` (hors du repo),
  permissions `600`. Personnalisable via `GOOGLE_OAUTH_TOKEN_FILE` dans `.env`.
- **Révoquer un accès** : l'utilisateur sur
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions),
  ou l'admin Workspace côté organisation. Supprimer le fichier token force un
  nouveau consentement au prochain lancement.

---

## Dépannage admin

**« app non vérifiée » à l'écran de consentement** → l'écran est en
« External ». Repasse-le en « Internal », ou ajoute le compte en « Test user ».

**Erreur 403 à l'écriture d'une fiche** → comportement **attendu** si le
compte n'a pas l'accès Éditeur sur le dossier Drive concerné. C'est la
sécurité qui fonctionne, pas un bug.

**La liste des collaborateurs est vide pour tout le monde** → vérifie que
`COLLABORATEURS_FOLDER_ID` (ou `GOOGLE_DRIVE_FOLDER_ID` + sous-dossier
`collaborateurs`) est correct et partagé.
