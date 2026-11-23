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

Les en-têtes de colonnes distinguent explicitement les prix HT des prix TTC.
Une seconde vérification compare la somme des lignes aux totaux de la facture :
si les montants lus correspondent au TTC au lieu du HT, ils sont reconvertis
avec le taux de TVA et signalés dans les notes de contrôle.
Une inversion des totaux HT et TTC proposée par le modèle est corrigée avant
cette réconciliation lorsque la relation `HT + TVA = TTC` permet de la prouver.

L'analyse inspecte explicitement le pied de page des factures marocaines pour
extraire la raison sociale, l'ICE, l'IF, la taxe professionnelle (TP), le RC et
l'adresse du fournisseur sans les confondre avec les données de l'acheteur.
Les montants de TVA imprimés sur chaque ligne sont prioritaires pour retrouver
le vrai taux fiscal et réconcilier les totaux HT, TVA et TTC. Les paiements déjà
effectués sont également distingués du montant restant à payer.
Les dates anglaises, françaises et numériques sont normalisées automatiquement
en ISO, y compris les libellés avec une heure comme `13 Jul 2022 12:58pm`.

Elle utilise Ollama et le modèle visuel local `qwen2.5vl:3b`, sans clé API ni
abonnement. Elle peut être utilisée facture par facture depuis le bouton
**Analyser le PDF par IA**. Pour les nouveaux imports, définir
`PURCHASES_AI_ENABLED=True` puis `PURCHASES_EXTRACTION_ENGINE=ollama`; la valeur
par défaut `rules` conserve le comportement OCR à règles. Une file PostgreSQL
et le conteneur `ai-worker` exécutent les analyses en arrière-plan. Une tâche
interrompue est remise en attente au redémarrage du worker.

Le PDF reste dans le réseau Docker du VPS : ses pages sont converties en images
par PAB puis envoyées au conteneur Ollama local.

Avec `PURCHASES_AI_AUTO_PROCESS=True`, chaque facture importée est placée dans
la file IA. Le résultat est intégré automatiquement : fournisseur créé ou
complété, lignes marquées comme intégrées et facture passée à l’état validé.
Les notes et anomalies de l’IA restent conservées pour la traçabilité. Sans ce
paramètre, le contrôle et la validation humaine historiques restent actifs.

L’état **Achats détaillés par fournisseur** rassemble chaque ligne d’article,
avec la facture, la date, les quantités et les montants. Le filtre fournisseur
et l’export Excel produisent une feuille complète exploitable comme base de
gestion.

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
PURCHASES_AI_AUTO_PROCESS=True
OLLAMA_API_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5vl:3b
OLLAMA_NUM_CTX=8192
PURCHASES_EXTRACTION_ENGINE=rules
```

Le contexte de 8 192 jetons est nécessaire pour les rendus haute résolution
qui préservent les petits caractères des pieds de page.

Les dates extraites sont rendues au format ISO dans les champs HTML de type
date. Elles restent ainsi visibles avec une interface française et ne sont pas
effacées accidentellement lors de l'enregistrement du formulaire.

Conserver `rules` pendant la phase de comparaison. Le passage à `ollama` pour
les imports automatiques ne doit intervenir qu’après validation d’un échantillon
représentatif de factures.
