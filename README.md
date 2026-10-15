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
- Base structurée des factures d’achat et de leurs lignes

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

Le fichier `.env` est strictement local. Ne le commitez jamais et remplacez
toutes les valeurs de développement avant un déploiement.

L’import automatique des scans est fourni par le profil Docker optionnel
`scan-import`. Sur le VPS, Syncthing livre les scans bruts dans
`/opt/pab/incoming`, puis PAB remet les PDF marqués dans
`/opt/paperless/consume`. Le worker doit être activé uniquement après avoir
supprimé tout flux direct concurrent entre ces deux étapes. Consultez
[`docs/releases/RELEASE-004.md`](docs/releases/RELEASE-004.md).

La page **Recherche exacte Paperless** accepte jusqu’à 100 titres ou noms de
fichiers, un par ligne. Elle interroge les filtres exacts de l’API Paperless et
affiche séparément les correspondances, les doublons exacts et les noms
absents. Configurez un jeton API Paperless en dehors du dépôt :

```dotenv
PAPERLESS_API_URL=https://archive.example.com
PAPERLESS_API_TOKEN=replace-with-a-paperless-token
PAPERLESS_API_TIMEOUT=15
```

Le jeton reste côté serveur et ne doit jamais être commité. Utilisez de
préférence le jeton d’un compte Paperless dédié disposant uniquement des
droits de lecture nécessaires.

La rubrique **Factures d’achat** importe un document Paperless par son
identifiant, conserve son texte OCR et propose les données d’en-tête, les
totaux et les lignes d’articles ou de services. Chaque ligne doit être
contrôlée. La validation comptable est bloquée tant que les lignes ne sont pas
marquées comme vérifiées et que leurs totaux HT, TVA et TTC ne correspondent
pas à la facture.

Docker Compose charge automatiquement `docker-compose.override.yml` en
développement afin de monter le code et d’utiliser `runserver`. Le déploiement
doit charger uniquement `docker-compose.yml`, qui conserve la commande Gunicorn
de l’image.

### Sans Docker

```bash
cd backend
pip install -r ../requirements.txt
python manage.py migrate
python manage.py runserver
```

## Déploiement et sécurité

Consultez le [guide de déploiement](docs/DEPLOYMENT.md) avant toute mise en
production. Il décrit les variables obligatoires, la rotation des secrets,
les sauvegardes, les contrôles Django et la procédure de retour arrière.

## Auteur

Imad74
