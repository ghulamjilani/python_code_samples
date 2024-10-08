# -*- coding: utf-8 -*-

import time

from datetime import datetime

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from django.shortcuts import get_object_or_404

from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.openapi import Schema
from drf_yasg.utils import swagger_auto_schema
from rest_framework.filters import SearchFilter
from rest_framework.mixins import (
    CreateModelMixin, ListModelMixin, UpdateModelMixin, RetrieveModelMixin
)
from rest_framework.exceptions import APIException
from rest_framework.serializers import ValidationError
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.utils.fields import IntegerChoiceField
from .exceptions import DBLockedException
from .models import Job, Customer, Location, ServiceTicket, DBLockDate
from .filters import JobFilter, ServiceTicketFilter
from .serializers import (
    CustomerSerializer, RemoveCustomerLocationSerializer, JobWriteSerializer, JobReadSerializer,
    ServiceTicketReadSerializer, ServiceTicketWriteSerializer, DeleteAttachmentSerializer,
    DeleteEmployeeWorksSerializer
)
from apps.notifications.models import Action
from .permissions import IsHaveAccessToCustomer, CanRemoveCustomerLocation
from apps.authentication.permissions import IsAdmin
from apps.api.utils import dict_none_defaults, render_to_pdf, PDFRenderer

from io import BytesIO

import zipfile

class JobViewSet(CreateModelMixin,
                 ListModelMixin,
                 RetrieveModelMixin,
                 UpdateModelMixin,
                 viewsets.GenericViewSet):
    """
    list:

    Job endpoint.\n
        Note: Job statuses are constants:
            {
                1: "Open",
                2: "Pending for Approval",
                3: "Rejected",
                4: "Approved"
            }\n
        Filter example: /?status=Open&start_date=09/13/19&end_date=10/13/19&search=WTX&all_tickets_approved=true&ordering=-number
        Available ordering fields: number, status, created_by, requested_by, approved_by, location, customer, time_stamp
        If you want to exclude: /?status!=Open
        If you want to get archived objects: /?is_archive=true
    """

    queryset = Job.objects.all().order_by('-creation_date')
    filter_backends = (DjangoFilterBackend, SearchFilter,)
    filterset_class = JobFilter
    search_fields = (
        'location__name', 'customer__name', 'number',
        'created_by__first_name', 'created_by__last_name', 'description',
    )

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update',):
            return JobWriteSerializer
        return JobReadSerializer

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        #print("this",queryset)
        user = self.request.user
        if user.is_mechanic:
            queryset = queryset.filter(mechanics=user.id)
        elif user.is_manager:
            queryset = queryset.filter(managers=user.id)
        is_archive = self.request.query_params.get('is_archive', None)
        if is_archive is None:
            queryset = queryset.filter(is_archive=False)
        return queryset
    

    @swagger_auto_schema(responses={200: JobReadSerializer})
    def create(self, request, *args, **kwargs):
        return super().create(request, args, kwargs)

    @swagger_auto_schema(responses={200: JobReadSerializer})
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, args, kwargs)

    def change_action_is_viewed(self, job_id):
        """
        Makes notifications is_viewed
        """
        list_st_id = ServiceTicket.objects.filter(
            connected_job=job_id
        ).values_list('id', flat=True)
        Action.objects.filter(
            Q(connected_object_id=job_id, object_type=0) |  # OBJECT_TYPES Jobh
            Q(connected_object_id__in=list_st_id, object_type=1)  # OBJECT_TYPES ST
        ).update(is_viewed=True)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def archive_job(self, request, pk=None):
        """
        API for the job archiving logic.
        Send the list of job id's that you want to archive.
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
                ih_obj = Job.objects.get(id=id)
                ih_obj.is_archive = True
                ih_obj.save(update_fields=['is_archive'])
                ServiceTicket.objects.filter(connected_job=ih_obj).update(is_archive=True)
                success_ids.append(id)
                self.change_action_is_viewed(ih_obj.id)
            except (ValueError, Job.DoesNotExist,):
                error_ids.append(id)
            response = {
                "Successfully archived Job (IDs)": success_ids,
                "Failed to archive Job (IDs)": error_ids
            }
        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def unarchive_job(self, request, pk=None):
        """
        API for the job unarchive logic.
        Send the list of job id's that you want to unarchive.
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
                ih_obj = Job.objects.get(id=id)
                ih_obj.is_archive = False
                ih_obj.save(update_fields=['is_archive'])
                ServiceTicket.objects.filter(connected_job=ih_obj).update(is_archive=False)
                success_ids.append(id)
            except (ValueError, Job.DoesNotExist,):
                error_ids.append(id)
            response = {
                "Successfully unarchived Job (IDs)": success_ids,
                "Failed to unarchive Job (IDs)": error_ids
            }
        return Response(response, status=status.HTTP_200_OK)


class ServiceTicketViewSet(CreateModelMixin,
                           ListModelMixin,
                           RetrieveModelMixin,
                           UpdateModelMixin,
                           viewsets.GenericViewSet):
    """
    Service Ticket content type is `multipart/form-data`.
    list:

    ServiceTicket endpoint.\n
    Service Ticket content type is `multipart/form-data`.\n
        Note: ServiceTicket statuses are constants:
            {
                1: "Open",
                2: "Pending for Approval",
                3: "Rejected",
                4: "Approved"
            }\n
        Filter example: /?status=Open&start_date=09/13/19&end_date=10/13/19&search=WTX&ordering=-number
        Available ordering fields: id, status, date, number, created_by, requested_by, approved_by, location, customer, notes
        If you want to get archived objects: /?is_archive=true
    """

    parser_classes = (JSONParser, FormParser, MultiPartParser,)
    queryset = ServiceTicket.objects.filter(is_archive=False).prefetch_related('employee_works').order_by('-creation_date')
    permission_classes = (IsAuthenticated,)
    filter_backends = (DjangoFilterBackend, SearchFilter,)
    filterset_class = ServiceTicketFilter
    search_fields = (
        'connected_job__location__name', 'connected_job__customer__name', 'connected_job__number',
        'additional_notes', 'created_by__first_name', 'created_by__last_name', 'id',
        'employee_works__employee__first_name'
    )

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update',):
            return ServiceTicketWriteSerializer
        return ServiceTicketReadSerializer

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        user = self.request.user
        if user.is_mechanic:
            queryset = queryset.filter(employee_works__employee=user.id)
            # q = list(queryset)
        elif user.is_manager:
            queryset = queryset.filter(connected_job__managers=user.id)
        return queryset.distinct()

    @swagger_auto_schema(
        methods=['patch'],
        responses={200: ServiceTicketReadSerializer},
        request_body=Schema(type="object", properties={
            "attachment_ids": Schema(type="array", write_only=True, items=Schema(type="integer"))
        })
    )
    @action(
        detail=True,
        methods=['patch'],
        serializer_class=DeleteAttachmentSerializer,
        permission_classes=(IsAuthenticated,)
    )
    def delete_attachments(self, request, pk=None):
        """
        Delete Attachments objects.
        Use `application/json` content type for this endpoint.
        """
        instance = self.get_object()
        serializer = DeleteAttachmentSerializer(data=request.data, instance=instance)
        serializer.is_valid(raise_exception=True)
        attachment_ids = request.data.get('attachment_ids', [])
        for attachment_id in attachment_ids:
            instance.attachments.get(id=attachment_id).delete()
        return Response(ServiceTicketReadSerializer(instance).data)

    @swagger_auto_schema(
        methods=['patch'],
        responses={200: ServiceTicketReadSerializer},
        request_body=Schema(type="object", properties={
            "employee_work_ids": Schema(
                type="array", write_only=True, items=Schema(type="integer")
            )
        })
    )
    @action(
        detail=True,
        methods=['patch'],
        serializer_class=DeleteEmployeeWorksSerializer,
        permission_classes=(IsAuthenticated,)
    )
    def delete_employee_works(self, request, pk=None):
        """
        Delete employee_works endpoint.
        Use `application/json` content type for this endpoint.
        """
        instance = self.get_object()
        serializer = DeleteEmployeeWorksSerializer(data=request.data, instance=instance)
        serializer.is_valid(raise_exception=True)
        employee_work_ids = request.data.get('employee_work_ids', [])
        for employee_work_id in employee_work_ids:
            instance.employee_works.get(id=employee_work_id).delete()
        return Response(ServiceTicketReadSerializer(instance).data)

    @swagger_auto_schema(responses={200: ServiceTicketReadSerializer})
    def create(self, request, *args, **kwargs):
        return super().create(request, args, kwargs)

    @swagger_auto_schema(responses={200: ServiceTicketReadSerializer})
    def partial_update(self, request, *args, **kwargs):
        """Override this method to ignore updating customer_signature if it already exists."""
        instance = self.get_object()
        data = request.data.copy()

        if 'customer_signature' in data and instance.customer_signature:
            data.pop('customer_signature')
        serializer = ServiceTicketWriteSerializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}
        return Response(serializer.data)

    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])
    def archive_service_ticket(self, request, pk=None):
        """
        API for the service ticket archiving logic.
        Send the list of service ticket id's that you want to archive.
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
                ih_obj = ServiceTicket.objects.get(id=id)
                ih_obj.is_archive = True
                ih_obj.save(update_fields=['is_archive'])
                success_ids.append(id)
                Action.objects.filter(
                    connected_object_id=ih_obj.id,
                    object_type=1  # OBJECT_TYPES ST
                ).update(is_viewed=True)
            except (ValueError, ServiceTicket.DoesNotExist,):
                error_ids.append(id)
            response = {
                "Successfully archived Service Ticket (IDs)": success_ids,
                "Failed to archive Service Ticket (IDs)": error_ids
            }
        return Response(response, status=status.HTTP_200_OK)
    
    def get_object(self):
        """
        Returns the object the view is displaying.

        You may want to override this if you need to provide non-standard
        queryset lookups.  Eg if objects are referenced using multiple
        keyword arguments in the url conf.
        """
        queryset = self.filter_queryset(self.get_queryset())
        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        assert lookup_url_kwarg in self.kwargs, (
            'Expected view %s to be called with a URL keyword argument '
            'named "%s". Fix your URL conf, or set the `.lookup_field` '
            'attribute on the view correctly.' %
            (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)



class CustomerViewSet(viewsets.ModelViewSet):
    """
    list:

    Customer endpoint.\n
        Filter example: /?search=CustomerName

        Request without pagination example: /?all=true

    create:
    Create a new Customer instance.

    request example:

        {
            "name": "Name",
            "locations": [
                {
                    "name": "WTX"
                }
            ]
        }

    partial_update:
    Patch a Customer instance.

    request example:

        {
            "name": "Name"
        }
    """
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filter_backends = [SearchFilter]
    search_fields = ['name']
    permission_classes = (IsAuthenticated, IsHaveAccessToCustomer,)

    def paginate_queryset(self, queryset):
        """Turn off the Pagination if the server gets all=True query parameter."""
        do_pagination = 'true' not in self.request.query_params.get('all', '').lower()
        if do_pagination:
            return super().paginate_queryset(queryset)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.job_set.count() != 0:
            raise ValidationError(
                _("You can't remove Customer that already has related Job")
            )
        return super().destroy(request, *args, **kwargs)

    @action(
        detail=True,
        methods=['patch'],
        serializer_class=RemoveCustomerLocationSerializer,
        permission_classes=(IsAuthenticated, CanRemoveCustomerLocation,)
    )
    def remove_location(self, request, pk=None):
        """
        Remove Location from Customer.

        request example:

            {
                "location_id": 1
            }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = Customer.objects.get(pk=pk)
        location = Location.objects.get(pk=serializer.data.get('location_id'))
        customer.locations.remove(location)
        return Response(CustomerSerializer(customer).data)


class STExportView(APIView):

    renderer_classes = [PDFRenderer]

    @method_decorator(csrf_exempt)
    def get(self, request, st_id):
        st = get_object_or_404(ServiceTicket, pk=st_id)
        if request.user.is_mechanic:
            # check if Mechanic was assigned to the job
            # otherwise forbid downloading the pdf

            mechanic_connected = st.connected_job.mechanics.filter(id__in=[request.user.id]).first()
            if not mechanic_connected:
                return Response('This PDF is not yours', status=status.HTTP_403_FORBIDDEN)

        # print(ServiceTicketReadSerializer(st))
        st_ctx = dict_none_defaults(ServiceTicketReadSerializer(st).data)

        template_name = 'service_tickets/service_ticket.html'

        response_pdf = render_to_pdf(template_name, st_ctx)
        if not response_pdf:
            return Response('PDF is not available', status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        timestamp = int(time.time())
        filename = f'service_ticket_{st.id}_{timestamp}.pdf'
        headers = {
            'Content-Disposition': f'inline; filename={filename}'
        }

        return Response(response_pdf, headers=headers, content_type='application/pdf')


class ServiceTicketExportView(APIView): 
    permission_classs = [IsAuthenticated,]

    def post(self, request, job_id):
        return Response({'status': 'error', 'message': 'method not allowed'}, status=status.HTTP_403_FORBIDDEN)

    def get(self, request, job_id):
        # print("Exporting tickets for job =", job_id)
        if ServiceTicket.objects.filter(connected_job__id=job_id).count() > 0:
            zip_archive = BytesIO()
            with zipfile.ZipFile(zip_archive, mode='w', compression=zipfile.ZIP_DEFLATED) as zip_file:
                for t in ServiceTicket.objects.filter(connected_job__id=job_id):
                    zip_file.writestr(str(t.id) + '.pdf', STExportView.as_view()(request._request, t.id).render().content)
            zip_file.close()

            response = HttpResponse(zip_archive.getvalue(), content_type='application/zip')
            # response.write(zip_archive)
            response['Content-Disposition'] = 'attachment; filename="job-{}-service-tickets.zip"'.format(job_id)
            return response
        else:
            return Response({'status': 'error', 'message': 'No service ticket exist'}, status=status.HTTP_400_BAD_REQUEST)


class DBLockView(APIView):

    permission_classes = [IsAuthenticated, ]

    def get(self, request):
        return Response({'status': 'error', 'message': 'method not allowed'}, status=status.HTTP_403_FORBIDDEN)

    def post(self, request):
        if request.user.is_admin:
            date = DBLockDate(lock_date=request.data.get('date', None))
            date.save()
            return Response({'status': 'success', 'message': 'DB Lock updated'}, status=status.HTTP_200_OK)
        else:
            return Response({'status': 'error', 'message': 'Only manager can lock the DB'},
                            status=status.HTTP_403_FORBIDDEN)
