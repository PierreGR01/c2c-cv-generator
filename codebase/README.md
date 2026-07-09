# C2C Tenders App

Application interne Camptocamp pour générer des CV PDF à la charte Camptocamp,
ciblés sur un appel d'offre, à partir de fiches maîtres collaborateurs stockées
sur Google Drive. Permet aussi l'ingestion de fiches "fin de projet" et
l'édition directe des fiches maîtres, avec authentification OAuth par
utilisateur (les permissions réelles sont gouvernées par les ACL Drive).

- **Installation & utilisation au quotidien** → [`SETUP.md`](SETUP.md)
- **Configuration Google Cloud (admin, une seule fois)** → [`SETUP-OAUTH.md`](SETUP-OAUTH.md)

## Stack

- [FastAPI](https://fastapi.tiangolo.com/) (Python) — API + service de fichiers statiques
- [Typst](https://typst.app/) — moteur de rendu PDF (gabarit [`engine/cv-template.typ`](engine/cv-template.typ))
- Frontend statique vanilla JS ([`static/index.html`](static/index.html))
- Google Drive API + Gmail API (OAuth utilisateur) — stockage des données et notifications
