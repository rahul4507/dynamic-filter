# Define Default Prams for Filtering and Ordering
SEARCH_PARAM = 'search'
ORDERING_PARAM = 'ordering'
DEFAULT_ORDERING = '-last_modified_date'
ADVANCED_FILTER_PARAM = 'filter'
SKIP_PARAMS = {'page', 'page_size', SEARCH_PARAM, ADVANCED_FILTER_PARAM, ORDERING_PARAM}

# Field Registry Constants
# Default lookup mappings for field types
DEFAULT_LOOKUPS = {
    'text': 'icontains',
    'integer': 'exact',
    'decimal': 'exact',
    'boolean': 'exact',
    'date': 'exact',
    'datetime': 'exact',
    'enum': 'exact',
    'relation': 'exact',
    'array': 'contains',
    'json': 'has_key',
}

# Mapping of Django internal types to our simplified types
DJANGO_TYPE_MAPPING = {
    'CharField': 'text',
    'TextField': 'text',
    'SlugField': 'text',
    'EmailField': 'text',
    'URLField': 'text',
    'FileField': 'text',
    'FilePathField': 'text',
    'IntegerField': 'integer',
    'PositiveIntegerField': 'integer',
    'SmallIntegerField': 'integer',
    'BigIntegerField': 'integer',
    'AutoField': 'integer',
    'BigAutoField': 'integer',
    'FloatField': 'decimal',
    'DecimalField': 'decimal',
    'BooleanField': 'boolean',
    'NullBooleanField': 'boolean',
    'DateField': 'date',
    'DateTimeField': 'datetime',
    'TimeField': 'text',
    'ForeignKey': 'relation',
    'OneToOneField': 'relation',
    'ManyToManyField': 'relation',
    'JSONField': 'json',
    'ArrayField': 'array',
}

# Default searchable field types
SEARCHABLE_TYPES = {'text', 'enum'}

# Default lookup expressions by field type
DEFAULT_LOOKUPS_BY_TYPE = {
    'text': ['exact', 'iexact', 'contains', 'icontains', 'startswith', 'istartswith'],
    'integer': ['exact', 'gt', 'gte', 'lt', 'lte', 'in', 'range'],
    'decimal': ['exact', 'gt', 'gte', 'lt', 'lte', 'range'],
    'boolean': ['exact'],
    'date': ['exact', 'gt', 'gte', 'lt', 'lte', 'range'],
    'datetime': ['exact', 'gt', 'gte', 'lt', 'lte', 'range', 'date'],
    'enum': ['exact', 'in'],
    'relation': ['exact', 'in'],
    'json': ['has_key', 'contains', 'contained_by'],
    'array': ['contains', 'contained_by', 'overlap', 'len']
}

# Lookup types that expect multiple values
MULTI_VALUE_LOOKUPS = ['in', 'range']

# Date parser formats
# Common date formats
DATE_FORMATS = [
    '%Y-%m-%d',  # ISO format: 2023-01-31
    '%d-%m-%Y',  # European: 31-01-2023
    '%m/%d/%Y',  # US: 01/31/2023
    '%d/%m/%Y',  # UK: 31/01/2023
    '%Y/%m/%d',  # Alternative ISO: 2023/01/31
    '%b %d, %Y',  # Jan 31, 2023
    '%d %b %Y',  # 31 Jan 2023
    '%B %d, %Y',  # January 31, 2023
    '%d %B %Y'  # 31 January 2023
]

# Common datetime formats
DATETIME_FORMATS = [
    '%Y-%m-%d %H:%M:%S',  # ISO format with space: 2023-01-31 14:30:00
    '%Y-%m-%dT%H:%M:%S',  # ISO format with T: 2023-01-31T14:30:00
    '%Y-%m-%dT%H:%M:%SZ',  # ISO format with Z: 2023-01-31T14:30:00Z
    '%Y-%m-%dT%H:%M:%S.%f',  # ISO with microseconds: 2023-01-31T14:30:00.123456
    '%Y-%m-%dT%H:%M:%S.%fZ',  # ISO with microseconds and Z: 2023-01-31T14:30:00.123456Z
    '%Y-%m-%d %H:%M',  # Short format: 2023-01-31 14:30
    '%d-%m-%Y %H:%M:%S',  # European with time: 31-01-2023 14:30:00
    '%m/%d/%Y %H:%M:%S',  # US with time: 01/31/2023 14:30:00
    '%d/%m/%Y %H:%M:%S',  # UK with time: 31/01/2023 14:30:00
    '%b %d, %Y %H:%M:%S',  # Jan 31, 2023 14:30:00
    '%d %b %Y %H:%M:%S'  # 31 Jan 2023 14:30:00
]