import random
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from documents.paperless_api import PaperlessApiClient, PaperlessApiError
from purchases.ai_extraction import AiExtractionError, OllamaInvoiceExtractor
from purchases.extraction import TOTALS_FROM_TRIPLET, TOTALS_FROM_WORDS
from purchases.management.commands.import_purchase_invoices import Command as ImportCommand
from purchases.models import InvoiceNature, PurchaseInvoice
from purchases.services import extractor_for_company


TOLERANCE = Decimal("0.05")
RULES = "règles actuelles"


def metrics(extracted):
    lines_total = sum((line.total_ht for line in extracted.lines), Decimal("0"))
    net = extracted.net_ht
    balanced = bool(extracted.lines) and net is not None and abs(lines_total - net) <= TOLERANCE
    totals_ok = (
        None not in (net, extracted.tax_amount, extracted.total_ttc)
        and abs(net + extracted.tax_amount - extracted.total_ttc) <= TOLERANCE
    ) or extracted.totals_method in (TOTALS_FROM_TRIPLET, TOTALS_FROM_WORDS)
    return {
        "lines": len(extracted.lines),
        "lines_total": lines_total,
        "balanced": balanced,
        "totals_ok": bool(totals_ok),
        "ice": bool(extracted.supplier_ice),
        "number": bool(extracted.invoice_number),
        "date": extracted.invoice_date is not None,
    }


class Command(BaseCommand):
    help = (
        "Compare, sans rien modifier dans PAB, l’extraction actuelle (règles) et l’extraction "
        "par Ollama sur un échantillon de factures. Produit un classeur Excel comparatif."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Code de la société.")
        parser.add_argument("--sample", type=int, default=50, help="Nombre de factures (défaut : 50).")
        parser.add_argument(
            "--models",
            default="qwen2.5vl:3b",
            help="Modèles Ollama locaux à tester, séparés par des virgules.",
        )
        parser.add_argument(
            "--ids", default="", help="Identifiants Paperless à inclure obligatoirement (ex. 2895,2642,2578)."
        )
        parser.add_argument("--seed", type=int, default=42, help="Graine du tirage aléatoire.")
        parser.add_argument(
            "--output", default="/tmp/comparaison-extraction-ia.xlsx", help="Fichier Excel produit."
        )
        parser.add_argument(
            "--total-invoices",
            type=int,
            default=None,
            help="Nombre de factures pour l’extrapolation du coût (défaut : factures dans PAB).",
        )

    def handle(self, *args, **options):
        company = ImportCommand._company(options["company"])
        models = [m.strip() for m in options["models"].split(",") if m.strip()]
        try:
            client = PaperlessApiClient()
            engines = {
                model: OllamaInvoiceExtractor(
                    model=model,
                    excluded_ices=[company.ice] if company.ice else [],
                    excluded_names=[company.name],
                )
                for model in models
            }
        except (PaperlessApiError, AiExtractionError) as error:
            raise CommandError(str(error)) from error
        rules = extractor_for_company(company)

        document_ids = self._sample(company, options)
        self.stdout.write(f"{len(document_ids)} factures à comparer avec : {RULES}, {', '.join(models)}")

        per_invoice, ai_lines = [], []
        summary = defaultdict(lambda: defaultdict(Decimal))
        for index, document_id in enumerate(document_ids, start=1):
            try:
                document = client.get_document(document_id)
                pdf = client.download_pdf(document_id)
            except PaperlessApiError as error:
                self.stderr.write(f"  #{document_id} ignoré : {error}")
                continue
            results = {RULES: (rules.extract(document.content, title=document.title), None)}
            for model, engine in engines.items():
                try:
                    result = engine.extract_document(
                        pdf_bytes=pdf, text=document.content, title=document.title,
                        page_count=document.page_count,
                    )
                    results[model] = (result.extracted, result)
                except AiExtractionError as error:
                    results[model] = (None, error)
            for engine_name, (extracted, detail) in results.items():
                stats = summary[engine_name]
                stats["documents"] += 1
                if extracted is None:
                    stats["errors"] += 1
                    per_invoice.append([document_id, document.title, engine_name, "ERREUR", str(detail)])
                    continue
                m = metrics(extracted)
                for key in ("balanced", "totals_ok", "ice", "number", "date"):
                    stats[key] += int(m[key])
                stats["lines"] += m["lines"]
                cost = getattr(detail, "cost_usd", None) or Decimal("0")
                seconds = Decimal(str(getattr(detail, "seconds", 0) or 0))
                stats["cost"] += cost
                stats["seconds"] += seconds
                per_invoice.append([
                    document_id, document.title, engine_name, "OK",
                    extracted.supplier_name, extracted.supplier_ice, extracted.invoice_number,
                    extracted.invoice_date, extracted.nature, m["lines"],
                    float(m["lines_total"]), float(extracted.net_ht) if extracted.net_ht is not None else None,
                    float(extracted.total_ttc) if extracted.total_ttc is not None else None,
                    "oui" if m["balanced"] else "non", "oui" if m["totals_ok"] else "non",
                    float(cost), float(seconds),
                ])
                if detail is not None:
                    for line in extracted.lines:
                        ai_lines.append([
                            document_id, document.title, engine_name, line.reference, line.description,
                            float(line.quantity), line.unit, float(line.unit_price_ht), float(line.total_ht),
                            float(line.tax_rate),
                        ])
            self.stdout.write(
                f"  {index}/{len(document_ids)} #{document_id} "
                + " | ".join(
                    f"{name}: {'lignes OK' if r[0] and metrics(r[0])['balanced'] else ('erreur' if r[0] is None else 'lignes ≠ total')}"
                    for name, r in results.items()
                )
            )

        total_invoices = options["total_invoices"] or PurchaseInvoice.objects.filter(company=company).count()
        rows = self._summary_rows(summary, total_invoices)
        self._write_workbook(options["output"], rows, per_invoice, ai_lines)
        self.stdout.write("\nSynthèse :")
        for row in rows[1:]:
            self.stdout.write(
                f"  {row[0]:<20} lignes = total HT : {row[2]:>5}   totaux cohérents : {row[3]:>5}   "
                f"ICE : {row[4]:>5}   coût/facture : {row[7]}   coût estimé {total_invoices} factures : {row[8]}"
            )
        self.stdout.write(self.style.SUCCESS(f"Classeur : {options['output']}"))

    # ------------------------------------------------------------ échantillon
    def _sample(self, company, options):
        rng = random.Random(options["seed"])
        wanted = [int(i) for i in options["ids"].replace(";", ",").split(",") if i.strip().isdigit()]
        invoices = PurchaseInvoice.objects.filter(
            company=company, nature=InvoiceNature.GOODS
        ).exclude(paperless_document_id=None)
        chosen = list(dict.fromkeys(wanted))
        # Deux factures pour chacun des 15 principaux fournisseurs…
        top = (
            invoices.exclude(supplier=None).values("supplier")
            .annotate(n=Count("id")).order_by("-n")[:15]
        )
        for row in top:
            ids = list(invoices.filter(supplier=row["supplier"]).values_list("paperless_document_id", flat=True))
            for document_id in rng.sample(ids, min(2, len(ids))):
                if document_id not in chosen:
                    chosen.append(document_id)
        # … puis un tirage au hasard pour compléter (petits fournisseurs, tickets, factures sans ICE).
        remaining = [i for i in invoices.values_list("paperless_document_id", flat=True) if i not in chosen]
        rng.shuffle(remaining)
        chosen.extend(remaining[: max(0, options["sample"] - len(chosen))])
        return chosen[: max(options["sample"], len(wanted))]

    # ------------------------------------------------------------ restitution
    @staticmethod
    def _summary_rows(summary, total_invoices):
        rows = [[
            "Moteur", "Factures", "Lignes = total HT", "Totaux cohérents", "ICE trouvé",
            "Lignes lues (moyenne)", "Erreurs", "Coût moyen / facture (USD)",
            f"Coût estimé pour {total_invoices} factures (USD)", "Temps moyen (s)",
        ]]
        for engine, stats in summary.items():
            done = stats["documents"] - stats["errors"]
            pct = lambda key: f"{(stats[key] / done * 100):.0f} %" if done else "—"
            average_cost = (stats["cost"] / done) if done else Decimal("0")
            rows.append([
                engine, int(stats["documents"]), pct("balanced"), pct("totals_ok"), pct("ice"),
                round(float(stats["lines"] / done), 1) if done else 0, int(stats["errors"]),
                round(float(average_cost), 4), round(float(average_cost * total_invoices), 2),
                round(float(stats["seconds"] / done), 1) if done else 0,
            ])
        return rows

    @staticmethod
    def _write_workbook(path, summary_rows, per_invoice, ai_lines):
        from openpyxl import Workbook
        from openpyxl.styles import Font

        workbook = Workbook()
        sheets = (
            ("Synthèse", summary_rows[0], summary_rows[1:]),
            ("Par facture", [
                "Paperless", "Pièce", "Moteur", "Statut", "Fournisseur", "ICE", "N° facture", "Date",
                "Nature", "Lignes", "Somme lignes HT", "Total HT", "Total TTC", "Lignes = total HT",
                "Totaux cohérents", "Coût (USD)", "Temps (s)",
            ], per_invoice),
            ("Lignes lues par l’IA", [
                "Paperless", "Pièce", "Modèle", "Référence", "Désignation", "Quantité", "Unité",
                "Prix unitaire HT", "Total HT", "TVA %",
            ], ai_lines),
        )
        for index, (title, header, rows) in enumerate(sheets):
            sheet = workbook.active if index == 0 else workbook.create_sheet()
            sheet.title = title
            sheet.append(header)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for row in rows:
                sheet.append(row)
            sheet.freeze_panes = "A2"
            for column in sheet.columns:
                sheet.column_dimensions[column[0].column_letter].width = 18
        workbook.save(path)
