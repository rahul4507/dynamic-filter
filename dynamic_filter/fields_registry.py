import inspect
from typing import Dict, List, Type, Optional, Set, Any

from django.db.models import (
    DateField, DateTimeField, Field, Model, JSONField,
    Sum, Count, Avg, Min, Max, F, Expression, QuerySet
)
from django.db.models.constants import LOOKUP_SEP
from django.db.models.functions import Concat


class FieldTypeRegistry:
    """Registry of field types and their default lookup expressions"""

    @classmethod
    def get_field_type(cls, field: Field) -> str:
        """Determine the simplified type of Django field"""
        if cls._is_choice_field(field):
            return 'enum'

        if isinstance(field, DateField) and not isinstance(field, DateTimeField):
            return 'date'

        if isinstance(field, DateTimeField):
            return 'datetime'

        if isinstance(field, JSONField):
            return 'json'

        if hasattr(field, 'get_internal_type'):
            django_type = field.get_internal_type()
            from .constants import DJANGO_TYPE_MAPPING
            return DJANGO_TYPE_MAPPING.get(django_type, 'text')

        return 'text'  # Default to text for unknown types

    @classmethod
    def _is_choice_field(cls, field: Field) -> bool:
        """Check if a field is a choice/enum field"""
        # Check for BaseChoice-derived fields
        if hasattr(field, '_choices_cls'):
            return True

        # Check class hierarchy
        class_hierarchy = inspect.getmro(field.__class__)
        for base_cls in class_hierarchy:
            if 'BaseChoiceField' in base_cls.__name__ or 'ChoiceField' in base_cls.__name__:
                return True

        # Check if field has conventional choices
        return hasattr(field, 'choices') and bool(field.choices)

    @classmethod
    def get_default_lookup(cls, field_type: str) -> str:
        """Get the default lookup expression for a field type"""
        from .constants import DEFAULT_LOOKUPS
        return DEFAULT_LOOKUPS.get(field_type, 'exact')

    @classmethod
    def get_lookups_for_type(cls, field_type: str) -> List[str]:
        """Get the available lookup expressions for a field type"""
        from .constants import DEFAULT_LOOKUPS_BY_TYPE
        return DEFAULT_LOOKUPS_BY_TYPE.get(field_type, ['exact'])


class FieldRegistry:
    """Registry for model fields with filter metadata"""

    def __init__(self, model: Type[Model], queryset: Optional[QuerySet] = None, config: Optional[Dict] = None):
        self.model = model
        self.queryset = queryset
        self.config = config or {}
        self.fields: Dict[str, Dict[str, Any]] = {}

        # Initialize allowed fields sets once
        self.allowed_filter_fields = self._get_allowed_fields('filter_fields')
        self.allowed_search_fields = self._get_allowed_fields('search_fields')

        # Analyze fields
        self._analyze_model_fields()
        if queryset is not None:
            self._analyze_annotated_fields()

    def _get_allowed_fields(self, config_key: str) -> Set[str]:
        """Get allowed fields from config as a set for efficient lookups"""
        fields = self.config.get(config_key, [])
        return set(fields) if fields else set()

    def _analyze_model_fields(self) -> None:
        """
        Analyze model fields to determine their types and filter properties,
        including fields from related models
        """
        related_fields = []
        # Register fields from the model itself
        for field in self.model._meta.get_fields():
            # Skip auto-created reverse relations we don't need
            if field.auto_created and not field.concrete:
                continue

            # Register the field itself
            self._register_field(field)

            # Process fields from related models (one level deep)
            if field.is_relation and hasattr(field, 'related_model'):
                related_fields.append(field)

        for relation_field in related_fields:
            # Register fields from related models
            self._register_related_fields(relation_field)

    def _register_related_fields(self, relation_field: Field) -> None:
        """Register fields from a related model"""
        related_model = relation_field.related_model
        relation_name = relation_field.name

        for rel_field in related_model._meta.get_fields():
            if hasattr(rel_field, 'get_internal_type'):
                # Skip auto-created reverse relations
                if rel_field.auto_created and not rel_field.concrete:
                    continue
                self._register_field(rel_field, relation_name)

    def _analyze_annotated_fields(self) -> None:
        """Register fields that are annotated in the queryset"""
        if not hasattr(self.queryset, 'query') or not hasattr(self.queryset.query, 'annotations'):
            return

        for field_name, expression in self.queryset.query.annotations.items():
            # Skip if already registered
            if field_name in self.fields:
                continue

            field_type = self._determine_annotation_type(expression)
            if field_type:
                self._register_annotated_field(field_name, field_type)

    def _determine_annotation_type(self, expression: Expression) -> str:
        """
        Determine the type of annotated field based on its expression
        Returns the field type as a string
        """
        # Handle common annotation types
        if isinstance(expression, Concat):
            return 'text'
        elif isinstance(expression, (Sum, Avg)):
            return 'decimal'
        elif isinstance(expression, Count):
            return 'integer'
        elif isinstance(expression, (Min, Max)):
            # Try to determine the type based on the source field
            if hasattr(expression, 'source_expressions') and expression.source_expressions:
                source = expression.source_expressions[0]
                if isinstance(source, F):
                    field_name = source.name
                    try:
                        field = self.model._meta.get_field(field_name)
                        return FieldTypeRegistry.get_field_type(field)
                    except:
                        pass
            # Default for Min/Max if we can't determine source type
            return 'text'

        # Default to text if we can't determine the type
        return 'text'

    def _register_annotated_field(self, field_name: str, field_type: str) -> None:
        """Register an annotated field for filtering"""
        # Get lookups based on field type
        lookups = FieldTypeRegistry.get_lookups_for_type(field_type)
        default_lookup = FieldTypeRegistry.get_default_lookup(field_type)

        # Determine if field is filterable and searchable
        filterable = not self.allowed_filter_fields or field_name in self.allowed_filter_fields
        searchable = not self.allowed_search_fields or field_name in self.allowed_search_fields

        # Build field metadata
        self.fields[field_name] = {
            'field_path': field_name,  # Annotated fields use their name directly
            'field': None,  # No actual field object for annotated fields
            'type': field_type,
            'searchable': searchable,
            'filterable': filterable,
            'lookups': lookups,
            'default_lookup': default_lookup,
            'is_annotated': True,
            'range_filter': field_type in ('date', 'datetime', 'integer', 'decimal'),
            'enum_class': None,
        }

    def _register_field(self, field: Field, relation_prefix: Optional[str] = None) -> None:
        """Register a field in the field registry"""
        field_name = field.name
        field_path = field_name

        # Handle relation paths
        if relation_prefix:
            field_path = f"{relation_prefix}{LOOKUP_SEP}{field_name}"
            # Avoid field name conflicts by prefixing related fields
            if field_name in self.fields:
                field_name = f"{relation_prefix}_{field_name}"

        # Skip if already registered
        if field_name in self.fields:
            return

        # Get field type and configuration
        field_type = FieldTypeRegistry.get_field_type(field)
        field_config = getattr(field, 'filter_config', {})

        # Determine if field is searchable and filterable
        base_searchable = field_config.get('searchable', False)
        searchable = field_name in self.allowed_search_fields if self.allowed_search_fields else base_searchable
        filterable = field_name in self.allowed_filter_fields if self.allowed_filter_fields else True

        # Get lookups and default lookup
        lookups = field_config.get('lookups', FieldTypeRegistry.get_lookups_for_type(field_type))
        default_lookup = field_config.get('default', FieldTypeRegistry.get_default_lookup(field_type))

        # Check if field supports range filtering
        range_filter = field_config.get(
            'range_filter',
            field_type in ('date', 'datetime', 'integer', 'decimal')
        )

        # Build and store field metadata
        self.fields[field_name] = {
            'field_path': field_path,
            'field': field,
            'type': field_type,
            'searchable': searchable,
            'filterable': filterable,
            'lookups': lookups,
            'default_lookup': default_lookup,
            'range_filter': range_filter,
            'enum_class': self._get_enum_class(field) if field_type == 'enum' else None,
            'is_annotated': False,
        }

    def _get_enum_class(self, field: Field) -> Optional[Type]:
        """Extract the enum class from a choice field"""
        # Check for direct choices class reference
        if hasattr(field, '_choices_cls'):
            return field._choices_cls

        # Try to extract from conventional choices
        if hasattr(field, 'choices') and field.choices:
            try:
                # Get the first choice to determine the class
                first_choice = field.choices[0]
                if isinstance(first_choice, tuple) and first_choice:
                    choice_value = first_choice[0]
                    if hasattr(choice_value, '__class__'):
                        return choice_value.__class__
            except (IndexError, AttributeError):
                pass

        return None

    def get_field_info(self, field_name: str) -> Optional[Dict]:
        """Get field information by name"""
        return self.fields.get(field_name)

    def get_searchable_fields(self) -> Dict[str, Dict]:
        """Get all searchable fields"""
        return {
            name: info for name, info in self.fields.items()
            if info.get('searchable')
        }

    def get_filterable_fields(self) -> Dict[str, Dict]:
        """
        Get information about all filterable fields for API documentation
        or frontend configuration.

        Returns:
            Dictionary of field names mapped to their metadata
        """
        result = {}

        for field_name, field_info in self.fields.items():
            # Skip internal fields and non-filterable fields
            if field_name.startswith('_') or not field_info.get('filterable', True):
                continue

            # Create metadata dict
            field_meta = self._create_field_metadata(field_name, field_info)
            result[field_name] = field_meta

        return result

    def _create_field_metadata(self, field_name: str, field_info: Dict) -> Dict:
        """Create metadata dictionary for a field"""
        field_type = field_info['type']

        field_meta = {
            'name': field_name,
            'type': field_type,
            'filterable': True,
            'searchable': field_info['searchable'],
            'orderable': True,
            'lookups': field_info['lookups'],
            'default_lookup': field_info['default_lookup'],
        }

        # Add range filter flag if applicable
        if field_info['range_filter']:
            field_meta['range_filter'] = True

        # Add enum choices if available
        if field_type == 'enum' and field_info['enum_class']:
            field_meta['choices'] = self._get_enum_choices(field_info['enum_class'])

        return field_meta

    def _get_enum_choices(self, enum_class: Type) -> List[Dict[str, str]]:
        """Get choices from an enum class in a standardized format"""
        choices = []

        if hasattr(enum_class, 'as_tuples'):
            choices = [{'value': str(v), 'label': str(l)} for v, l in enum_class.as_tuples()]
        elif hasattr(enum_class, 'choices'):
            choices = [{'value': str(v), 'label': str(l)} for v, l in enum_class.choices]

        return choices
