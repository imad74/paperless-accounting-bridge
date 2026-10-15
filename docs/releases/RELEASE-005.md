# RELEASE-005 — Base des factures d’achat

## Objectif

Structurer dans PAB les factures d’achat déjà archivées dans Paperless, y
compris chaque ligne d’article ou de service, sans modifier le PDF source.

## Modèle de données

- fournisseur rattaché à une société PAB ;
- facture liée à son identifiant Paperless et, lorsqu’il existe, au document
  PAB correspondant ;
- lignes détaillées : référence, désignation, quantité, unité, prix unitaire,
  remise, taux et montant de TVA, HT et TTC ;
- ventilation de TVA calculée par taux ;
- texte OCR, méthode et niveau de confiance de l’extraction ;
- auteur et date de validation.

## Flux de contrôle

1. L’utilisateur saisit l’identifiant Paperless.
2. PAB lit le document et son texte OCR avec le jeton API côté serveur.
3. L’extracteur conservateur propose les champs et les lignes reconnues.
4. Un opérateur corrige et marque chaque ligne comme vérifiée.
5. Un administrateur ou gestionnaire valide la facture.

La validation est refusée si le fournisseur, le numéro ou la date manquent,
si une ligne n’est pas vérifiée, ou si les sommes des lignes ne correspondent
pas aux totaux HT, TVA et TTC avec une tolérance de deux centimes.

## Limites assumées

Les présentations des fournisseurs étant très différentes, l’extraction OCR
reste une proposition. Les PDF Paperless ne sont ni modifiés ni remplacés et
aucune donnée extraite n’est réputée comptable avant validation humaine.

## Déploiement

Après sauvegarde de PostgreSQL :

```bash
python backend/manage.py migrate
python backend/manage.py check
```

Le compte API Paperless configuré dans `PAPERLESS_API_TOKEN` doit disposer du
droit de lecture sur les documents à importer.
