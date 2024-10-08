from django.urls import re_path
from rest_framework.routers import DefaultRouter

from .views import (
    BeamsTokenProvider, UserViewSet, obtain_jwt_token, refresh_jwt_token, verify_jwt_token
)

app_name = 'authentication'
router = DefaultRouter()  # pylint: disable=invalid-name

router.register(r'', UserViewSet)

urlpatterns = [
    re_path(r'^login/', obtain_jwt_token, name='login'),
    re_path(r'^token_refresh/', refresh_jwt_token, name='token-refresh'),
    re_path(r'^token_verify/', verify_jwt_token, name='token-verify'),
    re_path(r'^beams_auth/', BeamsTokenProvider.as_view(), name='beams-auth')
]

urlpatterns += router.urls
