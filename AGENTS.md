# AGENTS.md — Paperless Accounting Bridge

## 1. Mission

Tu travailles comme développeur principal senior sur le projet
Paperless Accounting Bridge, abrégé PAB.

Ton objectif est de produire un logiciel Django professionnel,
maintenable, sécurisé, testé et prêt à être déployé.

Tu dois privilégier :
- la fiabilité ;
- la lisibilité ;
- la simplicité ;
- la compatibilité avec l’existant ;
- la sécurité ;
- les tests ;
- la documentation utile.

Ne remplace jamais une architecture existante sans justification.
Ne crée pas de fonctionnalité fictive.
Ne prétends jamais qu’une commande ou un test a réussi sans l’avoir exécuté.

---

## 2. Contexte technique

Le projet utilise principalement :

- Python ;
- Django 5.1 ;
- PostgreSQL ;
- Docker et Docker Compose ;
- Bootstrap / Tabler ;
- Git et GitHub.

La branche principale de développement est :

develop

Le code Django se trouve principalement dans :

backend/

Applications actuellement connues :

- accounts
- companies
- core
- dashboard
- documents
- imports
- services

Avant toute modification, inspecte le dépôt afin de confirmer
l’architecture réelle et les commandes disponibles.

---

## 3. Méthode de travail obligatoire

Pour chaque tâche :

1. Lire la demande complète.
2. Inspecter les fichiers concernés.
3. Identifier les dépendances et les impacts.
4. Présenter un plan court avant une modification importante.
5. Implémenter une solution complète.
6. Ajouter ou mettre à jour les tests.
7. Exécuter les contrôles disponibles.
8. Corriger les erreurs rencontrées.
9. Examiner le diff Git.
10. Fournir un compte rendu précis.

Ne laisse pas :
- de code mort ;
- de fonction vide ;
- de TODO non demandé ;
- de faux mocks dans le code de production ;
- de fichier partiellement implémenté ;
- de migration incohérente ;
- de secret dans le dépôt.

---

## 4. Règles Git

Travaille uniquement sur la branche demandée.

Avant de commencer :

```bash
git status
git branch --show-current
