from abc import ABC, abstractmethod
import logging
import json
from urllib import parse
from typing import Dict, Any, Optional, List, Callable

from django.db.models import Q
from .constants import SEARCH_PARAM, ADVANCED_FILTER_PARAM
from .utils import RequestValueExtractor, DateParser, ValueConverter


class FilterStrategy(ABC):
    """Abstract base class for filter strategies"""

    @abstractmethod
    def build_query(self, field_info: Dict, value: Any = None, **kwargs) -> Optional[Q]:
        """
        Build a Q object for filtering

        Args:
            field_info: Dictionary containing field metadata
            value: The value to filter by (optional)
            **kwargs: Additional parameters for specific strategies

        Returns:
            Optional[Q]: A Django Q object for filtering, or None if no filter should be applied
        """
        pass


class BaseFieldFilterStrategy(FilterStrategy):
    """Strategy for building basic field filters"""

    def __init__(self, value_extractor: RequestValueExtractor, logger=None):
        """
        Initialize the strategy

        Args:
            value_extractor: Helper for extracting values from request
            logger: Optional logger instance
        """
        self.value_extractor = value_extractor
        self.logger = logger or logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def build_query(self, field_info: Dict, value: Any = None, lookup: str = None, **kwargs) -> Optional[Q]:
        """
        Build a Q object for a basic field filter

        Args:
            field_info: Dictionary containing field metadata
            value: Value to filter by (optional, will be extracted if not provided)
            lookup: Lookup expression to use (optional, will use default if not provided)

        Returns:
            Optional[Q]: A Django Q object for filtering, or None if no filter should be applied
        """
        # Skip non-filterable fields
        if not field_info.get("filterable", True):
            return None

        field_path = field_info['field_path']

        # Get value if not provided
        if value is None:
            value = self.value_extractor.get_value(field_path)
            if value is None or value == '':
                return None

        # Handle lookup selection
        lookup = self._resolve_lookup(field_info, lookup)

        # Handle null values specifically
        if value is None or (isinstance(value, str) and value.lower() == 'null'):
            return Q(**{f"{field_path}__isnull": True})

        # Process 'in' lookup values
        if lookup == 'in':
            value = self._prepare_in_lookup_value(value)

        # Convert value based on field type
        value = ValueConverter.convert_value(value, field_info)

        # Build and return Q object
        return Q(**{f"{field_path}__{lookup}": value})

    def _resolve_lookup(self, field_info: Dict, lookup: str = None) -> str:
        """
        Resolve the lookup to use, falling back to default if needed

        Args:
            field_info: Field metadata dictionary
            lookup: Requested lookup expression

        Returns:
            str: The resolved lookup expression
        """
        # Use provided lookup or fall back to default
        resolved_lookup = lookup or field_info['default_lookup']

        # Validate lookup is allowed for this field
        if resolved_lookup not in field_info.get('lookups', []):
            self.logger.warning(
                f"Lookup '{resolved_lookup}' not allowed for field '{field_info['field_path']}'. "
                f"Using default: {field_info['default_lookup']}"
            )
            resolved_lookup = field_info['default_lookup']

        return resolved_lookup

    def _prepare_in_lookup_value(self, value: Any) -> List:
        """
        Prepare a value for use with the 'in' lookup

        Args:
            value: The value to prepare

        Returns:
            List: A list of values suitable for the 'in' lookup
        """
        if isinstance(value, (list, tuple)):
            return value

        if isinstance(value, str) and ',' in value:
            return [item.strip() for item in value.split(',')]

        return [value]


class SearchFilterStrategy(FilterStrategy):
    """Strategy for building text search filters across multiple fields"""

    def __init__(self, value_extractor: RequestValueExtractor):
        """
        Initialize the strategy

        Args:
            value_extractor: Helper for extracting values from request
        """
        self.value_extractor = value_extractor

    def build_query(self, field_registry: Dict[str, Dict], **kwargs) -> Optional[Q]:
        """
        Build a Q object for text search across multiple fields

        Args:
            field_registry: Dictionary of field information

        Returns:
            Optional[Q]: A Django Q object for search filtering, or None if no search term
        """
        # Get search term
        search_term = self._get_search_term()
        if not search_term:
            return None

        q_obj = Q()
        has_searchable_field = False

        # Process each searchable field
        for field_name, field_info in field_registry.items():
            if not field_info.get('searchable', False):
                continue

            has_searchable_field = True
            field_q = self._build_field_search_query(field_info, search_term)
            if field_q:
                q_obj |= field_q

        return q_obj if has_searchable_field else None

    def _get_search_term(self) -> Optional[str]:
        """
        Get and validate the search term

        Returns:
            Optional[str]: The validated search term or None
        """
        search_term = self.value_extractor.get_value(SEARCH_PARAM)

        if not search_term or not isinstance(search_term, str):
            return None

        search_term = search_term.strip()
        if not search_term:
            return None

        return search_term

    def _build_field_search_query(self, field_info: Dict, search_term: str) -> Optional[Q]:
        """
        Build a search query for a specific field

        Args:
            field_info: Field metadata dictionary
            search_term: The term to search for

        Returns:
            Optional[Q]: A Django Q object for this field's search or None
        """
        field_path = field_info["field_path"]
        field_type = field_info['type']

        # Handle text fields
        if field_type == 'text':
            return Q(**{f"{field_path}__icontains": search_term})

        # Handle enum fields - search in enum labels
        if field_type == 'enum' and field_info.get('enum_class'):
            matching_values = self._find_matching_enum_values(field_info['enum_class'], search_term)
            if matching_values:
                return Q(**{f"{field_path}__in": matching_values})

        return None

    def _find_matching_enum_values(self, enum_class: Any, search_term: str) -> List:
        """
        Find enum values with labels matching the search term

        Args:
            enum_class: The enum class to search in
            search_term: Term to search for in labels

        Returns:
            List: List of matching enum values
        """
        matching_values = []
        search_term_lower = search_term.lower()

        # Try different enum interfaces
        if hasattr(enum_class, 'as_tuples'):
            for enum_value, enum_label in enum_class.as_tuples():
                if search_term_lower in str(enum_label).lower():
                    matching_values.append(enum_value)
        elif hasattr(enum_class, 'choices'):
            for choice in enum_class.choices:
                if isinstance(choice, tuple) and len(choice) >= 2:
                    if search_term_lower in str(choice[1]).lower():
                        matching_values.append(choice[0])

        return matching_values


class RangeFilterStrategy(FilterStrategy):
    """Base strategy for building range filters"""

    def __init__(self, value_extractor: RequestValueExtractor, parse_func: Callable):
        """
        Initialize the strategy

        Args:
            value_extractor: Helper for extracting values from request
            parse_func: Function to parse the min/max values
        """
        self.value_extractor = value_extractor
        self.parse_func = parse_func

    def build_query(self, field_info: Dict, **kwargs) -> Optional[Q]:
        """
        Build a Q object for a range filter

        Args:
            field_info: Dictionary containing field metadata

        Returns:
            Optional[Q]: A Django Q object for range filtering, or None if no range values
        """
        if not field_info.get("filterable", True):
            return None

        field_path = field_info['field_path']
        min_param = f"{field_path}_min"
        max_param = f"{field_path}_max"

        q_obj = None

        # Get min value if present
        min_value = self._parse_bound_value(min_param)
        if min_value is not None:
            q_obj = Q(**{f"{field_path}__gte": min_value})

        # Get max value if present
        max_value = self._parse_bound_value(max_param)
        if max_value is not None:
            max_q = Q(**{f"{field_path}__lte": max_value})
            q_obj = max_q if q_obj is None else q_obj & max_q

        return q_obj

    def _parse_bound_value(self, param: str) -> Any:
        """
        Parse a boundary value using the provided parse function

        Args:
            param: The parameter name to extract and parse

        Returns:
            Any: The parsed value or None
        """
        value_str = self.value_extractor.get_value(param)
        if not value_str:
            return None

        return self.parse_func(value_str)


class DateRangeFilterStrategy(RangeFilterStrategy):
    """Strategy for building date range filters"""

    def __init__(self, value_extractor: RequestValueExtractor):
        """Initialize with date parsing function"""
        super().__init__(value_extractor, DateParser.parse_date)


class DateTimeRangeFilterStrategy(RangeFilterStrategy):
    """Strategy for building datetime range filters"""

    def __init__(self, value_extractor: RequestValueExtractor):
        """Initialize with datetime parsing function"""
        super().__init__(value_extractor, DateParser.parse_datetime)


class AdvancedFilterStrategy(FilterStrategy):
    """Strategy for building advanced filters from JSON configuration"""

    def __init__(self, value_extractor: RequestValueExtractor, field_registry: Dict[str, Dict], logger=None):
        """
        Initialize the strategy

        Args:
            value_extractor: Helper for extracting values from request
            field_registry: Dictionary of field information
            logger: Optional logger instance
        """
        self.value_extractor = value_extractor
        self.field_registry = field_registry
        self.logger = logger or logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.basic_filter_strategy = BaseFieldFilterStrategy(value_extractor, logger)

    def build_query(self, **kwargs) -> Optional[Q]:
        """
        Parse and build Q object from advanced filter parameter

        Returns:
            Optional[Q]: A Django Q object for advanced filtering, or None
        """
        filter_config = self._get_filter_config()
        if not filter_config:
            return None

        # Build filter Q object
        return self._build_filter_object(filter_config)

    def _get_filter_config(self) -> Optional[Dict]:
        """
        Extract and parse the filter configuration

        Returns:
            Optional[Dict]: The parsed filter configuration or None
        """
        filter_param = self.value_extractor.get_value(ADVANCED_FILTER_PARAM)
        if not filter_param:
            return None

        try:
            # URL decode the parameter if it's a string
            if isinstance(filter_param, str):
                decoded_param = parse.unquote(filter_param)
                return json.loads(decoded_param)

            # If somehow it's already a dict/object
            return filter_param

        except (json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"Error parsing advanced filter: {e}")
            return None

    def _build_filter_object(self, config: Dict) -> Optional[Q]:
        """
        Recursively build a Q object from the filter configuration

        Args:
            config: The filter configuration dictionary

        Returns:
            Optional[Q]: A Django Q object for filtering, or None
        """
        # If this is a group condition with an operator
        if 'operator' in config and 'conditions' in config:
            return self._build_group_condition(config)

        # If this is a leaf condition
        elif 'field' in config and 'value' in config:
            return self._build_leaf_condition(config)

        else:
            self.logger.warning("Invalid filter condition format")
            return None

    def _build_group_condition(self, config: Dict) -> Optional[Q]:
        """
        Build a Q object for a group condition (AND/OR)

        Args:
            config: The group condition configuration

        Returns:
            Optional[Q]: A Django Q object for the group, or None
        """
        operator = config['operator'].upper()
        conditions = config['conditions']

        if not conditions:
            return None

        # Start with the first condition
        q_object = self._build_filter_object(conditions[0])
        if q_object is None:
            return None

        # Apply the operator to combine conditions
        for condition in conditions[1:]:
            next_q = self._build_filter_object(condition)
            if next_q is not None:
                q_object = self._combine_q_objects(q_object, next_q, operator)

        return q_object

    def _combine_q_objects(self, q1: Q, q2: Q, operator: str) -> Q:
        """
        Combine two Q objects based on the operator

        Args:
            q1: First Q object
            q2: Second Q object
            operator: The operator to use ('AND' or 'OR')

        Returns:
            Q: The combined Q object
        """
        if operator == 'AND':
            return q1 & q2
        elif operator == 'OR':
            return q1 | q2
        else:
            self.logger.warning(f"Unsupported operator: {operator}, using AND")
            return q1 & q2

    def _build_leaf_condition(self, config: Dict) -> Optional[Q]:
        """
        Build a Q object for a leaf condition (field comparison)

        Args:
            config: The leaf condition configuration

        Returns:
            Optional[Q]: A Django Q object for the condition, or None
        """
        field = config['field']
        lookup = config.get('lookup')  # Lookup is optional
        value = config['value']

        # Validate field exists in model
        if field not in self.field_registry:
            self.logger.warning(f"Unknown field: {field}")
            return None

        # Build field filter
        field_info = self.field_registry[field]
        return self.basic_filter_strategy.build_query(field_info, value, lookup)