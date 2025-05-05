import logging
import json
from urllib import parse
from typing import Dict, Type, Optional, List, Set

from django.db.models import Q, Model

from .constants import SEARCH_PARAM, ORDERING_PARAM, ADVANCED_FILTER_PARAM, SKIP_PARAMS
from fields_registry import FieldRegistry
from filter_strategy import BaseFieldFilterStrategy, SearchFilterStrategy, \
    DateRangeFilterStrategy, DateTimeRangeFilterStrategy, AdvancedFilterStrategy
from .utils import RequestValueExtractor, OrderingBuilder


class ModelFilter:
    """
    A flexible filter class that uses Django's ORM to apply filters and ordering
    based on request parameters with Meta class configuration.

    This class follows SOLID principles by delegating specific responsibilities
    to specialized components.
    """

    def __init__(
            self,
            model: Type[Model],
            request_data: Dict = None,
            queryset=None,
            config: Dict = None
    ):
        """
        Initialize the filter with a model, request data, and optional queryset.

        Args:
            model: The Django model class to filter
            request_data: Dict-like object containing filter parameters (e.g. request.GET)
            queryset: Optional pre-filtered queryset. If None, model.objects.all() will be used
            config: Optional filter configuration to override model-defined config
        """
        # Defensive programming - ensure inputs are valid
        self.model = model if model else None
        if not self.model:
            raise ValueError("Model must be provided")

        self.request_data = request_data or {}
        self.base_queryset = queryset if queryset is not None else model.objects.all()
        self.filtered_queryset = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.config = config or {}

        # Initialize components (SRP - separate responsibilities)
        self._initialize_components()

    def _initialize_components(self) -> None:
        """
        Initialize all component objects used by this filter.
        Extracted to separate method for better organization and potential override.
        """
        # Initialize field registry
        self.field_registry = FieldRegistry(self.model, self.base_queryset, self.config)

        # Initialize value extractor
        self.value_extractor = RequestValueExtractor(self.request_data)

        # Initialize ordering builder
        self.ordering_builder = OrderingBuilder(self.value_extractor, self.field_registry.fields)

        # Initialize filter strategies (Strategy Pattern)
        self._init_filter_strategies()

    def _init_filter_strategies(self) -> None:
        """
        Initialize filter strategies with proper dependencies.
        Extracted to separate method to support customization in subclasses.
        """
        self.strategies = {
            'basic': BaseFieldFilterStrategy(self.value_extractor, self.logger),
            'search': SearchFilterStrategy(self.value_extractor),
            'date_range': DateRangeFilterStrategy(self.value_extractor),
            'datetime_range': DateTimeRangeFilterStrategy(self.value_extractor),
            'advanced': AdvancedFilterStrategy(
                self.value_extractor, self.field_registry.fields, self.logger
            )
        }

    def apply(self) -> 'ModelFilter':
        """
        Apply all filters and ordering to the queryset.
        Returns self for method chaining.
        """
        # Return early if already filtered (optimization)
        if self.filtered_queryset is not None:
            return self

        # Build the filter query
        query = self._build_filter_query()

        # Apply filters to queryset
        queryset = self.base_queryset.filter(query)

        # Apply ordering
        ordering = self._apply_ordering(queryset)
        if ordering:
            queryset = queryset.order_by(*ordering)

        # Store the result
        self.filtered_queryset = queryset
        return self

    def _build_filter_query(self) -> Q:
        """
        Build the Django Q object for filtering.
        Extracted to separate method for better organization and potential override.
        """
        query = Q()

        # Try advanced filter first
        advanced_q = self._apply_advanced_filter()
        if advanced_q:
            query &= advanced_q
            return query

        # If no advanced filter, apply search and basic filters
        query &= self._apply_search_filter()
        query &= self._apply_basic_filters()

        return query

    def _apply_advanced_filter(self) -> Optional[Q]:
        """
        Apply advanced filter if present.
        Returns the Q object or None if no advanced filter found.
        """
        advanced_q = self.strategies['advanced'].build_query()
        return advanced_q

    def _apply_search_filter(self) -> Q:
        """
        Apply search filter if present.
        Returns Q object (empty if no search filter found).
        """
        search_q = self.strategies['search'].build_query(self.field_registry.fields)
        return search_q if search_q else Q()

    def _apply_basic_filters(self) -> Q:
        """
        Apply all basic field filters based on request parameters.
        Returns a Q object combining all field filters.
        """
        query = Q()
        processed_fields = set()

        for param in self.request_data:
            # Skip already processed or special parameters
            if param in processed_fields or param in SKIP_PARAMS:
                continue

            field_q = self._process_single_param(param, processed_fields)
            if field_q:
                query &= field_q

        return query

    def _process_single_param(self, param: str, processed_fields: Set[str]) -> Optional[Q]:
        """
        Process a single request parameter and build a Q object if it's valid.

        Args:
            param: The parameter name to process
            processed_fields: Set to track processed fields

        Returns:
            Q object or None if parameter not valid for filtering
        """
        # Direct field match
        if param in self.field_registry.fields:
            field_info = self.field_registry.fields[param]
            field_q = self.strategies['basic'].build_query(field_info)
            if field_q:
                processed_fields.add(param)
                return field_q

        # Handle field__lookup format
        elif '__' in param:
            return self._process_lookup_param(param, processed_fields)

        return None

    def _process_lookup_param(self, param: str, processed_fields: Set[str]) -> Optional[Q]:
        """
        Process parameters in field__lookup format.

        Args:
            param: Parameter in field__lookup format
            processed_fields: Set to track processed fields

        Returns:
            Q object or None if parameter not valid
        """
        field_name, lookup = param.split('__', 1)

        # Skip if field not registered
        if field_name not in self.field_registry.fields:
            return None

        field_info = self.field_registry.fields[field_name]

        # Validate lookup is allowed for this field
        if lookup not in field_info.get('lookups', []):
            self.logger.warning(
                f"Lookup '{lookup}' not allowed for field '{field_name}'. "
                f"Using default: {field_info.get('default_lookup', 'exact')}"
            )
            return None

        # Get value safely
        value = self.request_data.get(param)
        if value is None:
            return None

        # Build query with custom lookup
        field_q = self.strategies['basic'].build_query(
            field_info=field_info,
            value=value,
            lookup=lookup
        )

        if field_q:
            processed_fields.add(param)
            return field_q

        return None

    def _apply_ordering(self, queryset) -> List[str]:
        """
        Apply ordering to the queryset.

        Args:
            queryset: The queryset to order

        Returns:
            List of ordering fields
        """
        return self.ordering_builder.build_ordering()

    @property
    def qs(self):
        """
        Return the filtered and ordered queryset.
        Applies filters if not already applied.
        """
        if self.filtered_queryset is None:
            self.apply()

        # Log the query for debugging
        try:
            self.logger.info("Filtered Q object: %s", self.filtered_queryset.query.where)
        except Exception as e:
            self.logger.warning(f"Could not log filtered query object: {e}")

        return self.filtered_queryset

    def get_filterable_fields(self) -> Dict[str, Dict]:
        """
        Get information about all filterable fields.
        Delegates to field registry for information.
        """
        return self.field_registry.get_filterable_fields()

    def get_filter_params(self) -> Dict:
        """
        Get the current filter parameters in a format suitable for saving.

        Returns:
            Dictionary of filter parameters
        """
        params = {}

        # Include only real filter parameters (exclude pagination, etc.)
        for param, value in self.request_data.items():
            if param not in SKIP_PARAMS or param == SEARCH_PARAM:
                params[param] = value

        # Include advanced filter if present
        if ADVANCED_FILTER_PARAM in self.request_data:
            try:
                decoded = parse.unquote(self.request_data[ADVANCED_FILTER_PARAM])
                params['_advanced_filter'] = json.loads(decoded)
            except (json.JSONDecodeError, ValueError) as e:
                self.logger.warning(f"Failed to parse advanced filter: {e}")

        # Include ordering if present
        if ORDERING_PARAM in self.request_data:
            params['_ordering'] = self.request_data[ORDERING_PARAM]

        return params

    def to_url_params(self) -> str:
        """
        Convert current filter parameters to URL query string.

        Returns:
            URL query string
        """
        params = []

        for key, value in self.request_data.items():
            if value:  # Skip empty values
                try:
                    params.append(f"{key}={parse.quote(str(value))}")
                except Exception as e:
                    self.logger.warning(f"Failed to encode URL parameter {key}: {e}")

        return '&'.join(params)
