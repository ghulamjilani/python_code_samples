# -*- coding: utf-8 -*-
import string
import random
import re

import pytz
from dacite import from_dict
from django.utils.safestring import SafeString
from django.template.loader import render_to_string
from dateutil.parser import parse
from django.utils.translation import gettext as _

from utils.entities.row_render import RowData


def split_camel_case(text):
    """Split camelCase into Camel case"""
    split = re.sub('([A-Z][a-z]+)', r' \1', re.sub('([A-Z]+)', r' \1', text)).split()
    label = " ".join(split)
    label = label.replace("-", " ").replace("_", " ")
    return label.capitalize()


class Render:
    """Helper class to render templates"""
    @staticmethod
    def row(row_data):
        return render_to_string('row.html', {'data': row_data})

    @staticmethod
    def sub_head(row_data):
        return render_to_string('sub_head.html', {'data': row_data})

    @staticmethod
    def subtitle(title):
        return render_to_string('sub_title.html', {'title': title})

    @staticmethod
    def divider():
        return render_to_string('divider.html')

    @staticmethod
    def end_sub_head():
        return render_to_string('end_sub_head.html', {})

    @staticmethod
    def table(fhir_resources, render_template='bundle_render.html'):
        """ Render data using django template system, return html string"""
        return render_to_string(render_template, {'fhir_data': fhir_resources}).encode('utf-8')


def save_html_render(html, save_path):
    """Save html string on file"""
    with open(save_path, 'wb') as f:
        f.write(html)
        f.close()


def format_date(date_str):
    """give format (yyyy-mm-dd) to a datetime string"""
    try:
        date_icon = ""
        pattern_date_time = "^[\d]{2,4}-[\d]{1,2}"
        match = re.match(pattern_date_time, date_str)
        if match:
            res = parse(date_str, fuzzy=False)
            return f"{date_icon} {res.strftime('%Y-%m-%d')}"
        else:
            return date_str
    except ValueError:
        return date_str


def generate_random_200_id():
    # initializing size of string
    id_length = 200
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=id_length))


def is_dict(obj):
    return type(obj) is dict


def is_list(obj):
    return type(obj) is list


def is_string(value):
    return type(value) is str or type(value) is SafeString


def get_resource_references(resource_ref_path):
    from apps.healthcare.models import FhirResource
    from utils.helpers.label import LabelUtil
    results: list[FhirResource] = FhirResource.objects.filter(
        resource_json__icontains=resource_ref_path
    ).exclude(resource_type="Bundle").all()
    references = []
    for result in results:
        res_type = result.resource_json.get("resourceType")
        desc: str = get_resource_description(result.resource_json)
        references.append(Render.row(
            RowData(
                label=_(LabelUtil.clean_label(res_type)),
                value=f"<a href='/health-data/{res_type}/{result.resource_id}'>&#128194; {desc.capitalize()}</a>"
            )
        ))
    return references


def get_code_or_type_or_category(obj):
    if obj.get('code'):
        return obj.get('code')
    elif obj.get('type'):
        return obj.get('type')
    elif obj.get('category'):
        return obj.get('category')
    return None


def handle_codeable(resource_):
    from fhir.datatypes.generalpurpose.coding import CodeableConcept
    if CodeableConcept.type(resource_):
        res = from_dict(CodeableConcept, resource_)
        return res.value()


def get_resource_description(obj):
    if obj.get('title'):
        return obj.get('title')
    resource_ = get_code_or_type_or_category(obj)
    if type(resource_) is dict:
        return handle_codeable(resource_)
    else:
        return handle_codeable(resource_[0])


def string_to_date(date_string):
    utc = pytz.UTC
    start_date = parse(date_string, fuzzy=False).replace(tzinfo=utc)
    return start_date
