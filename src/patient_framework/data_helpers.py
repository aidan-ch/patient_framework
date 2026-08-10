"""Default parsers when none is passed """

from datetime import datetime

_TRUTHY = {"1", "true","t", "yes", "y"}

_FALSY = {"0", "false","f", "not","no", "n",""}

def _coerce_date(value, format_str) -> datetime:
    """:param value: A string representing the date to parse
    :param format_str: expects a string like "%Y-%m-%d"
    :return: Date object
    """
    try:
        out = datetime.strptime(value, format_str)
    except ValueError as e:
        raise TypeError(f"Date string does not match format, or format is invalid: {e}")

    return out

def _coerce_bool(value:bool|int|str) -> bool:
    """:param value: If value is a str object, must be one of _TRUTHY, or _FALSY
    to be parsed to a boolean, else will raise TypeError."""
    if isinstance(value,str):
        if value.lower() in _TRUTHY:
            return True
        elif value.lower() in _FALSY:
            return False
    elif isinstance(value, bool):
        return value
    elif isinstance(value, int):
        return bool(value)

    raise TypeError(f"Cannot coerce {value!r} to a boolean")

def _coerce_str(value):
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except TypeError as e:
        raise TypeError(f"Could not coerce {value!r} into a string: {e}")

def _coerce_int(value):
    if isinstance(value,int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise TypeError(f"Could not coerce {value!r} into an integer: {e}")

def _coerce_float(value):
    if isinstance(value, float):
        return value

    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise TypeError(f"Could not coerce {value!r} into a float: {e}")

def _coerce_none(value):
    """Essentially just checks that this value is in fact None"""
    if value is not None:
        raise TypeError(f"{value!r} is of type {type(value)} and not {type(None)}")

    return None