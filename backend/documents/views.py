from django.views.generic import ListView,CreateView,UpdateView,DeleteView,DetailView
from .models import Document
from .forms import DocumentForm
class DocumentListView(ListView):
 model=Document
