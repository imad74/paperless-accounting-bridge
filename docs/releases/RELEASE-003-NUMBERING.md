# Release 003 — Stratégie de numérotation

## Format retenu

Les numéros générés utilisent le format suivant :

```text
<PRÉFIXE>-<CODE_SOCIÉTÉ>-<SÉQUENCE_SUR_6_CHIFFRES>-<ANNÉE>
```

Exemple :

```text
FN-ACME-000001-2026
```

Le code société est inclus parce que `Document.number` reste globalement unique,
alors que chaque société possède désormais sa propre séquence pour un même type
documentaire.

## Portée des compteurs

La clé d’un compteur est constituée de la société, du type documentaire et de
l’année technique :

- pour un type avec réinitialisation annuelle, l’année technique est l’année
  réelle de génération ;
- pour un type sans réinitialisation annuelle, l’année technique vaut `0` et la
  séquence continue d’une année civile à l’autre ; l’année réelle reste affichée
  dans le numéro généré.

## Migration des compteurs existants

La migration est volontairement séparée en trois étapes :

1. `0002_documentcounter_company_nullable` ajoute la société nullable et retire
   l’ancienne contrainte ;
2. `0003_migrate_document_counters` affecte les sociétés et consolide les
   compteurs continus dans une transaction dédiée ;
3. `0004_finalize_document_counters` rend la société obligatoire et crée la
   nouvelle contrainte après le commit des modifications de données. Cette
   séparation évite les événements de triggers en attente lors des changements
   de schéma sous PostgreSQL.

L’affectation automatique est réalisée uniquement si elle est certaine : une
seule société existe, ou les documents correspondant au compteur appartiennent
à une seule société. Si plusieurs sociétés sont possibles, la migration s’arrête
avec les identifiants des compteurs concernés sans choisir silencieusement.

Après cet arrêt attendu, affecter explicitement chaque compteur depuis le shell
Django, puis relancer les migrations :

```python
from documents.models import DocumentCounter

DocumentCounter.objects.filter(pk=COUNTER_ID).update(company_id=COMPANY_ID)
```

Une sauvegarde PostgreSQL doit être réalisée avant toute migration d’une base
existante.
