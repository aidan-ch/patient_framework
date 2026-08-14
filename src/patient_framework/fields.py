import datetime
from types import UnionType
from typing import Callable, Type, get_args, TypeVar, Any, Generic, TypeAlias
from functools import partial

from .data_helpers import _coerce_str, _coerce_bool, _coerce_int, \
    _coerce_float, _coerce_none, _coerce_date

# allow no wildcard imports
__all__ = []



permitted_types :TypeAlias= str | int | float | bool | datetime.datetime | None
"""The only data types that are allowed to be declared for a field, and that
   can be returned by self.transform.
   This is because I want to avoid the possibility of the datasets storing collections
   or other complex objects inside as that may break much of the logic of this program.
   They will have their own default parsers and will have their own
   defined conversions to strings if the Dataset is saved as a csv.
   So there will never be a value in a dataset that is not one of these types.
   """


def _is_permitted_type(t: Type) -> bool:
    return t in get_args(permitted_types)


Field_T = TypeVar('Field_T', bound=permitted_types)


class _Field(Generic[Field_T]):
    """self._name, self._type are read only.

    Transformation is only really during Data ingestion.
    When doing "add row" or whatever to an existing dataset object, you can just
    apply the transformation yourself.
    """

    _DEFAULT_PARSERS : dict[Type,Callable[[Any],permitted_types]] = {
        str: _coerce_str,
        bool: _coerce_bool,
        int: _coerce_int,
        float: _coerce_float,
        type(None): _coerce_none
    }

    def __init__(self, name: str,
                 data_type: type[Field_T],
                 translation: str | None = None,
                 transformation: Callable[[object], Field_T] | None = None,
                 date_format: str | None = None):
        """:param transformation: transformation will be applied while loading data into dataset.
            If None is passed, then will use the built-in parser (in parsers.py).
            By default, all methods that load data anywhere in this package will transform
            the data using this transformation Callable. These methods will take a
            boolean specifying whether or not you wish to apply the transformation,
            which will default to True (e.g. schema._Patient.set)
        :param data_type: Data type that the values of this field should be upon import
            AND after parsing.
        :param date_format: Only need to specify if data_type == datetime.datetime.
        If data_type is not datetime.datetime, self.date_format will be set to None
        regardless of what is passed to initializer for it.
        """

        if not _is_permitted_type(data_type):
            raise TypeError(f"Type argument must be one of {permitted_types}")
        self._type = data_type
        """Must be one of permitted_types"""

        if not isinstance(name,str):
            raise TypeError("_Field name must be a string")
        self._name = name

        self._translation = translation
        if not isinstance(self.translation, str) and not isinstance(
                self.translation, type(None)):
            raise TypeError(
                f"Translation must be a string or None, cannot be of type {type(self.translation)}")

        if isinstance(self.translation,
                      str) and self.translation.strip() == "":
            raise ValueError(
                "Translation name cannot be empty. If no translation, must be set to None")

        if not callable(transformation) and not transformation is None:
            raise TypeError("transformation argument must be type Callable, or None")

        self._transformation=transformation

        if self.type == datetime.datetime:
            self._date_format = date_format
            default_date_parser = self._config_date_field()

            # adding this in regardless of whether or not transform is None (in which case this default would be used) or if it was specified
            # as choosing between specified transformation and default transformation is determined by the self.transform getter
            self._DEFAULT_PARSERS = dict(_Field._DEFAULT_PARSERS)
            self._DEFAULT_PARSERS.update({datetime.datetime:default_date_parser})
        else:
            # ensure all date related information is isolated to date related fields, ignoring date_format parameter if data_type parameter is not datetime.datetime
            self._date_format = None


    def parse(self, value: Any) -> Field_T | None:
        """Transform the value according to the field's callable, and validate
        that the returned value from the call matches the type stored inside self._type.

        If value is None, will return None since None represents no data. No configuration
        will transform no data into data."""

        if value is None:
            return None

        transformed_value = self.transform(value)

        if not self.is_matching_type(transformed_value):
            raise TypeError(
                f"Parsed value {transformed_value} is of type {type(transformed_value)},"
                f"but should same as specified type: {self.type}.")
        return transformed_value

    def serialize(self, value: Field_T) -> str:
        if not self.is_matching_type(value):
            raise RuntimeError(
                "Value does not match the data type of this field")

        match self.type:
            case str():
                return value
            case bool():
                if value:
                    return "true"
                else:
                    return "false"
            case int() | float():
                return str(value)
            case datetime.datetime():
                return value.strftime(self.date_format)
            case None:
                return ""
            case _:
                # fallthrough for any other case that may somehow occur
                return str(value)

    def equals(self, other: object) -> bool:
        """Not overriding __eq__ because want to keep _Field hashable, but also
            want to be able to have equals() check on the basis of many attributes,
            not necessarily just instance equality.
            Comparison on the basis of all attributes, except transformation and
            date_format.
            Ignoring transformation as it is intended to allow changing the format
            of the values, not what the values represent.
            Ignoring date_format as format of dates does not change the date itself.
            Names do not have to match if the translation of one matches the name
            of the other, or their names are different but their translations are the same"""

        if not isinstance(other, _Field):
            return NotImplemented

        if self.type != other.type:
            return False

        if self.name != other.name:
            if self.name == other.translation:
                return True
            elif self.translation == other.name:
                return True
            elif self.translation == other.translation:
                return True
            else:
                return False

        return True

    def _config_date_field(self) -> Callable[[Any],datetime.datetime]:
        """ Sets self._transform for date type fields.
        General validation checks:
            Ensures self._date_format is set if the data type is datetime.date.
            Checks that the formatting string is a valid formatting string.

        :return: Default parser for a date Field with this string format
        """
        if self.type is not datetime.datetime:
            raise RuntimeError(
                f"Cannot be called from _Field instance that is not a {datetime.date} instance")

        # Use partial for the datetime.date fields as need to pre-enter date_format such that can call transform(value) rather than transform(value, date_format)
        if self.date_format is None:
            raise RuntimeError("date_format cannot be set to none if data type"
                               f"is set to {datetime.datetime}")

        # ensure date format is good
        try:
            datetime.datetime.now().strftime(self.date_format)
        except ValueError as e:
            raise ValueError(f"Format string is invalid: {e}")

        return partial(_coerce_date,format_str=self.date_format)

    # name is read only
    @property
    def name(self) -> str:
        return self._name

    @property
    def translation(self):
        """Purpose of translation is so that when you're comparing values for
        fields from two different datasets (A and B), if field or translation
        from A match the field or translation from field B, they're the same field
        so their values can be compared directly.

        No two field names in a dataset can be identical.
        No two translations in a dataset can be identical.
        No translation can be the same as a field for which it is not the translation.
        """

        return self._translation


    @property
    def transform(self) -> Callable[[Any], Any]:
        if self._transformation is not None:
            return self._transformation
        else:
            return self._DEFAULT_PARSERS[self.type]

    @property
    def type(self) -> type[Field_T]:
        return self._type

    @property
    def date_format(self) -> str:
        if self._date_format is None:
            raise AttributeError("Field is not a date field - has no date_format attribute")

        return self._date_format

    def is_matching_type(self, value: Any) -> bool:
        """Return true if this value is compatible with the type of this _Field"""
        return isinstance(value, self.type)

    def copy(self) -> '_Field'[Field_T]:
        return _Field(name=self.name,
                      data_type=self.type,
                      translation=self.translation,
                      transformation=self.transform,
                      date_format=self.date_format)
