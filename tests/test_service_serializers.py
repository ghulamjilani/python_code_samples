from django.test import TestCase
from django.conf import settings

from apps.authentication.tests.factories import ManagerFactory, MechanicFactory
from .factories import JobFactory, ServiceTicketFactory
from ..models import ServiceTicket
from ..serializers import (
    JobReadSerializer, JobWriteSerializer, ServiceTicketReadSerializer
)
from ..utils import delete_file


class TestJobReadSerializer(TestCase):

    def setUp(self):
        self.manager = ManagerFactory()
        self.mechanic = MechanicFactory()
        self.job = JobFactory(managers=(self.manager,), mechanics=(self.mechanic,))

    def test_get_valid_user_fields(self):
        serializer = JobReadSerializer(self.job)
        self.assertEqual(serializer.data.get('id'), self.job.id)
        self.assertEqual(serializer.data.get('created_by').get('id'), self.job.created_by.id)
        self.assertEqual(serializer.data.get('description'), self.job.description)
        self.assertEqual(serializer.data.get('customer').get('id'), self.job.customer.id)
        self.assertEqual(serializer.data.get('location'), self.job.location.name)
        self.assertEqual(serializer.data.get('status').get('value'), self.job.status)
        self.assertEqual(
            serializer.data.get('managers')[0].get('id'), self.job.managers.first().id
        )
        self.assertEqual(
            serializer.data.get('mechanics')[0].get('id'), self.job.mechanics.first().id
        )
        self.assertEqual(serializer.data.get('number'), self.job.number)
        self.assertEqual(
            serializer.data.get('approved_tickets'),
            self.job.serviceticket_set.filter(status=ServiceTicket.APPROVED).count()
        )
        self.assertEqual(serializer.data.get('total_tickets'), self.job.serviceticket_set.count())


class TestJobWriteSerializer(TestCase):

    def setUp(self):
        self.manager = ManagerFactory()
        self.mechanic = MechanicFactory()
        self.job = JobFactory(managers=(self.manager,), mechanics=(self.mechanic,))

    def test_get_valid_user_fields(self):
        serializer = JobWriteSerializer(self.job)
        self.assertEqual(serializer.data.get('id'), self.job.id)
        self.assertEqual(serializer.data.get('created_by').get('id'), self.job.created_by.id)
        self.assertEqual(serializer.data.get('description'), self.job.description)
        self.assertEqual(serializer.data.get('customer').get('id'), self.job.customer.id)
        self.assertEqual(serializer.data.get('location'), self.job.location.name)
        self.assertEqual(serializer.data.get('status').get('value'), self.job.status)
        self.assertEqual(
            serializer.data.get('managers')[0].get('id'), self.job.managers.first().id
        )
        self.assertEqual(
            serializer.data.get('mechanics')[0].get('id'), self.job.mechanics.first().id
        )
        self.assertEqual(serializer.data.get('number'), self.job.number)


class TestServiceTicketReadSerializer(TestCase):

    def setUp(self):
        self.st = ServiceTicketFactory()

    def tearDown(self):
        delete_file(self.st.customer_signature.path)
        for attachment in self.st.attachments.all():
            delete_file(attachment.file.path)

    def test_get_valid_user_fields(self):
        serializer = ServiceTicketReadSerializer(self.st)
        self.assertEqual(serializer.data.get('id'), self.st.id)
        self.assertEqual(serializer.data.get('created_by').get('id'), self.st.created_by.id)
        self.assertEqual(serializer.data.get('connected_job').get('id'), self.st.connected_job.id)
        self.assertEqual(serializer.data.get('date'), self.st.date)
        self.assertEqual(serializer.data.get('unit'), self.st.unit)
        self.assertEqual(serializer.data.get('lease_name'), self.st.lease_name)
        self.assertEqual(serializer.data.get('county'), self.st.county)
        self.assertEqual(serializer.data.get('state').get('value'), self.st.state)
        self.assertEqual(serializer.data.get('total_worked_hours'), self.st.total_worked_hours)
        self.assertEqual(
            serializer.data.get('connected_job').get('customer').get('id'),
            self.st.connected_job.customer.id
        )
        self.assertEqual(
            serializer.data.get('connected_job').get('location'),
            self.st.connected_job.location.name
        )
        self.assertEqual(serializer.data.get('customer_po_wo'), self.st.customer_po_wo)
        self.assertEqual(serializer.data.get('who_called'), self.st.who_called)
        self.assertEqual(serializer.data.get('engine_model'), self.st.engine_model)
        self.assertEqual(serializer.data.get('engine_serial'), self.st.engine_serial)
        self.assertEqual(serializer.data.get('comp_model'), self.st.comp_model)
        self.assertEqual(serializer.data.get('comp_serial'), self.st.comp_serial)
        self.assertEqual(serializer.data.get('unit_hours'), self.st.unit_hours)
        self.assertEqual(serializer.data.get('rpm'), '{0:0.1f}'.format(self.st.rpm))
        self.assertEqual(serializer.data.get('suction'), '{0:0.1f}'.format(self.st.suction))
        self.assertEqual(serializer.data.get('discharge1'), '{0:0.1f}'.format(self.st.discharge1))
        self.assertEqual(serializer.data.get('discharge2'), '{0:0.1f}'.format(self.st.discharge2))
        self.assertEqual(serializer.data.get('discharge3'), '{0:0.1f}'.format(self.st.discharge3))
        self.assertEqual(
            serializer.data.get('safety_setting_lo1'),
            '{0:0.1f}'.format(self.st.safety_setting_lo1)
        )
        self.assertEqual(
            serializer.data.get('safety_setting_lo2'),
            '{0:0.1f}'.format(self.st.safety_setting_lo2)
        )
        self.assertEqual(
            serializer.data.get('safety_setting_lo3'),
            '{0:0.1f}'.format(self.st.safety_setting_lo3)
            )
        self.assertEqual(
            serializer.data.get('safety_setting_lo4'),
            '{0:0.1f}'.format(self.st.safety_setting_lo4)
            )
        self.assertEqual(
            serializer.data.get('safety_setting_lo5'),
            '{0:0.1f}'.format(self.st.safety_setting_lo5)
            )
        self.assertEqual(
            serializer.data.get('safety_setting_hi1'),
            '{0:0.1f}'.format(self.st.safety_setting_hi1)
            )
        self.assertEqual(
            serializer.data.get('safety_setting_hi2'),
            '{0:0.1f}'.format(self.st.safety_setting_hi2)
            )
        self.assertEqual(
            serializer.data.get('safety_setting_hi3'),
            '{0:0.1f}'.format(self.st.safety_setting_hi3)
            )
        self.assertEqual(
            serializer.data.get('safety_setting_hi4'),
            '{0:0.1f}'.format(self.st.safety_setting_hi4)
            )
        self.assertEqual(
            serializer.data.get('safety_setting_hi5'),
            '{0:0.1f}'.format(self.st.safety_setting_hi5)
            )
        self.assertEqual(
            serializer.data.get('engine_oil_pressure'),
            '{0:0.1f}'.format(self.st.engine_oil_pressure)
        )
        self.assertEqual(
            serializer.data.get('engine_oil_temp'),
            '{0:0.1f}'.format(self.st.engine_oil_temp)
        )
        self.assertEqual(
            serializer.data.get('compressor_oil_pressure'),
            '{0:0.1f}'.format(self.st.compressor_oil_pressure)
        )
        self.assertEqual(
            serializer.data.get('compressor_oil_temp'),
            '{0:0.1f}'.format(self.st.compressor_oil_temp)
        )
        self.assertEqual(serializer.data.get('ts1'), '{0:0.1f}'.format(self.st.ts1))
        self.assertEqual(serializer.data.get('ts2'), '{0:0.1f}'.format(self.st.ts2))
        self.assertEqual(serializer.data.get('ts3'), '{0:0.1f}'.format(self.st.ts3))
        self.assertEqual(serializer.data.get('ts4'), '{0:0.1f}'.format(self.st.ts4))
        self.assertEqual(serializer.data.get('td2'), '{0:0.1f}'.format(self.st.td2))
        self.assertEqual(serializer.data.get('td1'), '{0:0.1f}'.format(self.st.td1))
        self.assertEqual(serializer.data.get('td3'), '{0:0.1f}'.format(self.st.td3))
        self.assertEqual(serializer.data.get('td4'), '{0:0.1f}'.format(self.st.td4))
        self.assertEqual(
            serializer.data.get('cylinder_temperature_hi1'),
            '{0:0.1f}'.format(self.st.cylinder_temperature_hi1)
        )
        self.assertEqual(
            serializer.data.get('cylinder_temperature_hi2'),
            '{0:0.1f}'.format(self.st.cylinder_temperature_hi2)
        )
        self.assertEqual(
            serializer.data.get('cylinder_temperature_hi3'),
            '{0:0.1f}'.format(self.st.cylinder_temperature_hi3)
        )
        self.assertEqual(
            serializer.data.get('cylinder_temperature_hi4'),
            '{0:0.1f}'.format(self.st.cylinder_temperature_hi4)
        )
        self.assertEqual(
            serializer.data.get('exhaust_temperature_l'),
            '{0:0.1f}'.format(self.st.exhaust_temperature_l)
        )
        self.assertEqual(
            serializer.data.get('exhaust_temperature_r'),
            '{0:0.1f}'.format(self.st.exhaust_temperature_r)
        )
        self.assertEqual(
            serializer.data.get('exhaust_temperature_hi'),
            '{0:0.1f}'.format(self.st.exhaust_temperature_hi)
        )
        self.assertEqual(
            serializer.data.get('manifold_temperature_l'),
            '{0:0.1f}'.format(self.st.manifold_temperature_l)
        )
        self.assertEqual(
            serializer.data.get('manifold_temperature_r'),
            '{0:0.1f}'.format(self.st.manifold_temperature_r)
        )
        self.assertEqual(
            serializer.data.get('manifold_temperature_hi'),
            '{0:0.1f}'.format(self.st.manifold_temperature_hi)
        )
        self.assertEqual(serializer.data.get('manifold_pressure_l'),
        '{0:0.1f}'.format(self.st.manifold_pressure_l))
        self.assertEqual(serializer.data.get('manifold_pressure_r'),
        '{0:0.1f}'.format(self.st.manifold_pressure_r))
        self.assertEqual(
            serializer.data.get('manifold_pressure_hi1'),
            '{0:0.1f}'.format(self.st.manifold_pressure_hi1)
        )
        self.assertEqual(
            serializer.data.get('manifold_pressure_hi2'),
            '{0:0.1f}'.format(self.st.manifold_pressure_hi2)
        )
        self.assertEqual(serializer.data.get('lo_hi'), '{0:0.1f}'.format(self.st.lo_hi))
        self.assertEqual(
            serializer.data.get('jacket_water_pressure'),
            '{0:0.1f}'.format(self.st.jacket_water_pressure)
        )
        self.assertEqual(serializer.data.get('mmcfd'), '{0:0.1f}'.format(self.st.mmcfd))
        self.assertEqual(serializer.data.get('aux_temp'), '{0:0.1f}'.format(self.st.aux_temp))
        self.assertEqual(
            serializer.data.get('hour_meter_reading'),
            '{0:0.1f}'.format(self.st.hour_meter_reading)
        )
        self.assertEqual(serializer.data.get('what_was_the_call'), self.st.what_was_the_call)
        self.assertEqual(serializer.data.get('what_was_found'), self.st.what_was_found)
        self.assertEqual(serializer.data.get('what_was_performed'), self.st.what_was_performed)
        self.assertEqual(serializer.data.get('future_work_needed'), self.st.future_work_needed)
        self.assertEqual(serializer.data.get('additional_notes'), self.st.additional_notes)
        self.assertEqual(
            serializer.data.get('customer_printed_name'), self.st.customer_printed_name
        )
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('id'), self.st.employee_works.first().id
        )
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('start_time'),
            self.st.employee_works.first().start_time.strftime(
                settings.REST_FRAMEWORK.get('DATETIME_FORMAT')
            )
        )
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('end_time'),
            self.st.employee_works.first().end_time.strftime(
                settings.REST_FRAMEWORK.get('DATETIME_FORMAT')
            )
        )
        employee_work = self.st.employee_works.first()
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('mileage'),
            '{0:0.1f}'.format(employee_work.mileage)
        )
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('hotel'),
            employee_work.hotel
        )
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('per_diem'),
            employee_work.per_diem
        )
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('hours_worked'),
            '%d:%02d' % divmod(divmod(employee_work.hours_worked.total_seconds(), 60)[0], 60)
        )
        self.assertEqual(
            serializer.data.get('employee_works')[0].get('employee').get('id'),
            employee_work.employee.id
        )
        attachment = self.st.attachments.first()
        self.assertEqual(len(serializer.data.get('attachments')), self.st.attachments.count())
        self.assertEqual(
            serializer.data.get('attachments')[0].get('description'),
            attachment.description
        )
        self.assertEqual(
            serializer.data.get('attachments')[0].get('id'),
            attachment.id
        )
