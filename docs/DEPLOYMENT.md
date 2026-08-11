# Déploiement et sécurité

Ce guide couvre le déploiement de Paperless Accounting Bridge après la
Release 003. Les exemples utilisent Docker Compose ; adaptez le reverse proxy,
le stockage et l’orchestrateur à votre infrastructure.

## 1. Secrets à renouveler avant la production

Le fichier `.env` a été suivi dans l’historique Git à partir du commit
`371a10a`. Le retirer de la version courante empêche une nouvelle exposition,
mais n’efface pas les anciennes révisions. Toutes les valeurs qui y ont figuré
doivent donc être considérées comme compromises.

Avant le déploiement :

1. révoquez tout jeton GitHub ou jeton tiers exposé et créez-en un nouveau ;
2. générez une nouvelle `DJANGO_SECRET_KEY` aléatoire d’au moins 50 caractères ;
3. changez le mot de passe PostgreSQL dans la base et dans le gestionnaire de
   secrets ;
4. vérifiez qu’aucun secret réel ne se trouve dans `.env.example`, les logs ou
   l’historique des commandes ;
5. conservez les nouvelles valeurs dans un gestionnaire de secrets, jamais
   dans Git.

Une clé Django peut être générée dans un environnement Python contenant
Django :

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Ne copiez pas la nouvelle valeur dans un ticket, une Pull Request ou un canal
de discussion. La rotation des identifiants externes est une action opérateur
et ne peut pas être réalisée par une modification du dépôt.

## 2. Variables de production

Créez un fichier `.env` non versionné ou injectez les variables depuis votre
gestionnaire de secrets :

```dotenv
DJANGO_SECRET_KEY=<valeur-aléatoire-d-au-moins-50-caractères>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=pab.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://pab.example.com
DB_NAME=paperless
DB_USER=paperless
DB_PASSWORD=<mot-de-passe-unique>
DB_HOST=db
DB_PORT=5432
WEB_BIND_ADDRESS=127.0.0.1
WEB_HOST_PORT=8010
DB_BIND_ADDRESS=127.0.0.1
DB_HOST_PORT=5433
PAB_UID=1000
PAB_GID=1000
DJANGO_TRUST_PROXY_HEADERS=True
SCAN_INPUT_HOST_PATH=/opt/pab/incoming
PAPERLESS_CONSUME_HOST_PATH=/opt/paperless/consume
```

Le worker de scan est isolé dans le profil `scan-import` et reste arrêté par
défaut. Sur le VPS OVH actuel, Paperless occupe déjà le port public `8000` ;
PAB écoute donc uniquement sur `127.0.0.1:8010`. Le port PostgreSQL hôte `5433`
est également limité à la boucle locale. Les ports internes aux conteneurs
restent respectivement `8000` et `5432`.

`PAB_UID` et `PAB_GID` doivent correspondre aux valeurs retournées par
`id -u imad` et `id -g imad`. L’image crée ainsi son utilisateur non privilégié
avec les mêmes identifiants que le propriétaire de `/opt/pab/incoming` et de
`/opt/paperless/consume`, sans rendre ces dossiers accessibles en écriture à
tous les utilisateurs.

Avant l’activation du worker, Syncthing doit transférer exclusivement les scans
bruts de `F:/scan` vers `/opt/pab/incoming`. Aucun partage ne doit encore les
livrer directement dans `/opt/paperless/consume`. La procédure complète figure
dans
[`releases/RELEASE-004.md`](releases/RELEASE-004.md).

Lorsque `DJANGO_DEBUG=False`, l’application active par défaut la redirection
HTTPS, les cookies sécurisés et HSTS. N’activez
`DJANGO_TRUST_PROXY_HEADERS=True` que derrière un reverse proxy maîtrisé qui
remplace l’en-tête `X-Forwarded-Proto`.

Les options suivantes permettent une adaptation explicite :

- `DJANGO_SECURE_SSL_REDIRECT` ;
- `DJANGO_CSRF_COOKIE_SECURE` ;
- `DJANGO_SESSION_COOKIE_SECURE` ;
- `DJANGO_SECURE_HSTS_SECONDS` ;
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` ;
- `DJANGO_SECURE_HSTS_PRELOAD`.

Une valeur booléenne doit être `true`, `false`, `1`, `0`, `yes`, `no`, `on`
ou `off`. Une valeur invalide arrête explicitement le démarrage.

## 3. Préparation des données existantes

Avant d’activer les écrans métier, chaque superutilisateur qui doit utiliser
l’application doit disposer d’une appartenance active avec le rôle `ADMIN` :

1. connectez-vous à l’administration Django ;
2. ouvrez **Company memberships** ;
3. créez une appartenance par couple utilisateur–société ;
4. sélectionnez le rôle `ADMIN` et cochez l’appartenance active ;
5. vérifiez qu’au moins un administrateur actif existe par société.

La stratégie de migration des anciens compteurs est décrite dans
[`releases/RELEASE-003-NUMBERING.md`](releases/RELEASE-003-NUMBERING.md).
Une ambiguïté doit être corrigée manuellement après la migration
`documents.0002` ; elle ne doit jamais être devinée silencieusement.

## 4. Sauvegarde et contrôles avant déploiement

Créez une sauvegarde PostgreSQL testée avant toute migration. Les commandes de
production chargent uniquement `docker-compose.yml` afin d’exclure l’override
de développement :

```bash
docker compose -f docker-compose.yml exec -T db pg_dump -U paperless -Fc paperless > paperless-before-release-003.dump
```

Construisez ensuite l’image et exécutez les contrôles avec les vraies variables
de production :

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml build --pull
docker compose -f docker-compose.yml run --rm web python backend/manage.py check
docker compose -f docker-compose.yml run --rm web python backend/manage.py check --deploy
docker compose -f docker-compose.yml run --rm web python backend/manage.py makemigrations --check --dry-run
docker compose -f docker-compose.yml run --rm web python backend/manage.py migrate --plan
docker compose -f docker-compose.yml run --rm web python backend/manage.py test accounts companies documents imports
docker compose -f docker-compose.yml run --rm web python backend/manage.py collectstatic --noinput
```

`check --deploy` doit s’exécuter avec `DJANGO_DEBUG=False` et la véritable clé
de production. Aucun avertissement de sécurité ne doit être ignoré sans une
justification documentée.

## 5. Déploiement

Appliquez les migrations une seule fois avant de démarrer les nouvelles
instances :

```bash
docker compose -f docker-compose.yml run --rm web python backend/manage.py migrate --noinput
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
```

L’image utilise Gunicorn avec un utilisateur non privilégié. Le fichier
`docker-compose.override.yml`, chargé uniquement par les commandes de
développement sans option `-f`, remplace cette commande par `runserver` et
monte le code source. En production, conservez la commande par défaut de
l’image derrière un reverse proxy HTTPS.

Vérifiez ensuite :

```bash
curl --fail https://pab.example.com/health/
```

Contrôlez manuellement la connexion, la sélection de société, les permissions
des quatre rôles, la liste documentaire et la génération d’un numéro.

Après validation du partage Syncthing et uniquement lorsque
`/opt/pab/incoming` est vide, démarrez le worker :

```bash
docker compose -f docker-compose.yml --profile scan-import up -d scan-worker
docker compose -f docker-compose.yml --profile scan-import ps
docker compose -f docker-compose.yml --profile scan-import logs --tail=100 scan-worker
```

Le journal doit contenir `Surveillance automatique des scans démarrée.` avant
le dépôt du PDF pilote.

## 6. Retour arrière

1. arrêtez les nouvelles instances sans supprimer les volumes ;
2. redéployez l’image applicative précédemment validée ;
3. si une migration incompatible a été appliquée, restaurez la sauvegarde dans
   une base vide ou selon la procédure validée par l’administrateur PostgreSQL ;
4. relancez `check`, le test `/health/` et les contrôles fonctionnels ;
5. conservez les logs et documentez la cause avant une nouvelle tentative.

N’utilisez jamais `docker compose down -v` pendant un retour arrière : cette
commande supprime les volumes et peut détruire la base de données.
