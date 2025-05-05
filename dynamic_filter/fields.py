class FilterableFieldMixin:
    """
    Mixin that adds filter configuration capabilities to Django model fields.

    This mixin should be applied first in the inheritance chain to ensure
    its __init__ method is called after all other mixins have processed their
    kwargs.
    """

    def __init__(self, *args, **kwargs):
        # Extract filter configuration
        self.filter_config = kwargs.pop('filter_config', {})

        # Call parent constructor
        super().__init__(*args, **kwargs)
