from datetime import date

from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

from .models import DocumentCounter, DocumentType


class NumberingService:
    """Service de génération des numéros de documents."""

    @staticmethod
    def generate(document_type_code: str) -> str:
        """
        Génère un numéro de document unique.

        Exemple :
            FN-000001-2026
        """

        current_year = date.today().year

        try:
            document_type = DocumentType.objects.get(
                code=document_type_code,
                active=True,
            )
        except ObjectDoesNotExist:
            raise ValueError(
                f"Le type de document '{document_type_code}' n'existe pas."
            )

        with transaction.atomic():

            counter, created = (
                DocumentCounter.objects
                .select_for_update()
                .get_or_create(
                    document_type=document_type,
                    year=current_year,
                    defaults={
                        "current_number": 0,
                    },
                )
            )

            counter.current_number += 1
            counter.save(update_fields=["current_number"])

        return (
            f"{document_type.prefix}-"
            f"{counter.current_number:06d}-"
            f"{current_year}"
        )