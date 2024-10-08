from django.urls import re_path as url
from rest_framework.routers import DefaultRouter

from . import views


app_name = 'reports'

router = DefaultRouter()

router.register(r'users', views.ReportsByUsersViewSet, basename='users')
router.register(r'service_tickets', views.ReportsByServiceTicketsViewSet, basename='st_full_report')
router.register(r'user_hours', views.ReportsByUsersHoursViewSet, basename='user_hours')
router.register(r'indirect-hours', views.ReportsByIndirectHoursViewSet, basename='indirect-hours')
router.register(r'mechanic_report', views.DetailedReportByMechanicViewSet, basename='mechanic_report')

urlpatterns = [
    url(r'service-ticket-log', views.ServiceTicketChangelog.as_view())
]

urlpatterns += router.urls
