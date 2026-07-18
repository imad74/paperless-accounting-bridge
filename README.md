# Paperless Accounting Bridge (PAB)

## Version

v0.1.0-alpha

## Description

Paperless Accounting Bridge (PAB) est une application Django permettant de gérer le cycle de vie documentaire autour de Paperless-ngx.

## Fonctionnalités prévues

- Import intelligent
- Renommage automatique
- Numérotation documentaire
- Détection des doublons
- Historique des imports
- Intégration avec Paperless via API
- Tableau de bord
- Workflow documentaire

## Démarrage rapide

### Avec Docker Compose

1. Copiez le fichier d’environnement :
   ```bash
   cp .env.example .env
   ```
2. Démarrez les services :
   ```bash
   docker compose up --build
   ```
3. Ouvrez l’application sur :
   - http://localhost:8000/
   - http://localhost:8000/health/

### Sans Docker

```bash
cd backend
pip install -r ../requirements.txt
python manage.py migrate
python manage.py runserver
```

## Auteur

Imad74