from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.mixins import CompanyPermissionRequiredMixin
from accounts.permissions import CompanyPermission

from .reports import REPORTS, PurchaseReportFilterForm, build_report, report_workbook


class PurchaseReportView(CompanyPermissionRequiredMixin, TemplateView):
    """États des achats : affichage à l'écran et export Excel avec les mêmes filtres."""

    template_name = "purchases/report.html"
    required_company_permission = CompanyPermission.VIEW_DOCUMENTS
    page_size = 100

    def dispatch(self, request, *args, **kwargs):
        if kwargs.get("kind") not in REPORTS:
            raise Http404("État inconnu.")
        return super().dispatch(request, *args, **kwargs)

    def get_form(self):
        data = self.request.GET if self.request.GET else None
        return PurchaseReportFilterForm(data, company=self.active_company)

    def get(self, request, *args, **kwargs):
        kind = kwargs["kind"]
        form = self.get_form()
        if form.is_bound and not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form, kind=kind, result=None))
        result = build_report(kind, self.active_company, form)
        if request.GET.get("export") == "xlsx":
            workbook = report_workbook(
                kind, result, company=self.active_company, description=form.describe()
            )
            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            filename = f"achats-{kind}-{self.active_company.code.lower()}-{timezone.localdate():%Y%m%d}.xlsx"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            workbook.save(response)
            return response
        return self.render_to_response(self.get_context_data(form=form, kind=kind, result=result))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        result = kwargs.get("result")
        query = self.request.GET.copy()
        query.pop("page", None)
        query.pop("export", None)
        context.update(
            {
                "reports": REPORTS,
                "report_title": REPORTS[kwargs["kind"]],
                "filter_query": query.urlencode(),
                "description": kwargs["form"].describe(),
            }
        )
        if result is not None:
            page = Paginator(result.rows, self.page_size).get_page(self.request.GET.get("page"))
            context.update(
                {
                    "page_obj": page,
                    "table_rows": [
                        [(column, row.get(column.key)) for column in result.columns] for row in page.object_list
                    ],
                    "total_cells": [
                        (column, result.totals.get(_TOTAL_KEYS.get(column.key, ""))) for column in result.columns
                    ],
                }
            )
        return context


_TOTAL_KEYS = {
    "quantity": "quantity",
    "total_ht": "total_ht",
    "tax_amount": "tax_amount",
    "total_ttc": "total_ttc",
    "net_ht": "net_ht",
    "tax": "tax",
    "ttc": "ttc",
    "invoices": "invoices",
    "lines": "lines",
}
