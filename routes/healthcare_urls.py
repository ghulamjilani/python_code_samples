from django.urls import path

from apps.healthcare.docs_views import SharedDocumentsView, ShareDocumentsView
from apps.healthcare.views import ExportDataView, get_binary_file, HealthServicesView, HealthServiceView, \
	MyHealthDataView, ResourceView
from utils.config import GlobalConfig
from .views import handle_binary_resource

config = GlobalConfig()

healthcare_urls = [
    path('<str:provider>/services/', HealthServicesView.as_view(), name='hd_services'),
    path('<str:provider>/<int:service_id>/', HealthServiceView.as_view(), name='hd_service'),
    path('<str:provider>/<int:service_id>/<str:api_slug>/', MyHealthDataView.as_view(), name='my_health_data'),
    path('bin-file/<str:doc_id>/', get_binary_file, name='get_bin_file'),

    path('<str:resource>/<str:resource_id>/', ResourceView.as_view(), name='show_resource'),
    path('select-documents/', ShareDocumentsView.as_view(), name='select_documents'),
    path('shared-documents/', SharedDocumentsView.as_view(), name='shared_documents'),
    path('bin-file/<str:doc_id>/', handle_binary_resource, name='get_bin_file'),
    path('export-data/', ExportDataView.as_view(), name='export_data'),
]
