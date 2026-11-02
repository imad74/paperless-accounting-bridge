"""Annuaire des fournisseurs construit à partir de l'archive Paperless.

Chaque document est analysé (ICE fournisseur, nom, nature, date, total) puis
regroupé par ICE. Les lectures OCR qui diffèrent d'un chiffre sont rattachées
au même fournisseur. La nature détectée d'un fournisseur est la nature
majoritaire de ses factures ; la nature *validée* (default_nature) et
l'activité restent saisies par l'utilisateur et ne sont jamais écrasées.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .extraction import (
    TOTALS_FROM_TRIPLET,
    TOTALS_FROM_WORDS,
    hamming,
    ice_digits,
)
from .models import InvoiceNature, Supplier


# Part minimale de la nature majoritaire (hors « à déterminer ») pour la retenir.
MAJORITY_SHARE = Decimal("0.6")
PLACEHOLDER_PREFIX = "Fournisseur ICE "


@dataclass
class SupplierStats:
    ice: str
    documents: int = 0
    natures: Counter = field(default_factory=Counter)
    names: Counter = field(default_factory=Counter)
    total_ttc: Decimal = Decimal("0")
    first_date: date | None = None
    last_date: date | None = None

    def add(self, extracted):
        self.documents += 1
        self.natures[extracted.nature] += 1
        if extracted.supplier_name:
            self.names[" ".join(extracted.supplier_name.split()).upper()] += 1
        if extracted.total_ttc and extracted.totals_method in (TOTALS_FROM_TRIPLET, TOTALS_FROM_WORDS):
            if extracted.currency == "MAD":
                self.total_ttc += extracted.total_ttc
        day = extracted.invoice_date
        if day and 2015 <= day.year <= 2035:
            self.first_date = min(filter(None, (self.first_date, day)))
            self.last_date = max(filter(None, (self.last_date, day)))

    def merge(self, other):
        self.documents += other.documents
        self.natures.update(other.natures)
        self.names.update(other.names)
        self.total_ttc += other.total_ttc
        dates = [d for d in (self.first_date, self.last_date, other.first_date, other.last_date) if d]
        if dates:
            self.first_date, self.last_date = min(dates), max(dates)

    @property
    def suggested_name(self):
        return self.names.most_common(1)[0][0][:255] if self.names else ""

    @property
    def detected_nature(self):
        determined = {
            nature: count
            for nature, count in self.natures.items()
            if nature not in (InvoiceNature.UNKNOWN, InvoiceNature.SALE)
        }
        if not determined:
            return InvoiceNature.UNKNOWN
        nature, count = max(determined.items(), key=lambda item: item[1])
        if Decimal(count) / Decimal(sum(determined.values())) >= MAJORITY_SHARE:
            return nature
        return InvoiceNature.UNKNOWN

    @property
    def nature_details(self):
        labels = dict(InvoiceNature.choices)
        parts = [
            f"{labels.get(nature, nature)} {count}"
            for nature, count in self.natures.most_common()
        ]
        return " · ".join(parts)[:255]


class SupplierDirectoryBuilder:
    """Accumule les documents puis met à jour la table des fournisseurs."""

    def __init__(self, *, company, extractor):
        self.company = company
        self.extractor = extractor
        self.by_ice = {}
        self.outcome = Counter()

    def add_document(self, paperless_document):
        extracted = self.extractor.extract(
            paperless_document.content, title=paperless_document.title
        )
        if extracted.nature == InvoiceNature.SALE:
            self.outcome["factures de vente ignorées"] += 1
            return None
        if not extracted.supplier_ice:
            self.outcome["documents sans ICE fournisseur lisible"] += 1
            return None
        stats = self.by_ice.setdefault(extracted.supplier_ice, SupplierStats(extracted.supplier_ice))
        stats.add(extracted)
        self.outcome["documents rattachés à un fournisseur"] += 1
        return extracted

    def grouped(self):
        """Regroupe les ICE à un chiffre près, le plus fréquent devenant la référence."""
        known = {
            ice_digits(supplier.ice): supplier
            for supplier in Supplier.objects.filter(company=self.company).exclude(ice="")
        }
        groups = []
        for ice, stats in sorted(self.by_ice.items(), key=lambda item: -item[1].documents):
            target = next((g for g in groups if hamming(g.ice, ice) <= 1), None)
            if target is None:
                # Un fournisseur déjà connu sous un ICE voisin garde son ICE.
                existing = next((k for k in known if len(k) == 15 and hamming(k, ice) <= 1), None)
                grouped = SupplierStats(existing or ice)
                grouped.merge(stats)
                groups.append(grouped)
            else:
                target.merge(stats)
        return groups

    @transaction.atomic
    def save(self, *, min_documents=1):
        now = timezone.now()
        created = updated = 0
        groups = [g for g in self.grouped() if g.documents >= min_documents]
        existing = {
            ice_digits(supplier.ice): supplier
            for supplier in Supplier.objects.select_for_update().filter(company=self.company).exclude(ice="")
        }
        used_names = set(
            Supplier.objects.filter(company=self.company).values_list("normalized_name", flat=True)
        )
        for stats in groups:
            supplier = existing.get(stats.ice)
            if supplier is None:
                name = self._unique_name(stats.suggested_name or f"{PLACEHOLDER_PREFIX}{stats.ice}", stats.ice, used_names)
                supplier = Supplier(company=self.company, name=name, ice=stats.ice)
                created += 1
            else:
                updated += 1
                if supplier.name.startswith(PLACEHOLDER_PREFIX) and stats.suggested_name:
                    used_names.discard(supplier.normalized_name)
                    supplier.name = self._unique_name(stats.suggested_name, stats.ice, used_names)
            supplier.detected_nature = stats.detected_nature
            supplier.detected_nature_details = stats.nature_details
            supplier.paperless_document_count = stats.documents
            supplier.detected_total_ttc = stats.total_ttc.quantize(Decimal("0.01"))
            supplier.first_document_date = stats.first_date
            supplier.last_document_date = stats.last_date
            supplier.directory_updated_at = now
            supplier.save()
            used_names.add(supplier.normalized_name)
        self.outcome["fournisseurs créés"] = created
        self.outcome["fournisseurs mis à jour"] = updated
        return groups

    @staticmethod
    def _unique_name(name, ice, used_names):
        name = " ".join(name.split())[:230] or f"{PLACEHOLDER_PREFIX}{ice}"
        if Supplier.normalize_name(name) in used_names:
            name = f"{name} ({ice})"
        return name
