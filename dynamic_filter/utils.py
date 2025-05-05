"""
Utility classes for model filtering system.

This module provides utilities for value conversion, date parsing,
value extraction from requests, and query ordering functionality.
"""

from datetime import datetime
from typing import Any, Dict, Optional, Union, List, Type
import logging

from django.db import models
from django.http import QueryDict

from .constants import ORDERING_PARAM, DEFAULT_ORDERING, DATETIME_FORMATS, DATE_FORMATS


class ValueConverter:
    """
    Convert values based on field types with proper type handling.

    This class follows the Single Responsibility Principle by focusing solely
    on value conversion logic.
    """

    logger = logging.getLogger(__name__)

    @classmethod
    def convert_value(cls, value: Any, field_info: Dict) -> Any:
        """
        Convert a value based on its field type configuration.

        Args:
            value: The value to convert
            field_info: Dictionary with field configuration

        Returns:
            Converted value appropriate for the field type
        """
        if value is None:
            return None

        # Defensive programming - ensure field_info has required keys
        field_type = field_info.get('type')
        if not field_type:
            cls.logger.warning(f"No field type specified in field_info: {field_info}")
            return value

        try:
            # Handle different field types using dedicated converters
            if field_type == 'boolean':
                return cls.to_boolean(value)
            elif field_type == 'integer':
                return cls.to_integer(value)
            elif field_type == 'decimal':
                return cls.to_decimal(value)
            elif field_type == 'enum':
                return cls._convert_enum_value(value, field_info)

            # Default case - return as is
            return value
        except Exception as e:
            cls.logger.warning(f"Error converting value '{value}' for type '{field_type}': {e}")
            return value

    @classmethod
    def _convert_enum_value(cls, value: Any, field_info: Dict) -> Any:
        """
        Convert enum values based on field class.

        Args:
            value: The value to convert
            field_info: Dictionary with field configuration

        Returns:
            Converted enum value
        """
        if not field_info.get('enum_class'):
            return value

        field = field_info.get('field')
        if not field:
            return value

        # For CharField, TextField or similar with choices
        if isinstance(field, (models.CharField, models.TextField)):
            return cls._convert_list_or_single(value, str)

        # For IntegerField or similar with choices
        if isinstance(field, (models.IntegerField, models.PositiveIntegerField, models.SmallIntegerField)):
            return cls._convert_list_or_single(value, int)

        return value

    @staticmethod
    def _convert_list_or_single(value: Any, converter_func: Type) -> Any:
        """
        Apply converter function to either a single value or list of values.

        Args:
            value: Single value or list of values
            converter_func: Function to convert each value

        Returns:
            Converted value(s)
        """
        if isinstance(value, (list, tuple)):
            return [converter_func(v) for v in value]
        else:
            return converter_func(value)

    @staticmethod
    def to_boolean(value: Any) -> bool:
        """
        Convert a value to boolean with comprehensive handling.

        Args:
            value: Value to convert to boolean

        Returns:
            Boolean representation of the value
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', 't', 'yes', 'y', '1')
        return bool(value)

    @staticmethod
    def to_integer(value: Any) -> int:
        """
        Convert a value to integer with error handling.

        Args:
            value: Value to convert to integer

        Returns:
            Integer value or 0 if conversion fails
        """
        if value is None:
            return 0

        try:
            return int(float(value))  # Handle both '123' and '123.45'
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def to_decimal(value: Any) -> float:
        """
        Convert a value to decimal/float with error handling.

        Args:
            value: Value to convert to float

        Returns:
            Float value or 0.0 if conversion fails
        """
        if value is None:
            return 0.0

        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0


class DateParser:
    """
    Parse date and datetime values from strings with comprehensive format support.

    This class follows the Single Responsibility Principle by focusing solely
    on date parsing logic.
    """

    logger = logging.getLogger(__name__)

    @classmethod
    def parse_date(cls, value: str) -> Optional[datetime.date]:
        """
        Parse string to date object with multiple format support.

        Args:
            value: String representation of a date

        Returns:
            Date object or None if parsing fails
        """
        if not value or not isinstance(value, str):
            return None

        # Try all formats
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue

        cls.logger.debug(f"Could not parse date from '{value}'")
        return None

    @classmethod
    def parse_datetime(cls, value: str) -> Optional[datetime]:
        """
        Parse string to datetime object with multiple format support.

        Args:
            value: String representation of a datetime

        Returns:
            Datetime object or None if parsing fails
        """
        if not value or not isinstance(value, str):
            return None

        # Try all formats
        for fmt in DATETIME_FORMATS:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        cls.logger.debug(f"Could not parse datetime from '{value}'")
        return None

    @classmethod
    def register_format(cls, format_str: str, is_datetime: bool = False) -> None:
        """
        Register a new date/datetime format for parsing.

        Args:
            format_str: The format string (e.g., '%Y-%m-%d')
            is_datetime: Whether this is a datetime format (True) or date format (False)
        """
        if is_datetime:
            if format_str not in DATETIME_FORMATS:
                DATETIME_FORMATS.insert(0, format_str)  # Add to front for priority
        else:
            if format_str not in DATE_FORMATS:
                DATE_FORMATS.insert(0, format_str)


class RequestValueExtractor:
    """
    Extract and validate values from request data.

    This class follows the Single Responsibility Principle by focusing solely
    on value extraction logic.
    """

    def __init__(self, request_data: Union[Dict, QueryDict]):
        """
        Initialize with request data.

        Args:
            request_data: Dict or QueryDict containing request parameters
        """
        self.request_data = request_data or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def get_value(self, field_name: str, default: Any = None) -> Any:
        """
        Get values for a field from request data, handling multiple values correctly.

        Args:
            field_name: Name of the field
            default: Default value if field not found

        Returns:
            Single value or list of values depending on the request data
        """
        if not field_name:
            return default

        try:
            # Handle QueryDict (from request.GET/POST)
            if isinstance(self.request_data, QueryDict):
                return self._extract_from_query_dict(field_name, default)
            else:
                # Regular dict behavior
                return self.request_data.get(field_name, default)
        except Exception as e:
            self.logger.warning(f"Error extracting value for field '{field_name}': {e}")
            return default

    def _extract_from_query_dict(self, field_name: str, default: Any = None) -> Any:
        """
        Extract value(s) from a QueryDict object.

        Args:
            field_name: Name of the field
            default: Default value if field not found

        Returns:
            Single value, list of values, or default
        """
        # getlist returns all values for a parameter
        values = self.request_data.getlist(field_name)
        if len(values) > 1:
            return values
        elif len(values) == 1:
            return values[0]
        return default

    def has_param(self, field_name: str) -> bool:
        """
        Check if a parameter exists in the request data.

        Args:
            field_name: Name of the field to check

        Returns:
            True if parameter exists, False otherwise
        """
        return field_name in self.request_data

    def get_all_params(self) -> Dict:
        """
        Get all parameters as a dictionary.

        Returns:
            Dictionary of all parameters
        """
        if isinstance(self.request_data, QueryDict):
            return self.request_data.dict()
        return dict(self.request_data)


class OrderingBuilder:
    """
    Build ordering expressions for querysets.

    This class handles the construction of ordering parameters for Django ORM.
    """

    def __init__(self, value_extractor: RequestValueExtractor, field_registry: Dict[str, Dict]):
        """
        Initialize with dependencies.

        Args:
            value_extractor: Extractor for request values
            field_registry: Registry of available fields
        """
        self.value_extractor = value_extractor
        self.field_registry = field_registry
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def build_ordering(self) -> List[str]:
        """
        Build a list of ordering expressions for queryset.order_by().

        Returns:
            List of field names for ordering, with appropriate prefixes
        """
        # Get ordering parameter with fallback to default
        ordering_param = self.value_extractor.get_value(ORDERING_PARAM, DEFAULT_ORDERING)
        if not ordering_param:
            return []

        # Parse ordering fields into a list
        ordering_fields = self._parse_ordering_param(ordering_param)
        if not ordering_fields:
            return []

        # Process each field and validate
        return self._process_ordering_fields(ordering_fields)

    def _parse_ordering_param(self, ordering_param: Union[str, List]) -> List[str]:
        """
        Parse ordering parameter into a list of field names.

        Args:
            ordering_param: String or list representation of ordering fields

        Returns:
            List of field names
        """
        if isinstance(ordering_param, list):
            return [field.strip() for field in ordering_param if field.strip()]
        elif isinstance(ordering_param, str):
            return [field.strip() for field in ordering_param.split(',') if field.strip()]
        return []

    def _process_ordering_fields(self, ordering_fields: List[str]) -> List[str]:
        """
        Process ordering fields to ensure they're valid and map to correct paths.

        Args:
            ordering_fields: List of raw ordering field names

        Returns:
            List of validated field paths for ordering
        """
        valid_ordering = []

        for field in ordering_fields:
            # Skip empty fields
            if not field:
                continue

            # Handle descending order prefix
            prefix = ''
            field_name = field

            if field.startswith('-'):
                prefix = '-'
                field_name = field[1:]

            # Validate field exists in registry
            if field_name in self.field_registry:
                field_info = self.field_registry[field_name]
                valid_ordering.append(f"{prefix}{field_info['field_path']}")

        return valid_ordering
