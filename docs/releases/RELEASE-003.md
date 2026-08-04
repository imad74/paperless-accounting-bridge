# Release 003 — Gestion des accès, des sociétés et du référentiel documentaires

## 1. Statut

- **Version cible** : Release 003
- **Statut** : Implémentation terminée — rotation des secrets requise avant déploiement
- **Branche cible** : `develop`
- **Périmètre** : authentification, rattachement utilisateur–société, permissions, types documentaires, numérotation et interface associée

## 2. Contexte

Paperless Accounting Bridge dispose actuellement :

- de l’authentification standard de Django via l’administration ;
- d’un modèle `Company` et d’un CRUD HTML non protégé ;
- des modèles `DocumentType`, `Document` et `DocumentCounter` ;
- d’un service initial de numérotation ;
- d’une interface Bootstrap / Tabler ;
- d’un modèle `ImportJob`.

La version actuelle ne possède toutefois ni relation entre utilisateurs et sociétés, ni contrôle d’accès applicatif, ni cloisonnement des données par société. Les parcours de gestion des documents et des types documentaires sont également incomplets.

La Release 003 doit établir un socle multi-société sécurisé et rendre le référentiel documentaire administrable sans remettre en cause l’architecture Django existante.

## 3. Objectifs

La Release 003 doit :

1. imposer l’authentification sur les écrans métier ;
2. rattacher les utilisateurs à une ou plusieurs sociétés ;
3. définir des rôles applicatifs simples et explicites ;
4. empêcher tout accès croisé non autorisé entre sociétés ;
5. sécuriser le CRUD des sociétés ;
6. fournir la gestion applicative des types documentaires ;
7. fiabiliser la numérotation des documents ;
8. intégrer les nouvelles fonctions dans l’interface Tabler existante ;
9. fournir les migrations et tests nécessaires.

## 4. Hors périmètre

Ne font pas partie de cette release :

- l’intégration complète à l’API Paperless-ngx ;
- l’import automatique de fichiers ;
- l’OCR ;
- le rapprochement comptable ;
- les rapports avancés ;
- la refonte du thème Tabler ;
- le remplacement du modèle utilisateur Django sans nécessité démontrée ;
- une API REST publique.

## 5. Principes d’architecture

### 5.1 Modèle utilisateur

La Release 003 conserve le modèle utilisateur Django standard.

Un modèle d’association explicite doit porter la relation entre utilisateur et société. Cette approche évite une migration risquée vers un modèle utilisateur personnalisé alors que le projet utilise déjà `settings.AUTH_USER_MODEL` dans plusieurs modèles.

### 5.2 Appartenance à une société

Créer un modèle `CompanyMembership` dans l’application `accounts` avec au minimum :

- `user` : clé étrangère vers `settings.AUTH_USER_MODEL` ;
- `company` : clé étrangère vers `Company` ;
- `role` : rôle de l’utilisateur dans la société ;
- `active` : appartenance active ou suspendue ;
- `created_at` ;
- `updated_at`.

La paire `(user, company)` doit être unique.

Les rôles initiaux sont :

- `ADMIN` : gestion de la société, des membres et du référentiel documentaire ;
- `MANAGER` : gestion des documents et des types documentaires, sans gestion des membres ;
- `OPERATOR` : consultation et traitement des documents autorisés ;
- `VIEWER` : consultation uniquement.

Les libellés affichés dans l’interface doivent être en français.

### 5.3 Société active

Lorsqu’un utilisateur appartient à plusieurs sociétés, l’application doit conserver une société active dans la session.

Règles :

- une société inactive ne peut pas devenir active dans la session ;
- une appartenance inactive ne donne aucun accès ;
- si une seule société est disponible, elle est sélectionnée automatiquement ;
- si plusieurs sociétés sont disponibles et qu’aucune n’est sélectionnée, l’utilisateur est dirigé vers un sélecteur ;
- la valeur stockée en session doit être revalidée à chaque utilisation.

### 5.4 Autorisations

Les vues métier doivent utiliser des mixins ou services communs afin d’éviter la duplication des contrôles.

Les contrôles doivent porter à la fois sur :

- l’authentification ;
- l’appartenance active ;
- le rôle ;
- la société concernée par l’objet.

Les contrôles de l’interface ne remplacent jamais les contrôles côté serveur.

## 6. Exigences fonctionnelles

### 6.1 Authentification

- Toutes les vues métier exigent un utilisateur authentifié.
- L’endpoint `/health/` reste public.
- La connexion et la déconnexion utilisent les vues d’authentification Django.
- La barre de navigation affiche les informations de l’utilisateur connecté.
- Le lien de déconnexion doit être fonctionnel.
- Les redirections après connexion et déconnexion doivent être cohérentes.

### 6.2 Gestion des sociétés

- La liste des sociétés est limitée aux sociétés accessibles à l’utilisateur.
- Un administrateur applicatif autorisé peut créer une société.
- Seuls les rôles autorisés peuvent modifier une société.
- La suppression physique d’une société possédant des documents est interdite.
- La désactivation doit être privilégiée à la suppression.
- La recherche et la pagination existantes sont conservées.
- Les messages et libellés de l’interface sont harmonisés en français.

### 6.3 Gestion des membres

Un administrateur de société peut :

- consulter les membres de sa société ;
- ajouter une appartenance pour un utilisateur existant ;
- modifier le rôle d’un membre ;
- suspendre ou réactiver une appartenance ;
- retirer une appartenance lorsqu’elle n’est plus nécessaire.

Un utilisateur ne peut jamais gérer les membres d’une société à laquelle il n’appartient pas avec un rôle suffisant.

Le système doit empêcher la suppression ou la suspension du dernier administrateur actif d’une société.

### 6.4 Types documentaires

Fournir les écrans suivants :

- liste des types documentaires ;
- création ;
- modification ;
- activation et désactivation.

Les champs administrables sont :

- code ;
- nom ;
- préfixe ;
- description ;
- réinitialisation annuelle ;
- statut actif.

Règles :

- le code est obligatoire, normalisé et unique ;
- le préfixe est obligatoire, normalisé et unique ;
- un type utilisé par des documents ne doit pas être supprimé physiquement ;
- un type inactif ne peut pas être utilisé pour un nouveau document ;
- l’accès à la gestion dépend du rôle.

### 6.5 Documents

La liste des documents doit :

- être montée dans le routage principal ;
- exiger l’authentification ;
- être limitée à la société active ;
- permettre une recherche simple ;
- permettre un filtrage par type, statut et période ;
- utiliser la pagination ;
- afficher les informations essentielles sans exposer les champs techniques.

Le formulaire de document ne doit pas demander directement les champs techniques générés ou calculés, notamment :

- le numéro ;
- le nom de fichier stocké ;
- l’empreinte SHA-256 ;
- l’auteur ;
- les horodatages.

La création d’un document doit déléguer la génération du numéro au service métier.

### 6.6 Numérotation

La portée du compteur est définie par :

- la société ;
- le type documentaire ;
- l’année lorsque `yearly_reset=True`.

Le modèle `DocumentCounter` doit donc être relié à `Company`.

Contraintes :

- unicité du compteur selon sa portée ;
- génération atomique ;
- résistance aux créations concurrentes ;
- aucun numéro dupliqué ;
- aucune réutilisation silencieuse d’un numéro ;
- prise en compte réelle de `yearly_reset`.

Format initial :

```text
<PREFIX>-<NUMERO_SUR_6_CHIFFRES>-<ANNEE>
```

Exemple :

```text
FN-000001-2026
```

Si plusieurs sociétés peuvent employer le même préfixe, le code société doit être intégré au format ou l’unicité de `Document.number` doit être adaptée. Le choix final doit être documenté avant la migration.

Le format retenu et la procédure de migration sont documentés dans
[`RELEASE-003-NUMBERING.md`](RELEASE-003-NUMBERING.md). Le code société est
intégré au numéro afin de conserver l’unicité globale de `Document.number`.

## 7. Matrice minimale des permissions

| Action | ADMIN | MANAGER | OPERATOR | VIEWER |
|---|---:|---:|---:|---:|
| Consulter la société | Oui | Oui | Oui | Oui |
| Modifier la société | Oui | Non | Non | Non |
| Gérer les membres | Oui | Non | Non | Non |
| Consulter les types | Oui | Oui | Oui | Oui |
| Gérer les types | Oui | Oui | Non | Non |
| Consulter les documents | Oui | Oui | Oui | Oui |
| Créer ou modifier un document | Oui | Oui | Oui | Non |
| Archiver un document | Oui | Oui | Non | Non |

Cette matrice doit être centralisée dans le code et couverte par des tests.

## 8. Interface utilisateur

L’interface doit respecter le shell Tabler existant :

- `page`, `page-wrapper`, `page-body` et `container-xl` ;
- `page-header` et `page-title` ;
- cartes Tabler ;
- tableaux responsives ;
- formulaires Bootstrap ;
- badges pour les états ;
- messages Django rendus sous forme d’alertes.

Exigences complémentaires :

- interface en français ;
- utilisateur réel dans la barre de navigation ;
- sélecteur de société accessible ;
- liens latéraux fonctionnels ;
- état actif du menu calculé selon la route ;
- icônes homogènes ;
- aucun lien fictif `href="#"` pour une action disponible ;
- affichage clair des erreurs de formulaire ;
- conservation des filtres lors de la pagination.

## 9. Migrations et données existantes

Les migrations doivent :

1. créer `CompanyMembership` ;
2. ajouter la société au compteur documentaire ;
3. adapter la contrainte d’unicité des compteurs ;
4. préserver les documents et compteurs existants ;
5. prévoir une migration de données explicite si plusieurs sociétés existent déjà.

La migration de données ne doit pas deviner silencieusement la société d’un compteur ambigu.

Pour une installation existante, une stratégie documentée doit permettre :

- d’associer les superutilisateurs aux sociétés ;
- d’attribuer le rôle `ADMIN` ;
- d’affecter les anciens compteurs à une société ;
- de signaler toute donnée impossible à migrer automatiquement.

La procédure opérationnelle, la préparation des appartenances administrateur,
la rotation des secrets et le retour arrière sont décrits dans le
[`guide de déploiement`](../DEPLOYMENT.md).

## 10. Sécurité

- Toutes les mutations utilisent POST.
- La protection CSRF reste active.
- Les querysets sont filtrés avant toute récupération d’objet métier.
- Une tentative d’accès à un objet d’une autre société retourne 404 ou 403 selon la politique retenue.
- Les permissions ne reposent pas uniquement sur les éléments masqués dans les templates.
- Les secrets ne sont jamais ajoutés au dépôt.
- Le fichier `.env` ne doit plus être suivi et les secrets déjà exposés doivent être renouvelés.
- Les suppressions destructrices doivent être confirmées et protégées.

## 11. Tests obligatoires

### 11.1 Modèles

- unicité de `CompanyMembership` ;
- rôles valides ;
- comportement des appartenances inactives ;
- contraintes de `DocumentCounter` ;
- protection des types utilisés ;
- interdiction de suppression destructive d’une société.

### 11.2 Permissions

Pour chaque rôle :

- accès autorisé ;
- accès interdit ;
- accès à une société différente ;
- utilisateur sans appartenance ;
- utilisateur anonyme ;
- appartenance inactive.

### 11.3 Vues et formulaires

- connexion et déconnexion ;
- sélection de société ;
- CRUD autorisé ;
- validations ;
- filtres ;
- pagination ;
- messages ;
- protection CSRF ;
- méthodes HTTP non autorisées.

### 11.4 Numérotation

- premier numéro ;
- incrément ;
- séparation par société ;
- séparation par type ;
- changement d’année ;
- comportement sans réinitialisation annuelle ;
- type inactif ;
- code inconnu ;
- concurrence transactionnelle sous PostgreSQL.

### 11.5 Migrations

- `makemigrations --check --dry-run` ne produit aucun changement ;
- migration depuis l’état antérieur ;
- conservation des données existantes.

## 12. Critères d’acceptation

La Release 003 est acceptée lorsque :

1. aucune vue métier sensible n’est accessible anonymement ;
2. un utilisateur ne peut jamais consulter ou modifier les données d’une société non autorisée ;
3. les rôles respectent la matrice définie ;
4. un administrateur peut gérer les membres de sa société ;
5. les types documentaires sont administrables via l’interface ;
6. la numérotation est atomique, unique et séparée par société ;
7. `yearly_reset` est effectivement respecté ;
8. les migrations s’appliquent sur une base existante ;
9. tous les tests passent sous PostgreSQL ;
10. `python manage.py check` ne remonte aucune erreur ;
11. `python manage.py makemigrations --check --dry-run` ne détecte aucun écart ;
12. l’interface suit les conventions Tabler existantes et ne contient plus de navigation fictive pour le périmètre livré.

## 13. Découpage recommandé

### Lot 1 — Appartenances

- modèle `CompanyMembership` ;
- migration ;
- administration ;
- tests de modèle.

### Lot 2 — Contexte société et permissions

- société active en session ;
- mixins et services d’autorisation ;
- protection des vues existantes ;
- tests d’isolation.

### Lot 3 — Gestion des membres

- formulaires ;
- vues ;
- URLs ;
- templates ;
- tests de permissions.

### Lot 4 — Types documentaires

- formulaires ;
- vues ;
- URLs ;
- templates ;
- tests fonctionnels.

### Lot 5 — Numérotation

- évolution de `DocumentCounter` ;
- migration de données ;
- service transactionnel ;
- tests PostgreSQL.

### Lot 6 — Documents et interface

- routage ;
- liste filtrée ;
- formulaire sécurisé ;
- navigation Tabler ;
- tests de vues.

### Lot 7 — Durcissement

- exclusions Git et Docker ;
- rotation des secrets ;
- contrôles Django ;
- documentation de déploiement.

## 14. Commandes de validation

```bash
docker compose config
docker compose build
docker compose up -d db
docker compose run --rm web python backend/manage.py check
docker compose run --rm web python backend/manage.py check --deploy
docker compose run --rm web python backend/manage.py makemigrations --check --dry-run
docker compose run --rm web python backend/manage.py migrate --plan
docker compose run --rm web python backend/manage.py migrate
docker compose run --rm web python backend/manage.py test accounts companies documents
docker compose run --rm web python backend/manage.py collectstatic --noinput
```

Les tests de concurrence doivent être exécutés avec PostgreSQL et non uniquement avec SQLite.

## 15. Définition de terminé

Un lot est terminé lorsque :

- son code est complet ;
- ses migrations sont cohérentes ;
- ses tests sont présents et réussissent ;
- les contrôles Django réussissent ;
- l’interface est utilisable ;
- aucune permission n’est appliquée uniquement côté template ;
- le diff ne contient ni secret, ni fichier généré inutile, ni code mort ;
- la documentation utile est mise à jour.

