from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views


app_name = 'api'

router = DefaultRouter()

router.register(r'jobs', views.JobViewSet, basename='job')
router.register(r'service_tickets', views.ServiceTicketViewSet, basename='service_ticket')
router.register(r'customers', views.CustomerViewSet, basename='customer')

urlpatterns = [
    path('db-lock/', views.DBLockView.as_view(), name='db-lock-view'),
    path('export-service-tickets/<int:job_id>/', views.ServiceTicketExportView.as_view(),
         name='service-ticket-export-view')
]

urlpatterns += router.urls
