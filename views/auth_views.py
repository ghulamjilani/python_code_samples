from django.contrib.auth.models import Group
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.openapi import Schema
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.mixins import (
    CreateModelMixin, ListModelMixin, RetrieveModelMixin, UpdateModelMixin
)

from rest_framework_jwt.views import ObtainJSONWebTokenView, RefreshJSONWebTokenView, VerifyJSONWebTokenView
"""
from rest_framework_simplejwt.views import (
    TokenObtainPairView, TokenRefreshView, TokenVerifyView # ObtainJSONWebTokenView, VerifyJSONWebTokenView, RefreshJSONWebTokenView
)
"""

from apps.utils.tasks import (
    send_notification_user_created,
    send_password_restore_link,
    send_reset_password
)
from apps.notifications.notification_interface import beams_client
from apps.utils.request_middleware import RequestMiddleware
from .authentication import CsrfExemptAuthentication
from .filters import UserFilter
from .jwt_utils import response_with_token
from .models import User, Mechanic, Manager
from .permissions import IsAdmin, IsExceptTheMechanic, IsAdminOrOwnUserObjectAccess
from .serializers import (
    BasePasswordSerializer, HashSerializer, RestorePasswordSerializer,
    UserSerializer, UpdatePasswordSerializer, MechanicSerializer,
    ManagerSerializer, JSONWebTokenSerializer
)


class UserViewSet(ListModelMixin,
                  CreateModelMixin,
                  RetrieveModelMixin,
                  UpdateModelMixin,
                  GenericViewSet):
    """
    list:

    User endpoint.\n
        Note: User roles are constants:
            {
                1: "Admin",
                2: "Biller",
                3: "Manager",
                4: "Mechanic"
            }\n
        Filter example:
            /?role=Mechanic&&search=ManagerName
            /?status=archived - get all archived users
            /?status=active - get all active users
        Available ordering fields: name, role, email
        Request without pagination example: /?all=true
    """
    serializer_class = UserSerializer
    queryset = User.objects.order_by('status', '-date_joined')
    permission_classes = (IsAdmin,)
    
    filter_backends = (DjangoFilterBackend, SearchFilter,)
    filterset_class = UserFilter
    search_fields = ('first_name', 'last_name', 'groups__name', 'email',)

    def paginate_queryset(self, queryset):
        """Turn off the Pagination if the server gets all=True query parameter."""
        do_pagination = 'true' not in self.request.query_params.get('all', '').lower()
        if do_pagination:
            return super().paginate_queryset(queryset)

    def get_permissions(self):
        if self.action in ('partial_update', 'retrieve', 'update',):
            return [IsAdminOrOwnUserObjectAccess()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        print("Requested data is-----",request.data)
        serializer = self.get_serializer(data=request.data)
        # print("Serializer data is-----",serializer.data)

        serializer.is_valid(raise_exception=True)
        passwords = BasePasswordSerializer(data=request.data)
        passwords.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        user_instance = User.objects.get(id=serializer.data.get('id'))
        password = request.data.get('password')
        user_instance.set_password(password)
        user_instance.save()
        response = response_with_token(user_instance, serializer.data)
        transaction.on_commit(
            lambda: send_notification_user_created.delay(user_instance.id, password)
        )
        return Response(response, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        """Bind group to user."""
        role_id = serializer.validated_data.pop('role')
        instance = serializer.save()
        user_role = serializer.fields.get('role').choices.get(role_id)
        instance.groups.add(Group.objects.get(name=user_role))

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        # Any user can update his sent_email_notifications field
        requester = RequestMiddleware.get_request().user
        if instance == requester and not (requester.is_admin or requester.is_superuser):
            if len(request.data.keys()) > 1 or not 'sent_email_notifications' in request.data:
                return Response(
                    {'detail': _('You do not have permission to perform this action.')},
                    status=status.HTTP_403_FORBIDDEN
            )

        partial = kwargs.pop('partial', False)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        response = response_with_token(instance, serializer.data)
        return Response(response, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], permission_classes=[IsAdminOrOwnUserObjectAccess])
    def update_password(self, request, pk=None):
        """
        Update User password.

        request example:

            {
                "old_password": "OldPassword123",
                "password": "NewPassword1234",
                "password_check": "NewPassword1234"
            }
        """
        user = self.get_object()
        serializer = UpdatePasswordSerializer(data=request.data, context=user)
        if serializer.is_valid(raise_exception=True):
            user.set_password(serializer.data['password'])
            user.save()
            user_data = response_with_token(user, UserSerializer(user).data)
            response = {**user_data, 'detail': [_('Password is successfully updated!')]}
            return Response(response, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def confirm_email(self, request):
        serializer = HashSerializer(
            data={'hash': request.query_params.get('hash')}, cache_key_action='email_confirmation_'
        )
        if serializer.is_valid(raise_exception=True):
            user = User.objects.get(id=serializer.validated_data.get('hash').get('id'))
            user.is_confirmed_email = True
            user.save()
            transaction.on_commit(lambda: send_notification_user_created.delay(user.id))
            return Response({'is_confirmed_email': True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def restore_password_link(self, request, pk=None):
        """
        Restore password link.

        request example:

            {
                "email": "email@email.com"
            }
        """
        try:
            user = User.objects.get(email=request.data.get('email'))
        except User.DoesNotExist:
            return Response(
                {'email': [_('Email is invalid')]},
                status=status.HTTP_404_NOT_FOUND
            )
        # TODO: add celery tasks handling
        send_password_restore_link.delay(user.id)
        return Response({'detail': [_('Email is sent!')]}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def restore_password(self, request, pk=None):
        """
        Restore password.

        request example:

            {
                "password": 'pass123',
                "password_check": 'pass123'
            }

        url example:

            http://localhost:3000/auth/restore_password/?hash=eyJpZCI6IDcsICJ1dW2Yi04ZjJ9

        """
        data = dict.copy(request.data)
        data.update({'hash': request.query_params.get('hash')})
        serializer = RestorePasswordSerializer(data=data, cache_key_action='password_restore_')
        if serializer.is_valid(raise_exception=True):
            user = User.objects.get(id=serializer.validated_data.get('hash').get('id'))
            user.set_password(serializer.validated_data.get('password'))
            user.save()
            user_data = response_with_token(user, UserSerializer(user).data)
            response = {**user_data, 'detail': [_('Password is successfully restored!')]}
            return Response(response, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], permission_classes=[IsAdmin])
    def reset_password(self, request, pk=None):
        try:
            user = User.objects.get(id=pk)
        except (ValueError, User.DoesNotExist,):
            response = {'detail': _('There is no user with this ID')}
            return Response(response, status=status.HTTP_404_NOT_FOUND)
        password = User.objects.make_random_password()
        user.set_password(password)
        user.save()
        transaction.on_commit(lambda: send_reset_password.delay(user.id, password))
        return Response({'detail': [_('Email is sent!')]}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def archive_users(self, request, pk=None):
        """
        API for the User archiving logic.
        Send the list of User id's that you want to archive.
        Request example: { "ids": [1,2] }.
        """
        ids = request.data.get("ids")
        if ids is None or not isinstance(ids, list):
            response = {'ids': [_('This field is required. And it should be a list')]}
            return Response(response, status=status.HTTP_400_BAD_REQUEST)
        error_ids = []
        success_ids = []
        for id in ids:
            try:
                user_obj = User.objects.get(id=id)
                user_obj.status = User.ARCHIVED
                user_obj.sent_email_notifications = False
                user_obj.sent_push_notifications = False
                user_obj.save(
                    update_fields=[
                        'status', 'sent_email_notifications',
                        'sent_push_notifications'
                    ]
                )
                success_ids.append(id)
            except (ValueError, User.DoesNotExist,):
                error_ids.append(id)
        response = {
            "Successfully archived Users (IDs)": success_ids,
            "Failed to archive Users (IDs)": error_ids
        }
        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def unarchive_users(self, request, pk=None):
        """
        API for the User unarchive logic.
        Send the list of User id's that you want to unarchive.
        Request example: { "ids": [1,2] }.
        """
        ids = request.data.get("ids")
        if ids is None or not isinstance(ids, list):
            response = {'ids': [_('This field is required. And it should be a list')]}
            return Response(response, status=status.HTTP_400_BAD_REQUEST)
        error_ids = []
        success_ids = []
        for id in ids:
            try:
                user_obj = User.objects.get(id=id)
                user_obj.status = User.ACTIVE
                user_obj.sent_email_notifications = True
                user_obj.sent_push_notifications = True
                user_obj.save(
                    update_fields=[
                        'status', 'sent_email_notifications',
                        'sent_push_notifications'
                    ]
                )
                success_ids.append(id)
            except (ValueError, User.DoesNotExist,):
                error_ids.append(id)
        response = {
            "Successfully unarchived Users (IDs)": success_ids,
            "Failed to unarchive Users (IDs)": error_ids
        }
        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsExceptTheMechanic])
    def get_all_managers(self, request):
        data = Manager.objects.filter(status=1)
        serializer = ManagerSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsExceptTheMechanic])
    def get_all_mechanics(self, request):
        data = Mechanic.objects.filter(status=1)
        serializer = MechanicSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BeamsTokenProvider(APIView):
    """
    API View that returns Pusher Beams token for user that make a request.
    """
    permission_classes = (IsAuthenticated,)

    @swagger_auto_schema(
        responses={201: Schema(type='object', properties={'token': Schema(type='string')})}
    )
    def get(self, request, *args, **kwargs):
        beams_token = beams_client.generate_token(str(request.user.id))
        return Response(beams_token, status=status.HTTP_200_OK)


# Custom documentation for JWT views

class ObtainJSONWebToken(ObtainJSONWebTokenView):
    """
    API View that receives a POST with a user's username and password.

    Returns a JSON Web Token that can be used for authenticated requests.
    """
    serializer_class = JSONWebTokenSerializer
    
    def post(self, request):
        response = super(ObtainJSONWebToken, self).post(request)
        return response


class VerifyJSONWebToken(VerifyJSONWebTokenView):
    """
    API View that checks the veracity of a token, returning the token if it
    is valid.
    """


class RefreshJSONWebToken(RefreshJSONWebTokenView):
    """
    API View that returns a refreshed token (with new expiration) based on
    existing token

    If 'orig_iat' field (original issued-at-time) is found, will first check
    if it's within expiration window, then copy it to the new token
    """


obtain_jwt_token = ObtainJSONWebToken.as_view()
refresh_jwt_token = RefreshJSONWebToken.as_view()
verify_jwt_token = VerifyJSONWebToken.as_view()
