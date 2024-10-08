import os
from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.authentication.tests.factories import (
    ManagerFactory, MechanicFactory, BillerFactory, AdminFactory
)

from apps.notifications.models import Action
from apps.authentication.tests.factories import UserFactory
from .factories import JobFactory, ServiceTicketFactory, EmployeeWorkBlockFactory
from ..models import CommonInfo, Settings, ServiceTicket
from ..utils import delete_file


class MockedRequest:
    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        return super().__init__(*args, **kwargs)


class TestJob(TestCase):

    def setUp(self):
        self.job = JobFactory()

    def test_str_method(self):
        self.assertEqual(str(self.job), f'Job #{self.job.number}')

    @patch('apps.api.models.RequestMiddleware')
    def test_open_status(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.assertEqual(self.job.status, CommonInfo.OPEN)
        self.job.status = CommonInfo.REJECTED
        self.job.save()
        self.assertRaises(ValidationError, self.job.clean)
        self.job.status = CommonInfo.APPROVED
        self.job.save()
        self.assertRaises(ValidationError, self.job.clean)
        self.job.status = CommonInfo.PENDING_FOR_APPROVAL
        self.job.save()
        self.assertEqual(self.job.status, CommonInfo.PENDING_FOR_APPROVAL)

    @patch('apps.api.models.RequestMiddleware')
    def test_rejected_status(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.job.status = CommonInfo.REJECTED
        self.job.save()
        self.assertEqual(self.job.status, CommonInfo.REJECTED)
        self.job.status = CommonInfo.APPROVED
        self.job.save()
        self.assertRaises(ValidationError, self.job.clean)
        self.job.status = CommonInfo.PENDING_FOR_APPROVAL
        self.job.save()
        self.assertEqual(self.job.status, CommonInfo.PENDING_FOR_APPROVAL)

    @patch('apps.api.models.RequestMiddleware')
    def test_approved_status(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.job.status = CommonInfo.APPROVED
        self.job.save()
        self.assertEqual(self.job.status, CommonInfo.APPROVED)
        self.job.status = CommonInfo.REJECTED
        self.job.save()
        self.assertRaises(ValidationError, self.job.clean)
        self.job.status = CommonInfo.PENDING_FOR_APPROVAL
        self.job.save()
        self.assertEqual(self.job.status, CommonInfo.PENDING_FOR_APPROVAL)

    @patch('apps.api.models.RequestMiddleware')
    def test_if_all_service_tickets_in_status_approved(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.services_ticket = ServiceTicketFactory(connected_job=self.job)
        self.assertEqual(self.job.id, self.services_ticket.connected_job.id)
        self.service_ticket = ServiceTicketFactory(connected_job=self.job)
        self.assertEqual(self.job.id, self.service_ticket.connected_job.id)
        self.job.status = CommonInfo.PENDING_FOR_APPROVAL
        self.job.save()
        self.assertRaises(ValidationError, self.job.clean)
        self.service_ticket.status = CommonInfo.APPROVED
        self.service_ticket.save()
        self.job.status = CommonInfo.PENDING_FOR_APPROVAL
        self.job.save()
        self.assertEqual(self.job.status, CommonInfo.PENDING_FOR_APPROVAL)

        delete_file(self.service_ticket.customer_signature.path)
        for attachment in self.service_ticket.attachments.all():
            delete_file(attachment.file.path)

    def test_create_st_is_pending_status(self):
        new_job = JobFactory(
            status=CommonInfo.PENDING_FOR_APPROVAL,
            requester=BillerFactory()
        ).clean()
        self.assertRaises(ValidationError, new_job)

    @patch('apps.api.models.RequestMiddleware')
    def test_requester_generation(self, mocked_req):
        user = UserFactory()
        mocked_req.get_request.return_value = MockedRequest(user=user)
        new_job = JobFactory()
        new_job.status = CommonInfo.PENDING_FOR_APPROVAL
        new_job.save()
        self.assertEqual(new_job.requester.id, user.id)
        new_job.status = CommonInfo.OPEN
        new_job.save()
        self.assertEqual(new_job.requester, None)

    @patch('apps.api.models.RequestMiddleware')
    def test_approval_generation(self, mocked_req):
        user = UserFactory()
        mocked_req.get_request.return_value = MockedRequest(user=user)
        new_job = ServiceTicketFactory()

        new_job.status = CommonInfo.PENDING_FOR_APPROVAL
        new_job.save()
        self.assertEqual(new_job.approval, None)

        new_job._original_status = CommonInfo.PENDING_FOR_APPROVAL
        new_job.status = CommonInfo.APPROVED
        new_job.save()
        self.assertEqual(new_job.approval.id, user.id)

    def test_signal_job_mechanics_changed(self):
        mechanic = MechanicFactory()
        action = Action.objects.filter(connected_users=mechanic.id)
        self.assertEqual(action.count(), 0)
        new_job = JobFactory(mechanics=[mechanic])
        action = Action.objects.filter(connected_users=mechanic.id)
        self.assertEqual(action.count(), 1)
        self.assertEqual(action.last().connected_object_id, new_job.id)

    def test_signal_job_managers_changed(self):
        manager = ManagerFactory()
        action = Action.objects.filter(connected_users=manager.id)
        self.assertEqual(action.count(), 0)
        new_job = JobFactory(managers=[manager])
        action = Action.objects.filter(connected_users=manager.id)
        self.assertEqual(action.count(), 1)
        self.assertEqual(action.last().connected_object_id, new_job.id)

    @patch('apps.api.models.RequestMiddleware')
    def test_request_job_closing_notifications(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        new_job = JobFactory(requester=BillerFactory())
        actions_before = Action.objects.filter(
            connected_object_id=new_job.id,
        ).count()
        new_job.status = CommonInfo.PENDING_FOR_APPROVAL
        new_job.save()
        actions_after = Action.objects.filter(
            connected_object_id=new_job.id,
        ).count()
        self.assertEqual(actions_after, actions_before + 1)

    @patch('apps.api.models.RequestMiddleware')
    def test_job_has_been_rejected_notifications(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        new_job = JobFactory()
        actions_before = Action.objects.filter(
            connected_object_id=new_job.id,
        ).count()
        new_job.status = CommonInfo.REJECTED
        new_job.save()
        actions_after = Action.objects.filter(
            connected_object_id=new_job.id,
        ).count()
        self.assertEqual(actions_after, actions_before + 1)


class TestServiceTicket(TestCase):

    def setUp(self):
        self.service_ticket = ServiceTicketFactory()

    def test_str_method(self):
        self.assertEqual(
            str(self.service_ticket),
            f'Service ticket #{self.service_ticket.connected_job.number}'
        )

    @patch('apps.api.models.RequestMiddleware')
    def test_open_status(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.assertEqual(self.service_ticket.status, CommonInfo.OPEN)
        self.service_ticket.status = CommonInfo.REJECTED
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)
        self.service_ticket.status = CommonInfo.APPROVED
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)
        self.service_ticket.status = CommonInfo.PENDING_FOR_APPROVAL
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.status, CommonInfo.PENDING_FOR_APPROVAL)

    @patch('apps.api.models.RequestMiddleware')
    def test_reject_description_required_for_manager(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=ManagerFactory())
        self.service_ticket.status = CommonInfo.REJECTED
        self.service_ticket.reject_description = ' '
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)

    @patch('apps.api.models.RequestMiddleware')
    def test_reject_description_required_for_biller(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=BillerFactory())
        self.service_ticket.status = CommonInfo.REJECTED
        self.service_ticket.reject_description = ' '
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)

    @patch('apps.api.models.RequestMiddleware')
    def test_reject_description_required_for_admin(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=AdminFactory())
        self.service_ticket.status = CommonInfo.REJECTED
        self.service_ticket.reject_description = ' '
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)

    @patch('apps.api.models.RequestMiddleware')
    def test_rejected_status(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.service_ticket.status = CommonInfo.REJECTED
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.status, CommonInfo.REJECTED)
        self.service_ticket.status = CommonInfo.APPROVED
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)
        self.service_ticket.status = CommonInfo.PENDING_FOR_APPROVAL
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.status, CommonInfo.PENDING_FOR_APPROVAL)

    @patch('apps.api.models.RequestMiddleware')
    def test_approved_status(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.service_ticket.status = CommonInfo.APPROVED
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.status, CommonInfo.APPROVED)
        self.service_ticket.status = CommonInfo.REJECTED
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)
        self.service_ticket.status = CommonInfo.PENDING_FOR_APPROVAL
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.status, CommonInfo.PENDING_FOR_APPROVAL)

    def test_cannot_be_edited_if_status_approved(self):
        self.service_ticket.status = CommonInfo.APPROVED
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.status, CommonInfo.APPROVED)
        self.service_ticket.lease_name = 'New lease_name'
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)

    @patch('apps.api.models.RequestMiddleware')
    def test_admin_edited_if_status_approved(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=AdminFactory())
        self.service_ticket.status = CommonInfo.PENDING_FOR_APPROVAL
        self.service_ticket.save()
        self.service_ticket.status = CommonInfo.APPROVED
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.status, CommonInfo.APPROVED)
        self.service_ticket.lease_name = 'New lease_name'
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.lease_name, 'New lease_name')

    def test_cannot_be_edited_if_job_assigned(self):
        initial_job = JobFactory(status=CommonInfo.OPEN)
        new_service_ticket = ServiceTicketFactory(connected_job=initial_job)
        new_job = JobFactory(status=CommonInfo.OPEN)
        new_service_ticket.connected_job = new_job
        self.assertRaises(ValidationError, new_service_ticket.clean)

    @patch('apps.api.models.RequestMiddleware')
    def test_job_is_approved_already(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        self.service_ticket.connected_job.status = CommonInfo.APPROVED
        self.service_ticket.connected_job.save()
        self.service_ticket.lease_name = 'New lease_name'
        self.service_ticket.save()
        self.assertRaises(ValidationError, self.service_ticket.clean)
        self.service_ticket.connected_job.status = CommonInfo.PENDING_FOR_APPROVAL
        self.service_ticket.connected_job.save()
        self.service_ticket.lease_name = 'New lease_name'
        self.service_ticket.save()
        self.assertEqual(self.service_ticket.lease_name, 'New lease_name')

    @patch('apps.api.models.RequestMiddleware')
    def test_job_is_pending_status(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        new_job = JobFactory(
            status=CommonInfo.PENDING_FOR_APPROVAL,
            requester=BillerFactory()
        )
        new_service_ticket = ServiceTicketFactory(connected_job=new_job)
        self.assertRaises(ValidationError, new_service_ticket.clean())

        delete_file(new_service_ticket.customer_signature.path)
        for attachment in new_service_ticket.attachments.all():
            delete_file(attachment.file.path)

    def tearDown(self):
        delete_file(self.service_ticket.customer_signature.path)
        for attachment in self.service_ticket.attachments.all():
            delete_file(attachment.file.path)

    @patch('apps.api.models.RequestMiddleware')
    def test_requester_generation(self, mocked_req):
        user = UserFactory()
        mocked_req.get_request.return_value = MockedRequest(user=user)
        st_job = ServiceTicketFactory()
        st_job.status = CommonInfo.PENDING_FOR_APPROVAL
        st_job.save()
        self.assertEqual(st_job.requester.id, user.id)
        st_job.status = CommonInfo.OPEN
        st_job.save()
        self.assertEqual(st_job.requester, None)

    @patch('apps.api.models.RequestMiddleware')
    def test_approval_generation(self, mocked_req):
        user = UserFactory()
        mocked_req.get_request.return_value = MockedRequest(user=user)
        st_job = ServiceTicketFactory()

        st_job.status = CommonInfo.PENDING_FOR_APPROVAL
        st_job.save()
        self.assertEqual(st_job.approval, None)

        st_job._original_status = CommonInfo.PENDING_FOR_APPROVAL
        st_job.status = CommonInfo.APPROVED
        st_job.save()
        self.assertEqual(st_job.approval.id, user.id)

    @patch('apps.api.models.RequestMiddleware')
    def test_request_st_approval_notifications(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        new_st = ServiceTicketFactory()
        actions_before = Action.objects.filter(
            connected_object_id=new_st.id,
        ).count()
        new_st.status = CommonInfo.PENDING_FOR_APPROVAL
        new_st.save()
        actions_after = Action.objects.filter(
            connected_object_id=new_st.id,
        ).count()
        self.assertEqual(actions_after, actions_before + 1)

    @patch('apps.api.models.RequestMiddleware')
    def test_st_has_been_rejected_notifications(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        job = JobFactory(
            status=CommonInfo.PENDING_FOR_APPROVAL,
            requester=BillerFactory()
        )
        new_st = ServiceTicketFactory(
            connected_job=job,
            status=CommonInfo.PENDING_FOR_APPROVAL,
            requester=UserFactory()
        )
        actions_before = Action.objects.filter(
            connected_object_id=new_st.id,
        ).count()
        new_st.status = CommonInfo.REJECTED
        new_st.save()
        actions_after = Action.objects.filter(
            connected_object_id=new_st.id,
        ).count()
        self.assertEqual(actions_after, actions_before + 1)

    @patch('apps.api.models.RequestMiddleware')
    def test_st_has_been_approved_notifications(self, mocked_req):
        mocked_req.get_request.return_value = MockedRequest(user=UserFactory())
        job = JobFactory(
            status=CommonInfo.PENDING_FOR_APPROVAL,
            requester=BillerFactory()
        )
        new_st = ServiceTicketFactory(
            connected_job=job,
            status=CommonInfo.PENDING_FOR_APPROVAL,
            requester=UserFactory()
        )
        actions_before = Action.objects.filter(
            connected_object_id=new_st.id,
        ).count()
        new_st.status = CommonInfo.APPROVED
        new_st.save()
        actions_after = Action.objects.filter(
            connected_object_id=new_st.id,
        ).count()
        self.assertEqual(actions_after, actions_before + 1)

    def test_total_worked_hours_if_not_hours(self):
        st = ServiceTicketFactory()
        employee_work = st.employee_works.first()
        employee_work.start_time = None
        employee_work.end_time = None
        employee_work.save()
        self.assertEqual(st.total_worked_hours, '')

    def test_total_worked_hours_with_filled_worked_hours(self):
        st = ServiceTicketFactory()
        employee_work = st.employee_works.all().delete()
        wb1 = EmployeeWorkBlockFactory(
            service_ticket_id=st.id,
            start_time=None,
            end_time=None
        )
        wb2 = EmployeeWorkBlockFactory(
            service_ticket_id=st.id,
            start_time=datetime.now(),
            end_time=None
        )
        wb3 = EmployeeWorkBlockFactory(
            service_ticket_id=st.id,
            start_time=None,
            end_time=datetime.now()
        )
        wb4 = EmployeeWorkBlockFactory(
            service_ticket_id=st.id,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(hours=1)
        )
        wb5 = EmployeeWorkBlockFactory(
            service_ticket_id=st.id,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(minutes=30)
        )
        st.employee_works.set([wb1, wb2, wb3, wb4, wb5])
        self.assertEqual(st.total_worked_hours, '1h 30m')

    def test_total_mileage(self):
        new_st: ServiceTicket = ServiceTicketFactory()
        new_st.employee_works.all().delete()
        wb1 = EmployeeWorkBlockFactory(service_ticket_id=new_st.id)
        wb1.mileage = 1.1
        wb1.save()
        wb2 = EmployeeWorkBlockFactory(service_ticket_id=new_st.id)
        wb2.mileage = 0
        wb2.save()
        wb3 = EmployeeWorkBlockFactory(service_ticket_id=new_st.id)
        wb3.mileage = 2.2
        wb3.save()
        self.assertEqual(new_st.total_mileage, '3.3')
