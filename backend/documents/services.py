from datetime import date

from django.db import transaction
from django.utils import timezone

from companies.models import Company

from .models import Document, DocumentCounter, DocumentType


class NumberingService:
    """Service de génération des numéros de documents."""

    @classmethod
    def generate(
        cls,
        *,
        company: Company,
        document_type_code: str,
        generation_date: date | None = None,
    ) -> str:
        """
        Réserve et renvoie un numéro unique pour une société et un type.

        Exemple :
            FN-ACME-000001-2026
        """

        try:
            company = Company.objects.get(pk=company.pk, active=True)
        except (AttributeError, Company.DoesNotExist):
            raise ValueError("La société n’existe pas ou est inactive.") from None

        normalized_code = DocumentType.normalize_identifier(
            document_type_code
        )

        try:
            document_type = DocumentType.objects.get(
                code=normalized_code,
                active=True,
            )
        except DocumentType.DoesNotExist:
            raise ValueError(
                f"Le type de document '{document_type_code}' n'existe pas."
            ) from None

        effective_date = generation_date or timezone.localdate()
        current_year = effective_date.year
        counter_year = current_year if document_type.yearly_reset else 0

        with transaction.atomic():
            counter, _ = (
                DocumentCounter.objects
                .select_for_update()
                .get_or_create(
                    company=company,
                    document_type=document_type,
                    year=counter_year,
                    defaults={
                        "current_number": 0,
                    },
                )
            )

            sequence = counter.current_number + 1
            while True:
                number = (
                    f"{document_type.prefix}-"
                    f"{company.code}-"
                    f"{sequence:06d}-"
                    f"{current_year}"
                )
                if not Document.objects.filter(number=number).exists():
                    break
                sequence += 1

            counter.current_number = sequence
            counter.save(update_fields=("current_number",))

        return number
