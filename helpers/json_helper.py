from dataclasses import dataclass, field
from typing import Union, TypeVar

from dacite import from_dict
from django.utils.translation import gettext as _
from fhir.constraints import Constraints
from fhir.datatypes.extension import Extension
from fhir.datatypes.complex.attachment import Attachment
from fhir.datatypes.generalpurpose.coding import CodeableConcept
from fhir.datatypes.generalpurpose.identifier import Identifier
from fhir.datatypes.generalpurpose.quantity import Quantity
from fhir.datatypes.generalpurpose.range import Range, ReferenceRange
from fhir.datatypes.generalpurpose.period import Period
from fhir.datatypes.generalpurpose.timing import TimingRepeat
from fhir.datatypes.others.activity import Activity
from fhir.datatypes.others.address import Address
from fhir.datatypes.others.collections import Collection
from fhir.datatypes.others.communication import Communication
from fhir.datatypes.others.name import HumanName
from fhir.datatypes.others.telecom import ContactPoint
from fhir.datatypes.others.vaccine import DateCriterion
from fhir.datatypes.sections.component import Component
from fhir.datatypes.specialpurpose.dosage import Dosage
from fhir.datatypes.specialpurpose.reference import Reference
from fhir.foundation.conformance.structure_definition import ProfileHandler
from fhir.foundation.domain_resource import DomainResource
from fhir.terminology import Terminology
from utils.decorators.decorators import apply_constrains, decorate_flat_value
from utils.handlers.activity_handler import ActivityHandler
from utils.handlers.codeable_concept_handler import CodeableConceptHandler
from utils.handlers.collection_handler import CollectionHandler
from utils.handlers.component_handler import ComponentHandler
from utils.handlers.dosage_handler import DosageHandler
from utils.handlers.extension_handler import ExtensionHandler
from utils.handlers.name_handler import HumanNameHandler
from utils.handlers.reference_handler import ReferenceHandler
from utils.handlers.relationship_handler import RelationshipHandler
from utils.helpers.core_helpers import format_date, Render
from utils.helpers.label import LabelUtil
from utils.helpers.string import String

T = TypeVar('T')


@dataclass()
class JsonHelper:
    terminology: Terminology
    resource: DomainResource
    flattened_values: list = field(default_factory=list, init=False)
    constrains: Constraints = Constraints()

    def start_flattening(self):
        self.flatten_resource(
            json_obj=self.resource.json_resource,
            json_path=self.resource.resourceType,
            profile=self.resource.meta_profile
        )

    @decorate_flat_value
    def handle_property(self, json_obj, json_path, profile):
        """Handle a final value of the json: ie: string, int"""
        label = LabelUtil.get_label(profile, json_path)
        # print(json_path)
        json_obj = format_date(str(json_obj))
        row = Render.row(
            {'label': label, 'value': _(str(json_obj))})
        self.flattened_values.append(row)

    @apply_constrains
    def handle_contained(self, json_obj, json_path, profile):
        if type(json_obj) is list:
            for _obj in json_obj:
                self.flattened_values.append(Render.sub_head(
                    f"{_(_obj.get('resourceType', ''))}"))
                self.flatten_resource(json_obj, json_path, profile)
                self.flattened_values.append(Render.end_sub_head())
        else:
            self.flatten_resource(json_obj, json_path, profile)

    def iter_dict_object(self, json_obj, json_path, profile):
        """Iterate over dict keys"""
        for key in json_obj:
            if key.startswith('div'):
                self.flattened_values.append(
                    f'<tr><td colspan="2" class="value">{json_obj[key]}</td></tr>')
            elif key.startswith('contained'):
                self.handle_contained(
                    json_obj[key], f"{json_path}.{key}", profile)
            else:
                self.flatten_resource(json_obj[key], f"{json_path}.{key}", profile)

    def iter_dict_list(self, json_obj, json_path, profile):
        for entry in json_obj:
            self.flatten_resource(entry, json_path, profile)
            if json_path.split('.')[-1] in ['performer', 'participant', 'activity', 'section']:
                self.flattened_values.append(Render.divider())

    def create_section(self, json_obj, json_path, profile):
        profiler = ProfileHandler(profile)
        # get profile for this path
        _profile = String.profile_id(profiler.search_profile(json_path))
        # get base path for this new profile
        base_path = profiler.search_type(json_path)
        if _profile and base_path:
            head_label = LabelUtil.get_label(_profile, base_path)
        else:
            head_label = LabelUtil.get_label(profile_name=profile, path=json_path)
        self.flattened_values.append(Render.sub_head(head_label))
        self.iter_dict_list(json_obj, json_path, profile)
        self.flattened_values.append(Render.end_sub_head())

    @apply_constrains
    def flatten_resource(self, json_obj: Union[dict, list, T], json_path: str, profile: str):
        # print(json_path)
        if type(json_obj) is dict:
            if Extension.type(json_obj):
                results = ExtensionHandler(
                    json_obj=json_obj, path=json_path,
                    profile=profile, terminology=self.terminology
                ).handle()
                if type(results) is list and len(results) > 0:
                    self.flattened_values += results
                else:
                    self.flattened_values.append(results)
            elif HumanName.type(json_path):
                HumanNameHandler(
                    json_obj=json_obj, path=json_path, profile=profile
                ).handle(self)
            elif ContactPoint.type(json_path):
                ContactPoint.manage(json_obj, json_path, profile, self)
            elif Address.type(json_path):
                Address.manage(json_obj, profile, json_path, self)
            elif DateCriterion.type(json_path):
                self.flattened_values += DateCriterion.handle(json_obj, self.terminology)
            elif CodeableConcept.type(json_obj) or json_path.endswith('class'):
                concept = json_obj
                if json_path.endswith('class') and not json_obj.get('coding'):
                    concept = {'coding': [json_obj]}
                self.flattened_values += (CodeableConceptHandler(
                    json_obj=concept, path=json_path, profile=profile,
                    terminology=self.terminology
                ).handle())
            elif Component.type(json_path):
                self.flattened_values += (ComponentHandler(
                    json_obj=json_obj, path=json_path, profile=profile,
                    terminology=self.terminology
                ).handle())
            elif Dosage.type(json_path):
                self.flattened_values += (DosageHandler(
                    json_obj=json_obj, path=json_path, profile=profile,
                    terminology=self.terminology
                ).handle())
            elif Activity.type(json_path):
                ActivityHandler(
                    json_obj=json_obj, path=json_path, profile=profile,
                    terminology=self.terminology
                ).handle(self)
            elif Collection.type(json_path):
                self.flattened_values += (CollectionHandler(
                    json_obj=json_obj, path=json_path, profile=profile,
                    terminology=self.terminology
                ).handle())
            elif TimingRepeat.type(json_path):
                self.flattened_values += TimingRepeat.handle(json_obj, json_path, profile)
                if TimingRepeat.has_extension(json_obj):
                    self.flatten_resource(TimingRepeat.has_extension(json_obj), f"{json_path}.extension", profile)
            elif Communication.instance(json_path):
                Communication.manage(json_obj, json_path, profile, self)
            elif Reference.type(json_obj):
                self.flattened_values += ReferenceHandler(
                    json_obj=json_obj, path=json_path, profile=profile
                ).handle()
            elif Range.type(json_obj):
                self.flattened_values.append(Range.handle(json_obj, profile, json_path))
            elif ReferenceRange.type(json_obj, json_path):
                self.flattened_values += ReferenceRange.handle(json_obj, profile, json_path, self)
            elif Identifier.type(json_obj):
                self.flattened_values += Identifier.handle(json_obj)
            elif Period.type(json_obj):
                self.flattened_values += Period.handle(json_obj, json_path, profile)
            elif Quantity.type(json_obj):
                self.flattened_values.append(Quantity.handle(json_obj, profile, json_path))
            elif Attachment.type(json_obj):
                self.flattened_values += Attachment.handle(json_obj)
            else:
                self.iter_dict_object(json_obj, json_path, profile)
        elif type(json_obj) is list:
            if RelationshipHandler.type(json_obj):
                handler = from_dict(RelationshipHandler, {'relationship': json_obj})
                self.flattened_values.append(handler.handle())
            elif json_path.endswith('contact'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('content'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('telecom'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('component'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('participant'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('performer'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('section'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('entry'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.endswith('activity'):
                self.create_section(json_obj, json_path, profile)
            elif json_path.split('.')[-1] in ['dosage', 'dosageInstruction']:
                self.create_section(json_obj, json_path, profile)
            else:
                self.iter_dict_list(json_obj, json_path, profile)
        else:
            self.handle_property(json_obj, json_path, profile)

