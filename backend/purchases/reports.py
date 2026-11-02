"""États paramétrables sur les achats : détail des lignes, synthèses par article,
par fournisseur et par mois, avec export Excel.

Les synthèses par fournisseur et par mois utilisent les totaux des factures
(en-têtes, plus fiables) ; dès qu'un filtre porte sur la désignation ou la
référence d'article, elles sont calculées sur les lignes correspondantes.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django import forms
from django.db.models import (
    Count,
    DecimalField,
    F,
    IntegerField,
    Max,
    Min,
    OuterRef,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Lower, NullIf, Trim, TruncMonth

from .extraction import hamming, ice_digits
from .models import InvoiceNature, PurchaseInvoice, PurchaseInvoiceLine, Supplier


ZERO = Decimal("0")
MONEY = DecimalField(max_digits=18, decimal_places=2)
QUANTITY = DecimalField(max_digits=18, decimal_places=4)
UNIDENTIFIED = "(fournisseur non identifié)"

REPORTS = {
    "catalogue": "Articles et fournisseurs",
    "comparaison": "Comparaison des prix fournisseurs",
    "lignes": "Détail des lignes d’achat",
    "articles": "Synthèse par article",
    "fournisseurs": "Synthèse par fournisseur",
    "mois": "Synthèse par mois",
}

STATUS_CHOICES = (
    ("", "Toutes sauf rejetées"),
    (PurchaseInvoice.Status.VALIDATED, "Validées uniquement"),
    (PurchaseInvoice.Status.TO_REVIEW, "À vérifier uniquement"),
    ("ALL", "Toutes, y compris rejetées"),
)


class PurchaseReportFilterForm(forms.Form):
    date_from = forms.DateField(
        required=False,
        label="Du",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        label="Au",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        required=False,
        label="Fournisseur",
        empty_label="Tous les fournisseurs",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    designation = forms.CharField(
        required=False,
        label="Désignation contient",
        help_text="Plusieurs mots : tous doivent être présents (ex. « verre vin »).",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex. moquette, MDF, rose"}),
    )
    reference = forms.CharField(
        required=False,
        label="Référence article",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    nature = forms.ChoiceField(
        required=False,
        label="Nature",
        choices=(("", "Toutes les natures"), *InvoiceNature.choices),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    activity = forms.ChoiceField(
        required=False,
        label="Activité du fournisseur",
        choices=(("", "Toutes les activités"),),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    status = forms.ChoiceField(
        required=False,
        label="Statut des factures",
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    multi_suppliers = forms.BooleanField(
        required=False,
        label="Seulement les articles vendus par plusieurs fournisseurs",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    currency = forms.CharField(
        required=False,
        initial="MAD",
        label="Devise",
        max_length=3,
        widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 3}),
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        suppliers = Supplier.objects.filter(company=company) if company else Supplier.objects.none()
        # Seuls les fournisseurs ayant au moins une facture importée sont proposés.
        self.fields["supplier"].queryset = (
            suppliers.filter(invoices__isnull=False).distinct().order_by("name")
        )
        activities = (
            suppliers.exclude(activity="").values_list("activity", flat=True).distinct().order_by("activity")
        )
        self.fields["activity"].choices = (("", "Toutes les activités"),) + tuple(
            (activity, activity) for activity in activities
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            raise forms.ValidationError("La date de début doit précéder la date de fin.")
        cleaned["currency"] = (cleaned.get("currency") or "").strip().upper()
        return cleaned

    @property
    def filters(self):
        return self.cleaned_data if self.is_bound and self.is_valid() else {"currency": "MAD"}

    @property
    def uses_line_filters(self):
        filters = self.filters
        return bool(filters.get("designation") or filters.get("reference"))

    def describe(self):
        """Résumé lisible des filtres, repris en tête de l'export Excel."""
        filters = self.filters
        parts = []
        if filters.get("date_from") or filters.get("date_to"):
            start = filters["date_from"].strftime("%d/%m/%Y") if filters.get("date_from") else "…"
            end = filters["date_to"].strftime("%d/%m/%Y") if filters.get("date_to") else "…"
            parts.append(f"Période : {start} → {end}")
        if filters.get("supplier"):
            parts.append(f"Fournisseur : {filters['supplier'].name}")
        if filters.get("designation"):
            parts.append(f"Désignation : {filters['designation']}")
        if filters.get("reference"):
            parts.append(f"Référence : {filters['reference']}")
        if filters.get("nature"):
            parts.append(f"Nature : {InvoiceNature(filters['nature']).label}")
        if filters.get("activity"):
            parts.append(f"Activité : {filters['activity']}")
        if filters.get("multi_suppliers"):
            parts.append("Articles vendus par plusieurs fournisseurs")
        parts.append(f"Statut : {dict(STATUS_CHOICES)[filters.get('status', '')]}")
        if filters.get("currency"):
            parts.append(f"Devise : {filters['currency']}")
        return " · ".join(parts)


# ---------------------------------------------------------------- jeux de données
def _supplier_label():
    return Coalesce(
        F("supplier__name"),
        NullIf(F("supplier_name_raw"), Value("")),
        Value(UNIDENTIFIED),
    )


def filtered_invoices(company, filters):
    invoices = PurchaseInvoice.objects.filter(company=company)
    status = filters.get("status") or ""
    if status == "ALL":
        pass
    elif status:
        invoices = invoices.filter(status=status)
    else:
        invoices = invoices.exclude(status=PurchaseInvoice.Status.REJECTED)
    if filters.get("date_from"):
        invoices = invoices.filter(invoice_date__gte=filters["date_from"])
    if filters.get("date_to"):
        invoices = invoices.filter(invoice_date__lte=filters["date_to"])
    if filters.get("supplier"):
        invoices = invoices.filter(supplier=filters["supplier"])
    if filters.get("nature"):
        invoices = invoices.filter(nature=filters["nature"])
    if filters.get("activity"):
        invoices = invoices.filter(supplier__activity=filters["activity"])
    if filters.get("currency"):
        invoices = invoices.filter(currency=filters["currency"])
    return invoices


def filtered_lines(company, filters):
    lines = PurchaseInvoiceLine.objects.filter(invoice__in=filtered_invoices(company, filters))
    for word in (filters.get("designation") or "").split():
        lines = lines.filter(description__icontains=word)
    if filters.get("reference"):
        lines = lines.filter(reference__icontains=filters["reference"].strip())
    return lines


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"  # text, date, money, quantity, integer, month


@dataclass
class ReportResult:
    columns: list
    rows: list  # liste de dict
    totals: dict
    note: str = ""


def lines_report(company, filters):
    rows = (
        filtered_lines(company, filters)
        .annotate(
            supplier_label=Coalesce(
                F("invoice__supplier__name"),
                NullIf(F("invoice__supplier_name_raw"), Value("")),
                Value(UNIDENTIFIED),
            )
        )
        .order_by("invoice__invoice_date", "invoice__invoice_number", "position")
        .values(
            "invoice__invoice_date",
            "supplier_label",
            "invoice__supplier__ice",
            "invoice__invoice_number",
            "invoice__paperless_title",
            "reference",
            "description",
            "quantity",
            "unit",
            "unit_price_ht",
            "discount_percent",
            "total_ht",
            "tax_rate",
            "tax_amount",
            "total_ttc",
            "verified",
            "invoice_id",
        )
    )
    columns = [
        Column("invoice__invoice_date", "Date", "date"),
        Column("supplier_label", "Fournisseur"),
        Column("invoice__supplier__ice", "ICE"),
        Column("invoice__invoice_number", "N° facture"),
        Column("invoice__paperless_title", "Pièce"),
        Column("reference", "Référence"),
        Column("description", "Désignation"),
        Column("quantity", "Quantité", "quantity"),
        Column("unit", "Unité"),
        Column("unit_price_ht", "Prix unitaire HT", "money"),
        Column("discount_percent", "Remise %", "quantity"),
        Column("total_ht", "Total HT", "money"),
        Column("tax_rate", "TVA %", "quantity"),
        Column("tax_amount", "TVA", "money"),
        Column("total_ttc", "Total TTC", "money"),
    ]
    totals = filtered_lines(company, filters).aggregate(
        quantity=Coalesce(Sum("quantity"), ZERO, output_field=QUANTITY),
        total_ht=Coalesce(Sum("total_ht"), ZERO, output_field=MONEY),
        tax_amount=Coalesce(Sum("tax_amount"), ZERO, output_field=MONEY),
        total_ttc=Coalesce(Sum("total_ttc"), ZERO, output_field=MONEY),
        count=Count("id"),
    )
    return ReportResult(columns, rows, totals)


def articles_report(company, filters):
    rows = (
        filtered_lines(company, filters)
        .annotate(article=Lower(Trim("description")))
        .values("article")
        .annotate(
            designation=Max("description"),
            reference=Max("reference"),
            unit=Max("unit"),
            quantity=Coalesce(Sum("quantity"), ZERO, output_field=QUANTITY),
            total_ht=Coalesce(Sum("total_ht"), ZERO, output_field=MONEY),
            total_ttc=Coalesce(Sum("total_ttc"), ZERO, output_field=MONEY),
            min_price=Min("unit_price_ht"),
            max_price=Max("unit_price_ht"),
            purchases=Count("invoice", distinct=True),
            suppliers=Count("invoice__supplier", distinct=True),
            first_date=Min("invoice__invoice_date"),
            last_date=Max("invoice__invoice_date"),
        )
        .order_by("-total_ht")
    )
    rows = list(rows)
    for row in rows:
        row["average_price"] = (
            (row["total_ht"] / row["quantity"]).quantize(Decimal("0.0001"))
            if row["quantity"]
            else None
        )
    columns = [
        Column("designation", "Désignation"),
        Column("reference", "Référence"),
        Column("unit", "Unité"),
        Column("quantity", "Quantité totale", "quantity"),
        Column("average_price", "Prix moyen HT", "money"),
        Column("min_price", "Prix min HT", "money"),
        Column("max_price", "Prix max HT", "money"),
        Column("total_ht", "Total HT", "money"),
        Column("total_ttc", "Total TTC", "money"),
        Column("purchases", "Factures", "integer"),
        Column("suppliers", "Fournisseurs", "integer"),
        Column("first_date", "Premier achat", "date"),
        Column("last_date", "Dernier achat", "date"),
    ]
    totals = {
        "quantity": sum((row["quantity"] for row in rows), ZERO),
        "total_ht": sum((row["total_ht"] for row in rows), ZERO),
        "total_ttc": sum((row["total_ttc"] for row in rows), ZERO),
        "count": len(rows),
    }
    return ReportResult(
        columns,
        rows,
        totals,
        note="Les articles sont regroupés par désignation identique (sans tenir compte des majuscules).",
    )


def _amount_aggregates(prefix=""):
    if prefix:  # calcul sur les lignes
        return {
            "net_ht": Coalesce(Sum("total_ht"), ZERO, output_field=MONEY),
            "tax": Coalesce(Sum("tax_amount"), ZERO, output_field=MONEY),
            "ttc": Coalesce(Sum("total_ttc"), ZERO, output_field=MONEY),
            "invoices": Count("invoice", distinct=True),
            "lines": Count("id"),
        }
    # Pas de jointure sur les lignes ici : elle multiplierait les totaux des factures.
    return {
        "net_ht": Coalesce(Sum("net_ht"), ZERO, output_field=MONEY),
        "tax": Coalesce(Sum("tax_amount"), ZERO, output_field=MONEY),
        "ttc": Coalesce(Sum("total_ttc"), ZERO, output_field=MONEY),
        "invoices": Count("id", distinct=True),
        "lines": Coalesce(Sum("line_count"), 0),
    }


def _with_line_count(invoices):
    counts = (
        PurchaseInvoiceLine.objects.filter(invoice=OuterRef("pk"))
        .order_by()
        .values("invoice")
        .annotate(total=Count("id"))
        .values("total")
    )
    return invoices.annotate(line_count=Coalesce(Subquery(counts, output_field=IntegerField()), 0))


def suppliers_report(company, filters, *, on_lines):
    if on_lines:
        queryset = filtered_lines(company, filters).annotate(
            supplier_label=Coalesce(
                F("invoice__supplier__name"),
                NullIf(F("invoice__supplier_name_raw"), Value("")),
                Value(UNIDENTIFIED),
            ),
            supplier_ice=Coalesce(F("invoice__supplier__ice"), F("invoice__supplier_ice_raw")),
            day=F("invoice__invoice_date"),
        )
        aggregates = _amount_aggregates("lines")
    else:
        queryset = _with_line_count(filtered_invoices(company, filters)).annotate(
            supplier_label=_supplier_label(),
            supplier_ice=Coalesce(F("supplier__ice"), F("supplier_ice_raw")),
            day=F("invoice_date"),
        )
        aggregates = _amount_aggregates()
    rows = list(
        queryset.values("supplier_label", "supplier_ice")
        .annotate(first_date=Min("day"), last_date=Max("day"), **aggregates)
        .order_by("-ttc")
    )
    columns = [
        Column("supplier_label", "Fournisseur"),
        Column("supplier_ice", "ICE"),
        Column("invoices", "Factures", "integer"),
        Column("lines", "Lignes", "integer"),
        Column("net_ht", "Total HT", "money"),
        Column("tax", "TVA", "money"),
        Column("ttc", "Total TTC", "money"),
        Column("first_date", "Première facture", "date"),
        Column("last_date", "Dernière facture", "date"),
    ]
    return ReportResult(columns, rows, _sum_totals(rows), note=_source_note(on_lines))


def months_report(company, filters, *, on_lines):
    if on_lines:
        queryset = filtered_lines(company, filters).annotate(month=TruncMonth("invoice__invoice_date"))
        aggregates = _amount_aggregates("lines")
    else:
        queryset = _with_line_count(filtered_invoices(company, filters)).annotate(
            month=TruncMonth("invoice_date")
        )
        aggregates = _amount_aggregates()
    rows = list(
        queryset.exclude(month=None)
        .values("month")
        .annotate(suppliers=Count("invoice__supplier" if on_lines else "supplier", distinct=True), **aggregates)
        .order_by("month")
    )
    columns = [
        Column("month", "Mois", "month"),
        Column("invoices", "Factures", "integer"),
        Column("lines", "Lignes", "integer"),
        Column("suppliers", "Fournisseurs", "integer"),
        Column("net_ht", "Total HT", "money"),
        Column("tax", "TVA", "money"),
        Column("ttc", "Total TTC", "money"),
    ]
    return ReportResult(columns, rows, _sum_totals(rows), note=_source_note(on_lines))


def _sum_totals(rows):
    return {
        "net_ht": sum((row["net_ht"] for row in rows), ZERO),
        "tax": sum((row["tax"] for row in rows), ZERO),
        "ttc": sum((row["ttc"] for row in rows), ZERO),
        "invoices": sum(row["invoices"] for row in rows),
        "lines": sum(row["lines"] for row in rows),
        "count": len(rows),
    }


def _source_note(on_lines):
    if on_lines:
        return "Montants calculés sur les lignes d’articles correspondant à la désignation ou à la référence."
    return "Montants issus des totaux des factures (en-têtes)."


def _article_key(text):
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


class SupplierNamer:
    """Nom du fournisseur d'une facture : fiche rattachée, sinon annuaire par ICE, sinon nom lu."""

    def __init__(self, company):
        self.directory = {
            ice_digits(supplier.ice): supplier.name
            for supplier in Supplier.objects.filter(company=company).exclude(ice="")
            if len(ice_digits(supplier.ice)) == 15
        }
        self.cache = {}

    def __call__(self, invoice):
        if invoice.supplier_id:
            return invoice.supplier.name
        ice = ice_digits(invoice.supplier_ice_raw)
        if ice:
            if ice not in self.cache:
                self.cache[ice] = self.directory.get(ice) or next(
                    (name for known, name in self.directory.items() if hamming(known, ice) <= 1),
                    None,
                )
            if self.cache[ice]:
                return self.cache[ice]
        if invoice.supplier_name_raw:
            return invoice.supplier_name_raw.strip()
        return f"ICE {ice}" if ice else UNIDENTIFIED


def _articles_by_supplier(company, filters):
    """{clé article: {"names": Counter, "suppliers": {nom: statistiques}}}"""
    namer = SupplierNamer(company)
    articles = defaultdict(lambda: {"names": Counter(), "suppliers": defaultdict(lambda: {
        "quantity": ZERO, "total": ZERO, "prices": [], "invoices": set(), "last": None, "unit": "",
    })})
    lines = filtered_lines(company, filters).select_related("invoice", "invoice__supplier")
    for line in lines.iterator(chunk_size=2000):
        key = _article_key(line.description)
        if not key:
            continue
        article = articles[key]
        article["names"][line.description.strip()] += 1
        stats = article["suppliers"][namer(line.invoice)]
        stats["quantity"] += line.quantity or ZERO
        stats["total"] += line.total_ht or ZERO
        if line.unit_price_ht:
            stats["prices"].append(line.unit_price_ht)
        stats["invoices"].add(line.invoice_id)
        stats["unit"] = stats["unit"] or line.unit
        day = line.invoice.invoice_date
        if day and (stats["last"] is None or day > stats["last"]):
            stats["last"] = day
    if filters.get("multi_suppliers"):
        articles = {key: value for key, value in articles.items() if len(value["suppliers"]) > 1}
    return articles


def catalogue_report(company, filters):
    rows = []
    for article in _articles_by_supplier(company, filters).values():
        suppliers = article["suppliers"]
        prices = [price for stats in suppliers.values() for price in stats["prices"]]
        rows.append({
            "designation": article["names"].most_common(1)[0][0],
            "supplier_count": len(suppliers),
            "supplier_names": " | ".join(sorted(suppliers)),
            "quantity": sum((stats["quantity"] for stats in suppliers.values()), ZERO),
            "total_ht": sum((stats["total"] for stats in suppliers.values()), ZERO),
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "purchases": len({i for stats in suppliers.values() for i in stats["invoices"]}),
            "last_date": max((stats["last"] for stats in suppliers.values() if stats["last"]), default=None),
        })
    rows.sort(key=lambda row: (-row["supplier_count"], row["designation"].casefold()))
    columns = [
        Column("designation", "Désignation"),
        Column("supplier_count", "Nb fournisseurs", "integer"),
        Column("supplier_names", "Fournisseurs"),
        Column("quantity", "Quantité totale", "quantity"),
        Column("total_ht", "Total HT", "money"),
        Column("min_price", "Prix unitaire min", "money"),
        Column("max_price", "Prix unitaire max", "money"),
        Column("purchases", "Factures", "integer"),
        Column("last_date", "Dernier achat", "date"),
    ]
    totals = {
        "quantity": sum((row["quantity"] for row in rows), ZERO),
        "total_ht": sum((row["total_ht"] for row in rows), ZERO),
        "count": len(rows),
    }
    multi = sum(1 for row in rows if row["supplier_count"] > 1)
    return ReportResult(
        columns,
        rows,
        totals,
        note=(
            f"{len(rows)} articles, dont {multi} vendus par plusieurs fournisseurs. "
            "Articles regroupés par désignation identique (majuscules et espaces ignorés)."
        ),
    )


def comparison_report(company, filters):
    filters = dict(filters, multi_suppliers=True)
    rows = []
    for article in _articles_by_supplier(company, filters).values():
        name = article["names"].most_common(1)[0][0]
        for supplier, stats in article["suppliers"].items():
            average = (stats["total"] / stats["quantity"]).quantize(Decimal("0.0001")) if stats["quantity"] else None
            rows.append({
                "designation": name,
                "supplier": supplier,
                "unit": stats["unit"],
                "quantity": stats["quantity"],
                "total_ht": stats["total"],
                "average_price": average,
                "min_price": min(stats["prices"]) if stats["prices"] else None,
                "max_price": max(stats["prices"]) if stats["prices"] else None,
                "purchases": len(stats["invoices"]),
                "last_date": stats["last"],
            })
    rows.sort(key=lambda row: (row["designation"].casefold(), row["average_price"] is None, row["average_price"] or 0))
    columns = [
        Column("designation", "Désignation"),
        Column("supplier", "Fournisseur"),
        Column("unit", "Unité"),
        Column("quantity", "Quantité", "quantity"),
        Column("average_price", "Prix moyen HT", "money"),
        Column("min_price", "Prix min", "money"),
        Column("max_price", "Prix max", "money"),
        Column("total_ht", "Total HT", "money"),
        Column("purchases", "Factures", "integer"),
        Column("last_date", "Dernier achat", "date"),
    ]
    totals = {
        "quantity": sum((row["quantity"] for row in rows), ZERO),
        "total_ht": sum((row["total_ht"] for row in rows), ZERO),
        "count": len(rows),
    }
    return ReportResult(
        columns,
        rows,
        totals,
        note="Articles vendus par plusieurs fournisseurs : pour chaque article, du moins cher au plus cher.",
    )


def build_report(kind, company, form):
    filters = form.filters
    if kind == "catalogue":
        return catalogue_report(company, filters)
    if kind == "comparaison":
        return comparison_report(company, filters)
    if kind == "lignes":
        return lines_report(company, filters)
    if kind == "articles":
        return articles_report(company, filters)
    if kind == "fournisseurs":
        return suppliers_report(company, filters, on_lines=form.uses_line_filters)
    if kind == "mois":
        return months_report(company, filters, on_lines=form.uses_line_filters)
    raise KeyError(kind)


# ---------------------------------------------------------------- export Excel
def report_workbook(kind, result, *, company, description):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = REPORTS[kind][:31]
    sheet.append([f"{REPORTS[kind]} — {company.name}"])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet.append([description])
    if result.note:
        sheet.append([result.note])
    sheet.append([])
    header_row = sheet.max_row + 1
    sheet.append([column.label for column in result.columns])
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)

    formats = {
        "money": "#,##0.00",
        "quantity": "#,##0.####",
        "integer": "0",
        "date": "DD/MM/YYYY",
        "month": "MM/YYYY",
    }
    for row in result.rows:
        values = []
        for column in result.columns:
            value = row.get(column.key)
            if isinstance(value, Decimal):
                value = float(value)
            if column.kind == "month" and value is not None and hasattr(value, "date"):
                value = value.date()
            values.append(value)
        sheet.append(values)
    for index, column in enumerate(result.columns, start=1):
        width = {"description": 40, "designation": 40, "supplier_label": 40, "supplier": 35, "supplier_names": 60}.get(
            column.key, 15
        )
        sheet.column_dimensions[get_column_letter(index)].width = width
        if column.kind in formats:
            for (cell,) in sheet.iter_rows(min_row=header_row + 1, min_col=index, max_col=index):
                cell.number_format = formats[column.kind]

    # Ligne de totaux
    total_values = []
    for index, column in enumerate(result.columns):
        key = {"quantity": "quantity", "total_ht": "total_ht", "tax_amount": "tax_amount",
               "total_ttc": "total_ttc", "net_ht": "net_ht", "tax": "tax", "ttc": "ttc",
               "invoices": "invoices", "lines": "lines"}.get(column.key)
        value = result.totals.get(key) if key else None
        if index == 0:
            value = "TOTAL"
        total_values.append(float(value) if isinstance(value, Decimal) else value)
    sheet.append(total_values)
    for index, cell in enumerate(sheet[sheet.max_row], start=0):
        cell.font = Font(bold=True)
        column = result.columns[index]
        if column.kind in formats and index:
            cell.number_format = formats[column.kind]

    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(len(result.columns))}{sheet.max_row - 1}"
    return workbook
