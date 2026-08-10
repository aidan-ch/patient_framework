import datetime
from typing import Callable, Type, get_args
from functools import partial

from .data_helpers import _coerce_str, _coerce_bool, _coerce_int, _coerce_float, _coerce_none, _coerce_date





_DEFAULT_PARSERS = {
    str : _coerce_str,
    bool : _coerce_bool,
    int : _coerce_int,
    float: _coerce_float,
    type(None) : _coerce_none,
    datetime.date : _coerce_date
}


permitted_types = str | int | float | bool | datetime.date | type(None)
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
            If None is passed, then will use the built-in parser (in parsers.py)
        :param data_type: Data type that the values of this field should be upon import
            AND after parsing.
        :param date_format: Only need to specify if data_type == datetime.date"""



        self._type = data_type
        """Must be one of permitted_types"""
        self._name = name
        self._translation = translation
        self._date_format = date_format


        if transformation is not None:
            self._transform = transformation
            """Callable that will transform the values of this field in the dataset by calling transform(value).
            Must return data of type stated in permitted_types"""

        # assign default parsers
        else:
            # data requires separate default parser because need to assign the date_format string to the parser
            if self.type == datetime.date:
                self._config_date_field()
            else:
                self._transform = _DEFAULT_PARSERS[self.type]

        if not _is_permitted_type(self.type):
            raise TypeError(f"Type argument must be one of {permitted_types}")

        if self.translation.strip() == "":
            raise ValueError(
                "Translation name cannot be empty. If no translation, must be set to None")

        if self.transform is None or not isinstance(self.transform, Callable):
            raise TypeError("Transform argument must be a callable")


    def _config_date_field(self):
        """ Sets self._transform for date type fields.

        Ensures self._date_format is set if the data type is datetime.date.
        Checks that the formatting string is a valid formatting string.
        """
        if self.type is not datetime.date:
            raise RuntimeError(f"Cannot be called from Field instance that is not a {datetime.date} instance")

        # Use partial for the datetime.date fields as need to pre-enter date_format such that can call transform(value) rather than transform(value, date_format)
        if self.date_format is None:
            raise RuntimeError("date_format cannot be set to none if data type"
                               f"is set to {datetime.date}")

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

        :return: Self.name if no translation available (i.e. _translation is None)"""
        if self._translation is None:
            return self.name
        return self._translation

    @translation.setter
    def translation(self, translation):
        if not isinstance(translation, str):
            raise ValueError("Translated name must be a string")
        self._translation = translation

    def parse(self, value):
        """Transform the value according to the field's callable, and validate
        that the returned value from the call matches the type stored inside self._type"""
        transformed_value = self.transform(value)

        if not isinstance(transformed_value,self.type):
            raise TypeError(f"Parsed value {transformed_value} is of type {type(transformed_value)},"
                               f"but should same as specified type: {self.type}.")
        return transformed_value

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

