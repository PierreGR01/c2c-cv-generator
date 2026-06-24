# CV Generator Camptocamp — Prise en main

Générer des CVs PDF à la charte Camptocamp, ciblés sur un appel d'offre, en quelques clics.

---

## Ce dont tu as besoin

| Quoi | Où |
|---|---|
| **Docker Desktop** | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) — installe-le une seule fois |
| **Le code** | Demande l'accès au repo GitHub à Pierre |
| **Les credentials** | LastPass → note sécurisée **`CV Generator – .env`** |

---

## Installation (une seule fois)

### 1. Installe Docker Desktop

Télécharge et installe Docker Desktop. Au premier lancement, il te demandera peut-être d'activer WSL2 — accepte. Redémarre si nécessaire.

> Tu n'auras plus besoin de toucher à Docker après ça. C'est juste un moteur qui tourne en arrière-plan.

### 2. Récupère le code

Clone le dépôt ou télécharge-le en ZIP depuis GitHub, puis décompresse-le où tu veux sur ton poste.

### 3. Configure les credentials

- Ouvre LastPass → Notes sécurisées → **`CV Generator – .env`**
- Copie le contenu de la note
- Dans le dossier `cv-generator/`, ouvre le fichier **`.env`** déjà présent et remplace son contenu par ce que tu viens de copier, puis enregistre

> ⚠️ Ce fichier contient des clés d'accès — ne le partage jamais, ne le committe jamais.

---

## Utilisation au quotidien

### Lancer le service

**Windows** — double-clique sur `lancer.bat`

**Mac** — double-clique sur `lancer.sh`
_(premier lancement : clic droit → Ouvrir, pour contourner Gatekeeper)_

Une fenêtre de terminal s'ouvre. La **première fois**, Docker télécharge et construit l'image (~2-3 min). Les fois suivantes c'est quasi instantané.

Le navigateur s'ouvre automatiquement sur **http://localhost:8000**.

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

Les fiches collaborateurs sont des fichiers YAML stockés sur **Google Drive**, dans le dossier partagé de l'équipe. Le service les lit directement — pas besoin de toucher au code.

Pour ajouter un collaborateur : dépose un nouveau fichier `.yaml` dans le dossier `collaborateurs/` sur Drive. Il apparaîtra dans l'interface au prochain chargement (cache de 5 min).

Pour modifier un collaborateur : édite son fichier `.yaml` sur Drive.

---

## Mettre à jour le service

```bash
git pull
```

Puis relance `lancer.bat` / `lancer.sh` — Docker reconstruira l'image si nécessaire.

---

## Problèmes courants

**"Docker n'est pas lancé"**
→ Ouvre Docker Desktop depuis le menu Démarrer / Applications, attends que l'icône soit stable.

**L'interface charge mais la liste de collaborateurs est vide**
→ Vérifie que ton fichier `.env` existe bien à la racine du dossier et que son contenu est correct (pas de retour à la ligne parasite dans le JSON).

**Le PDF dépasse une page**
→ Réduis le nombre de projets max dans les options (essaie 3).
