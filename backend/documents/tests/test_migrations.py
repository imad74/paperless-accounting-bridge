from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DocumentCounterMigrationTests(TransactionTestCase):
    company_migration = (
        "companies",
        "0002_alter_company_options_company_contact_company_ice_and_more",
    )
    migrate_from = [company_migration, ("documents", "0001_initial")]
    migrate_intermediate = [
        company_migration,
        ("documents", "0002_documentcounter_company_nullable"),
    ]
    migrate_to = [
        company_migration,
        ("documents", "0004_finalize_document_counters"),
    ]
    migrate_latest = [
        company_migration,
        ("documents", "0005_document_pdf_storage"),
    ]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(self.migrate_latest)
        super().tearDown()

    def test_single_company_is_assigned_to_existing_counter(self):
        old_apps = self.migrate(self.migrate_from)
        Company = old_apps.get_model("companies", "Company")
        DocumentCounter = old_apps.get_model("documents", "DocumentCounter")
        DocumentType = old_apps.get_model("documents", "DocumentType")
        company = Company.objects.create(code="ONE", name="Une société")
        document_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )
        counter = DocumentCounter.objects.create(
            document_type=document_type,
            year=2026,
            current_number=17,
        )

        new_apps = self.migrate(self.migrate_to)
        MigratedCounter = new_apps.get_model("documents", "DocumentCounter")
        migrated_counter = MigratedCounter.objects.get(pk=counter.pk)

        self.assertEqual(migrated_counter.company_id, company.pk)
        self.assertEqual(migrated_counter.current_number, 17)

    def test_document_usage_resolves_counter_in_multi_company_database(self):
        old_apps = self.migrate(self.migrate_from)
        Company = old_apps.get_model("companies", "Company")
        Document = old_apps.get_model("documents", "Document")
        DocumentCounter = old_apps.get_model("documents", "DocumentCounter")
        DocumentType = old_apps.get_model("documents", "DocumentType")
        Company.objects.create(code="OTHER", name="Autre société")
        document_company = Company.objects.create(
            code="DOC",
            name="Société document",
        )
        document_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )
        Document.objects.create(
            number="FN-000001-2026",
            title="Facture historique",
            company=document_company,
            document_type=document_type,
            original_filename="invoice.pdf",
            stored_filename="invoice.pdf",
            document_date=date(2026, 1, 15),
        )
        counter = DocumentCounter.objects.create(
            document_type=document_type,
            year=2026,
            current_number=1,
        )

        new_apps = self.migrate(self.migrate_to)
        MigratedCounter = new_apps.get_model("documents", "DocumentCounter")

        self.assertEqual(
            MigratedCounter.objects.get(pk=counter.pk).company_id,
            document_company.pk,
        )

    def test_ambiguous_counter_requires_explicit_assignment(self):
        old_apps = self.migrate(self.migrate_from)
        Company = old_apps.get_model("companies", "Company")
        DocumentCounter = old_apps.get_model("documents", "DocumentCounter")
        DocumentType = old_apps.get_model("documents", "DocumentType")
        first_company = Company.objects.create(code="FIRST", name="Première")
        Company.objects.create(code="SECOND", name="Deuxième")
        document_type = DocumentType.objects.create(
            code="INV",
            name="Facture",
            prefix="FN",
        )
        counter = DocumentCounter.objects.create(
            document_type=document_type,
            year=2026,
            current_number=3,
        )

        with self.assertRaisesMessage(
            RuntimeError,
            "Impossible d’affecter automatiquement la société",
        ):
            self.migrate(self.migrate_to)

        intermediate_apps = self.migrate(self.migrate_intermediate)
        IntermediateCounter = intermediate_apps.get_model(
            "documents",
            "DocumentCounter",
        )
        IntermediateCounter.objects.filter(pk=counter.pk).update(
            company_id=first_company.pk
        )

        new_apps = self.migrate(self.migrate_to)
        MigratedCounter = new_apps.get_model("documents", "DocumentCounter")
        self.assertEqual(
            MigratedCounter.objects.get(pk=counter.pk).company_id,
            first_company.pk,
        )

    def test_continuous_legacy_counters_are_consolidated_at_high_water_mark(self):
        old_apps = self.migrate(self.migrate_from)
        Company = old_apps.get_model("companies", "Company")
        DocumentCounter = old_apps.get_model("documents", "DocumentCounter")
        DocumentType = old_apps.get_model("documents", "DocumentType")
        company = Company.objects.create(code="CONT", name="Continue")
        document_type = DocumentType.objects.create(
            code="SEQ",
            name="Séquence continue",
            prefix="SC",
            yearly_reset=False,
        )
        DocumentCounter.objects.create(
            document_type=document_type,
            year=2025,
            current_number=12,
        )
        DocumentCounter.objects.create(
            document_type=document_type,
            year=2026,
            current_number=4,
        )

        new_apps = self.migrate(self.migrate_to)
        MigratedCounter = new_apps.get_model("documents", "DocumentCounter")
        counters = list(
            MigratedCounter.objects.filter(
                company_id=company.pk,
                document_type_id=document_type.pk,
            )
        )

        self.assertEqual(len(counters), 1)
        self.assertEqual(counters[0].year, 0)
        self.assertEqual(counters[0].current_number, 12)


class DocumentPdfStorageMigrationTests(TransactionTestCase):
    company_migration = (
        "companies",
        "0002_alter_company_options_company_contact_company_ice_and_more",
    )
    migrate_from = [
        company_migration,
        ("documents", "0004_finalize_document_counters"),
    ]
    migrate_to = [
        company_migration,
        ("documents", "0005_document_pdf_storage"),
    ]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(self.migrate_to)
        super().tearDown()

    def test_counter_starts_at_highest_existing_numeric_pdf_filename(self):
        old_apps = self.migrate(self.migrate_from)
        Company = old_apps.get_model("companies", "Company")
        Document = old_apps.get_model("documents", "Document")
        DocumentType = old_apps.get_model("documents", "DocumentType")
        company = Company.objects.create(code="PDF", name="PDF")
        document_type = DocumentType.objects.create(
            code="PDF",
            name="PDF",
            prefix="PDF",
        )
        Document.objects.create(
            number="PDF-PDF-000001-2026",
            title="Document historique",
            company=company,
            document_type=document_type,
            original_filename="scan.pdf",
            stored_filename="00000042.pdf",
            document_date=date(2026, 1, 1),
        )
        Document.objects.create(
            number="PDF-PDF-000002-2026",
            title="Ancien nom dupliqué",
            company=company,
            document_type=document_type,
            original_filename="autre-scan.pdf",
            stored_filename="00000042.pdf",
            document_date=date(2026, 1, 2),
        )

        new_apps = self.migrate(self.migrate_to)
        DocumentFileCounter = new_apps.get_model(
            "documents",
            "DocumentFileCounter",
        )
        MigratedDocument = new_apps.get_model(
            "documents",
            "Document",
        )

        self.assertEqual(
            DocumentFileCounter.objects.get(key="pdf").current_number,
            42,
        )
        self.assertEqual(MigratedDocument.objects.count(), 2)
        self.assertTrue(
            all(
                document.pdf_file.name == ""
                for document in MigratedDocument.objects.all()
            )
        )
