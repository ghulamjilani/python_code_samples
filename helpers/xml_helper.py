import re
from functools import cache

from django.utils.translation import gettext as _
from lxml import etree

from utils.app_exceptions import PgoHttpException
from utils.config import GlobalConfig
from utils.decorators.decorators import performance_time
from utils.helpers.pgo_regex import Pgex
from utils.pgo_logger import PgoLogger
import lxml.etree as et

conf: GlobalConfig = GlobalConfig()
logger: PgoLogger = PgoLogger()


class XmlHelper:

    @staticmethod
    @cache
    def validate_xml(xsd_file, xml_path):
        xmlschema = etree.XMLSchema(etree.parse(xsd_file))
        xml_file = etree.parse(xml_path)
        return xmlschema.validate(xml_file)

    @staticmethod
    @performance_time
    def validate_res_xml(providers_xml_path, services_xml_path, whitelist_xml_path):
        """Validate xml file data"""

        services_valid = XmlHelper.validate_xml(conf.service_validation_file, services_xml_path)
        if not services_valid:
            logger.error("Services xml validation fail")
            raise PgoHttpException(status=403, message=_("Services xml validation fail"))
        logger.info("Services xml is valid...")

        whitelist_valid = XmlHelper.validate_xml(conf.whitelist_validation_file, whitelist_xml_path)
        if not whitelist_valid:
            logger.error("Whitelist xml validation fail")
            raise PgoHttpException(status=403, message=_("Whitelist xml validation fail"))
        logger.info("Whitelist xml is valid...")

        providers_valid = XmlHelper.validate_xml(conf.provider_validation_file, providers_xml_path)
        if not providers_valid:
            logger.error("Providers xml validation fail")
            raise PgoHttpException(status=403, message=_("Providers xml validation fail"))
        logger.info("Providers xml is valid...")



    @staticmethod
    def provider_iter_parser(xml_file):
        """Return the parser, xml namespace and desired tag"""
        events_ = ('start', 'end')
        # get the xml name_space
        parser = et.iterparse(xml_file, events=events_)
        ev, el = next(parser)
        name_space = Pgex.xml_namespace(el)
        wanted_tag = f"{name_space}Zorgaanbieder"
        parser = et.iterparse(xml_file, events=events_, tag=wanted_tag)
        return parser, name_space, wanted_tag
