import datetime
from typing import Callable, Type, get_args
from functools import partial

from .data_helpers import _coerce_str, _coerce_bool, _coerce_int, _coerce_float, _coerce_none, _coerce_date

_DEFAULT_PARSERS = {
    str : _coerce_str,
    bool : _coerce_bool,
    int : _coerce_int,
    float: _coerce_float,
    datetime.datetime : _coerce_date,
    type(None): _coerce_none
}


permitted_types = str | int | float | bool | datetime.datetime | None
"""The only data types that are allowed to be declared for a field, and that
   can be returned by self.transform.
   This is because I want to avoid the possibility of the datasets storing collections
   or other complex objects inside as that may break much of the logic of this program.
   They will have their own default parsers and will have their own
   defined conversions to strings if the Dataset is saved as a csv.
   So there will never be a value in a dataset that is not one of these types.
   """

def _is_permitted_type(t : Type) -> bool:
    return t in get_args(permitted_types)


class Field:
    """self._name, self._type are read only"""

    def __init__(self, name: str,
                 data_type: Type,
                 translation: str | None = None,
                 transformation: Callable = None,
                 date_format:str = None):
        """:param transformation: transformation will be applied while loading data into dataset.
            If None is passed, then will use the built-in parser (in parsers.py).
            By default, all methods that load data anywhere in this package will transform
            the data using this transformation Callable. These methods will take a
            boolean specifying whether or not you wish to apply the transformation,
            which will default to True (e.g. schema.Patient.set)
        :param data_type: Data type that the values of this field should be upon import
            AND after parsing.
        :param date_format: Only need to specify if data_type == datetime.datetime"""



        self._type = data_type
        """Must be one of permitted_types"""
        if not _is_permitted_type(self.type):
            raise TypeError(f"Type argument must be one of {permitted_types}")

        self._name = name

        self._translation = translation
        if not isinstance(self.translation,str) and not isinstance(self.translation,type(None)):
            raise TypeError(f"Translation must be a string or None, cannot be of type {type(self.translation)}")

        if isinstance(self.translation,str) and self.translation.strip() == "":
            raise ValueError(
                "Translation name cannot be empty. If no translation, must be set to None")

        self._date_format = date_format


        if transformation is not None:
            self._transform = transformation
            """Callable that will transform the values of this field in the dataset by calling transform(value).
            Must return data of type stated in permitted_types"""

        # assign default parsers
        else:
            # data requires separate default parser because need to assign the date_format string to the parser
            if self.type == datetime.datetime:
                self._config_date_field()
            else:
                self._transform = _DEFAULT_PARSERS[self.type]

        if not isinstance(self.transform, Callable):
            raise TypeError("Transform argument must be a callable")


    def parse(self, value):
        """Transform the value according to the field's callable, and validate
        that the returned value from the call matches the type stored inside self._type.

        If value is None, will return None since None represents no data. No configuration
        will transform no data into data."""

        if value is None:
            return None

        transformed_value = self.transform(value)

        if not self.compatible(transformed_value):
            raise TypeError(f"Parsed value {transformed_value} is of type {type(transformed_value)},"
                            f"but should same as specified type: {self.type}.")
        return transformed_value

    def serialize(self,value)->str:
        if not self.compatible(value):
            raise RuntimeError("Value does not match the data type of this field")

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
            case type(None):
                return ""
            case _:
                # fallthrough for any other case that may somehow occur
                return str(value)

    def __eq__(self, other):
        """Comparison on the basis of field names"""
        if not isinstance(other, Field):
            return NotImplemented
        else:
            return self.name == other.name

    def _config_date_field(self):
        """ Sets self._transform for date type fields.

        Ensures self._date_format is set if the data type is datetime.date.
        Checks that the formatting string is a valid formatting string.
        """
        if self.type is not datetime.datetime:
            raise RuntimeError(f"Cannot be called from Field instance that is not a {datetime.date} instance")

        # Use partial for the datetime.date fields as need to pre-enter date_format such that can call transform(value) rather than transform(value, date_format)
        if self.date_format is None:
            raise RuntimeError("date_format cannot be set to none if data type"
                               f"is set to {datetime.datetime}")

        else:
            try:
                datetime.datetime.now().strftime(self.date_format)
            except ValueError as e:
                raise ValueError(f"Format string is invalid: {e}")
            self._transform = partial(_DEFAULT_PARSERS[self.type], date_format = self.date_format)

    # name is read only
    @property
    def name(self):
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

    @translation.setter
    def translation(self, translation):
        if not isinstance(translation, str):
            raise ValueError("Translated name must be a string")
        self._translation = translation

    @property
    def transform(self):
        return self._transform

    @transform.setter
    def transform(self, transformation):
        if not isinstance(transformation, Callable):
            raise ValueError("Transformation must be a callable")
        self._transform = transformation

    @property
    def type(self):
        return self._type

    @property
    def date_format(self):
        return self._date_format

    def compatible(self, value)->bool:
        """Return true if this value is compatible with the type of this Field"""
        return isinstance(value, self.type)

