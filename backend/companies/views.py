from django.contrib import messages
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DeleteView,
)

from .forms import CompanyForm
from .models import Company


class CompanyListView(ListView):
    model = Company
    template_name = "companies/list.html"

    context_object_name = "companies"

    paginate_by = 15

    def get_queryset(self):

        queryset = Company.objects.all()

        search = self.request.GET.get("q")

        if search:

            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(city__icontains=search)
                | Q(contact__icontains=search)
                | Q(email__icontains=search)
            )

        return queryset.order_by("name")


class CompanyCreateView(CreateView):
    model = Company

    form_class = CompanyForm

    template_name = "companies/form.html"

    success_url = reverse_lazy("companies:list")

    def form_valid(self, form):
        messages.success(self.request, "Company created successfully.")
        return super().form_valid(form)


class CompanyUpdateView(UpdateView):
    model = Company

    form_class = CompanyForm

    template_name = "companies/form.html"

    success_url = reverse_lazy("companies:list")

    def form_valid(self, form):
        messages.success(self.request, "Company updated successfully.")
        return super().form_valid(form)


class CompanyDeleteView(DeleteView):
    model = Company

    template_name = "companies/delete.html"

    success_url = reverse_lazy("companies:list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Company deleted successfully.")
        return super().delete(request, *args, **kwargs)