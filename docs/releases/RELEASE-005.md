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

## Extraction intelligente du PDF

L’extraction visuelle par IA est facultative. Contrairement à l’extracteur OCR
à règles, elle lit la mise en page du PDF et renvoie une structure imposée :

- identification de la facture, dates et bon de commande ;
- fournisseur et acheteur, ICE, IF, RC, adresses et coordonnées ;
- chaque ligne avec référence, désignation, quantité, unité, prix, remise et TVA ;
- sous-total, remise globale, livraison, HT, TVA, TTC et montant à payer ;
- mode et conditions de paiement, RIB/IBAN et SWIFT/BIC.

Elle utilise Ollama et le modèle visuel local `qwen2.5vl:3b`, sans clé API ni
abonnement. Elle peut être utilisée facture par facture depuis le bouton
**Analyser le PDF par IA**. Pour les nouveaux imports, définir
`PURCHASES_AI_ENABLED=True` puis `PURCHASES_EXTRACTION_ENGINE=ollama`; la valeur
par défaut `rules` conserve le comportement OCR à règles. Une file PostgreSQL
et le conteneur `ai-worker` exécutent les analyses en arrière-plan. Une tâche
interrompue est remise en attente au redémarrage du worker.

Le PDF reste dans le réseau Docker du VPS : ses pages sont converties en images
par PAB puis envoyées au conteneur Ollama local.
Après l’analyse, la facture repasse toujours à l’état **À vérifier** et les
lignes ne sont jamais marquées comme vérifiées automatiquement.

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

Le moteur local se prépare avec :

```bash
docker compose --profile local-ai up -d ollama
docker compose --profile local-ai exec ollama ollama pull qwen2.5vl:3b
docker compose --profile local-ai up -d ai-worker
```

Configuration minimale dans `.env` :

```dotenv
PURCHASES_AI_ENABLED=True
OLLAMA_API_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5vl:3b
PURCHASES_EXTRACTION_ENGINE=rules
```

Conserver `rules` pendant la phase de comparaison. Le passage à `ollama` pour
les imports automatiques ne doit intervenir qu’après validation d’un échantillon
représentatif de factures.
