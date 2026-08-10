from datetime import datetime

_TRUTHY = {"1", "true", "yes", "y"}
"""All strings in here are lowercased; use .lower() before comparison"""

_FALSY = {"0", "false", "no", "n"}

def _coerce_date(value, date_format) -> datetime.date:
    """:param value: A string representing the date to parse
    :param date_format: expects a string like "%Y-%m-%d
    :return: Date object
    """
    try:
        out = datetime.strptime(value, date_format).date()
    except ValueError as e:
        raise TypeError(f"Invalid date string or string does not match format: {e}")

    return out

def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in _TRUTHY:
            return True
        if value in _FALSY:
            return False

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