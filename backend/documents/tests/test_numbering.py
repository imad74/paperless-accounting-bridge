from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase

from companies.models import Company
from documents.models import Document, DocumentCounter, DocumentType
from documents.services import NumberingService


class NumberingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(code="ACME", name="ACME")
        cls.other_company = Company.objects.create(
            code="BETA",
            name="Beta",
        )
        cls.yearly_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
            yearly_reset=True,
        )
        cls.continuous_type = DocumentType.objects.create(
            code="SEQ",
            name="Séquence continue",
            prefix="SC",
            yearly_reset=False,
        )
        cls.other_type = DocumentType.objects.create(
            code="CRN",
            name="Avoir",
            prefix="AV",
        )
        cls.inactive_type = DocumentType.objects.create(
            code="OLD",
            name="Type inactif",
            prefix="OLD",
            active=False,
        )

    def generate(self, *, company=None, document_type_code="INV", year=2026):
        return NumberingService.generate(
            company=company or self.company,
            document_type_code=document_type_code,
            generation_date=date(year, 1, 15),
        )

    def test_first_number_contains_prefix_company_sequence_and_year(self):
        number = self.generate()

        self.assertEqual(number, "FN-ACME-000001-2026")

    def test_sequence_is_incremented(self):
        first_number = self.generate()
        second_number = self.generate()

        self.assertEqual(first_number, "FN-ACME-000001-2026")
        self.assertEqual(second_number, "FN-ACME-000002-2026")

    def test_counters_are_separated_by_company(self):
        company_number = self.generate()
        other_company_number = self.generate(company=self.other_company)

        self.assertEqual(company_number, "FN-ACME-000001-2026")
        self.assertEqual(other_company_number, "FN-BETA-000001-2026")
        self.assertEqual(DocumentCounter.objects.count(), 2)

    def test_counters_are_separated_by_document_type(self):
        invoice_number = self.generate()
        credit_number = self.generate(document_type_code="CRN")

        self.assertEqual(invoice_number, "FN-ACME-000001-2026")
        self.assertEqual(credit_number, "AV-ACME-000001-2026")

    def test_yearly_counter_resets_for_a_new_year(self):
        first_year_number = self.generate(year=2026)
        next_year_number = self.generate(year=2027)

        self.assertEqual(first_year_number, "FN-ACME-000001-2026")
        self.assertEqual(next_year_number, "FN-ACME-000001-2027")
        self.assertQuerySetEqual(
            DocumentCounter.objects.order_by("year").values_list(
                "year",
                "current_number",
            ),
            [(2026, 1), (2027, 1)],
        )

    def test_continuous_counter_does_not_reset_for_a_new_year(self):
        first_year_number = self.generate(
            document_type_code="SEQ",
            year=2026,
        )
        next_year_number = self.generate(
            document_type_code="SEQ",
            year=2027,
        )

        self.assertEqual(first_year_number, "SC-ACME-000001-2026")
        self.assertEqual(next_year_number, "SC-ACME-000002-2027")
        counter = DocumentCounter.objects.get()
        self.assertEqual(counter.year, 0)
        self.assertEqual(counter.current_number, 2)

    def test_document_type_code_is_normalized(self):
        number = self.generate(document_type_code=" inv ")

        self.assertEqual(number, "FN-ACME-000001-2026")

    def test_existing_document_number_is_never_reused(self):
        Document.objects.create(
            number="FN-ACME-000001-2026",
            title="Numéro déjà utilisé",
            company=self.company,
            document_type=self.yearly_type,
            original_filename="existing.pdf",
            stored_filename="existing.pdf",
            document_date=date(2026, 1, 10),
        )

        number = self.generate()

        self.assertEqual(number, "FN-ACME-000002-2026")
        counter = DocumentCounter.objects.get()
        self.assertEqual(counter.current_number, 2)

    def test_unknown_document_type_is_rejected(self):
        with self.assertRaisesMessage(
            ValueError,
            "Le type de document 'UNKNOWN' n'existe pas.",
        ):
            self.generate(document_type_code="UNKNOWN")

    def test_inactive_document_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.generate(document_type_code=self.inactive_type.code)

    def test_inactive_company_is_rejected(self):
        Company.objects.filter(pk=self.company.pk).update(active=False)

        with self.assertRaisesMessage(
            ValueError,
            "La société n’existe pas ou est inactive.",
        ):
            self.generate()

    def test_counter_scope_is_unique(self):
        DocumentCounter.objects.create(
            company=self.company,
            document_type=self.yearly_type,
            year=2026,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentCounter.objects.create(
                    company=self.company,
                    document_type=self.yearly_type,
                    year=2026,
                )

    def test_yearly_counter_rejects_technical_year_zero(self):
        counter = DocumentCounter(
            company=self.company,
            document_type=self.yearly_type,
            year=0,
        )

        with self.assertRaises(ValidationError):
            counter.full_clean()

    def test_continuous_counter_requires_technical_year_zero(self):
        counter = DocumentCounter(
            company=self.company,
            document_type=self.continuous_type,
            year=2026,
        )

        with self.assertRaises(ValidationError):
            counter.full_clean()


@skipUnless(
    connection.vendor == "postgresql",
    "La concurrence de numérotation doit être testée sous PostgreSQL.",
)
class NumberingConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.company = Company.objects.create(code="CONC", name="Concurrence")
        self.document_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )

    def test_concurrent_generation_never_duplicates_a_number(self):
        worker_count = 8
        barrier = Barrier(worker_count)

        def generate_number(_):
            close_old_connections()
            try:
                company = Company.objects.get(pk=self.company.pk)
                barrier.wait(timeout=10)
                return NumberingService.generate(
                    company=company,
                    document_type_code=self.document_type.code,
                    generation_date=date(2026, 1, 15),
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            numbers = list(executor.map(generate_number, range(worker_count)))

        self.assertEqual(len(numbers), worker_count)
        self.assertEqual(len(set(numbers)), worker_count)
        self.assertEqual(
            sorted(numbers),
            [
                f"FN-CONC-{sequence:06d}-2026"
                for sequence in range(1, worker_count + 1)
            ],
        )
        counter = DocumentCounter.objects.get(
            company=self.company,
            document_type=self.document_type,
            year=2026,
        )
        self.assertEqual(counter.current_number, worker_count)
