# Release 004 - Nommage et marquage des PDF scannés

## Statut

- **État** : en développement
- **Branche** : `agent/release-004-pdf-filenames`
- **Premier lot** : stockage et nommage des PDF

## Objectif

Chaque document créé depuis l’interface reçoit deux identifiants distincts :

- le numéro métier existant, par exemple `FN-DEMO-000003-2026` ;
- un nom de fichier technique global constitué de huit chiffres, par exemple
  `00000001.pdf`.

Le nom technique est imprimé en haut à droite de chaque page du PDF scanné.

## Règles fonctionnelles

1. seuls les fichiers PDF sont acceptés ;
2. la séquence est globale à toutes les sociétés afin d’éviter les collisions ;
3. les noms vont de `00000001.pdf` à `99999999.pdf` ;
4. la réservation du nom est atomique sous PostgreSQL ;
5. un fichier déjà connu par son SHA-256 est refusé ;
6. le nom est imprimé sur toutes les pages, y compris les pages pivotées ;
7. le fichier marqué est conservé dans le stockage média ;
8. le téléchargement passe par une vue protégée et limitée à la société active ;
9. le nom d’origine reste conservé dans `original_filename` ;
10. un PDF peut être ajouté à une fiche historique qui n’en possède pas, sans
    modifier son numéro métier ;
11. une fois associé, le PDF n’est pas remplaçable depuis le formulaire métier.

## Sécurité et exploitation

- la taille maximale est configurée par `DOCUMENT_PDF_MAX_BYTES` et vaut
  25 Mio par défaut ;
- les PDF chiffrés ou protégés par mot de passe sont refusés ;
- le répertoire média n’est pas exposé directement par Django ;
- le volume `media_data` doit être inclus dans les sauvegardes et restaurations.

## Import automatique depuis le scanner

Le worker optionnel `scan-worker` applique le flux suivant :

```text
scanner
  -> serveur Windows : F:/scan
  -> Syncthing
  -> VPS OVH : /opt/pab/incoming
  -> PAB scan-worker sur le VPS
  -> VPS OVH : /opt/paperless/consume
  -> Paperless-ngx
```

Le worker s’exécute sur le VPS, au même endroit que Paperless-ngx. Il ne doit
jamais être activé tant que Syncthing livre aussi les scans bruts directement
dans `/opt/paperless/consume`. Sinon Paperless et PAB resteraient deux
consommateurs concurrents du même flux.

Pour chaque PDF stable, le worker :

1. déplace atomiquement le fichier dans `.pab-processing` ;
2. sélectionne l’unique société active et l’unique type actif ;
3. refuse les doublons selon le SHA-256 du scan original ;
4. génère le numéro métier et le nom technique sur huit chiffres ;
5. imprime le nom technique sur chaque page ;
6. crée la fiche `Document` et conserve le PDF dans `media_data` ;
7. crée une entrée transactionnelle dans `PaperlessOutbox` ;
8. copie atomiquement le PDF vers le dossier de consommation Paperless du VPS ;
9. journalise le résultat dans `ImportJob`.

Un PDF invalide ou dupliqué est déplacé dans
`/opt/pab/incoming/.pab-errors`. Syncthing propage ce sous-répertoire vers le
serveur Windows. Une panne du dossier Paperless ne renumérote pas le document :
l’outbox réessaie la remise au cycle suivant.

### Activation différée

1. arrêter temporairement l’arrivée de nouveaux scans et attendre la fin de la
   synchronisation actuelle ;
2. créer les répertoires PAB sur le VPS avec le propriétaire du service
   Syncthing :

   ```bash
   sudo install -d -o imad -g imad -m 0775 /opt/pab
   sudo install -d -o imad -g imad -m 0775 /opt/pab/incoming
   ```

3. retirer ou mettre en pause dans Syncthing tout partage qui livre encore
   `F:/scan` directement dans `/opt/paperless/consume`, sans supprimer les
   fichiers locaux ;
4. créer un partage Syncthing, par exemple `pab-incoming`, avec les chemins
   suivants :

   - serveur Windows : `F:/scan` ;
   - VPS OVH : `/opt/pab/incoming` ;
   - type du dossier sur les deux appareils : **Send & Receive**.

   PAB supprime le scan d’entrée après son enregistrement. Le mode
   **Send & Receive** permet à Syncthing de propager cette suppression vers
   `F:/scan`. Les modes **Send Only** ou **Receive Only** ne conviennent pas à
   cette file de transit.

5. conserver sur le VPS le montage Paperless existant. Pour une installation
   Docker standard, le chemin hôte est monté ainsi :

   ```yaml
   - /opt/paperless/consume:/usr/src/paperless/consume
   ```

6. activer la suppression des doublons de consommation Paperless :

   ```dotenv
   PAPERLESS_CONSUMER_DELETE_DUPLICATES=true
   ```

7. relever l’UID et le GID du propriétaire des dossiers, puis configurer le
   `.env` de PAB sur le VPS :

   ```bash
   id -u imad
   id -g imad
   ```

   ```dotenv
   WEB_BIND_ADDRESS=127.0.0.1
   WEB_HOST_PORT=8010
   DB_BIND_ADDRESS=127.0.0.1
   DB_HOST_PORT=5433
   PAB_UID=1000
   PAB_GID=1000
   SCAN_INPUT_HOST_PATH=/opt/pab/incoming
   PAPERLESS_CONSUME_HOST_PATH=/opt/paperless/consume
   SCAN_STABILITY_SECONDS=10
   SCAN_POLL_SECONDS=5
   SCAN_DEFAULT_COMPANY_CODE=
   SCAN_DEFAULT_DOCUMENT_TYPE_CODE=
   ```

   Remplacer `1000` par les valeurs réellement retournées par `id`. Les deux
   codes restent vides tant qu’il existe exactement une société active
   (`DELIGHT EVENT`) et un type actif (`FN`). Si plusieurs choix sont créés,
   le worker s’arrête explicitement jusqu’à la configuration des codes.

8. appliquer les migrations et démarrer le profil :

   ```bash
   docker compose --profile scan-import build web scan-worker
   docker compose run --rm web python backend/manage.py migrate --noinput
   docker compose --profile scan-import up -d web scan-worker
   docker compose --profile scan-import logs -f scan-worker
   ```

Le chemin interne `/usr/src/paperless/consume` et l’usage d’un bind mount sont
ceux documentés par Paperless-ngx :
https://docs.paperless-ngx.com/setup/#docker-compose-install.

Le comportement des modes **Send & Receive**, **Send Only** et **Receive Only**
est documenté par Syncthing :
https://docs.syncthing.net/users/foldertypes.html.

## Critères d’acceptation

- deux créations successives produisent `00000001.pdf` puis `00000002.pdf` ;
- des créations concurrentes ne produisent jamais le même nom ;
- le nom est visible en haut à droite de chaque page rendue ;
- un utilisateur autorisé peut ouvrir le PDF de sa société ;
- un utilisateur d’une autre société reçoit une réponse 404 ;
- les migrations s’appliquent sur les documents historiques ;
- les contrôles Django et tous les tests réussissent sous PostgreSQL.

## Commandes de validation

```bash
docker compose build
docker compose run --rm web python backend/manage.py check
docker compose run --rm web python backend/manage.py makemigrations --check --dry-run
docker compose run --rm web python backend/manage.py migrate --plan
docker compose run --rm web python backend/manage.py test documents
docker compose run --rm web python backend/manage.py test imports
docker compose run --rm web python backend/manage.py test accounts companies documents imports
```
