import copy
from typing import Any, Iterator, cast

from .fields import _Field, Field_T, permitted_types
from .source_config import VisitPolicy, DEFAULT_VISIT_POLICY

# allow no wildcard imports
__all__ = []

class _UNSPECIFIED:
    pass


"""Data for the patient should ALWAYS be square"""


class _Patient:
    """PRIVATE CLASS - only to be implemented by Dataset class
    Only deals with fields as _Field objects, not as strings.

    Supports dict-style access for convenience:
        patient[field]                -> get value (default visit policy, all visits)
        patient[field, visit_label]   -> get value from one specific visit]
        patient[field, visit_policy]  -> get value for a specified visit policy

        patient[field] = value        -> set value across all visits
        patient[field, visit_label] = value -> set value for one visit
        patient[field, visit_label, transform] = value --> set value for one visit, decide if will be saved as field.parse(value)
        patient[field, transform] = value --> set value across all visits, decide if will be saved as field.parse(value)
    """

    # unexpected visit labels (not passed to __init__ in argument expected_events will be appended to end of list self.data
    def __init__(self, pt_id) -> None:
        self._id = pt_id
        self.data: dict[permitted_types, dict[_Field, permitted_types]] = {}
        """Of form {visit_label_str : {_Field object : value,...}, ...}"""
        self._visits: list[
            permitted_types] = []  # order = order of addition to self.data. Ordered list of visits required to implement VisitPolicy

    def __repr__(self) -> str:
        return f"ID: {self.id}"

    def __getitem__(self,
                    key: _Field[Field_T] | tuple[
                        _Field[Field_T], permitted_types] |
                         tuple[
                             _Field[Field_T], VisitPolicy]) -> Field_T | None:
        """
        patient[field]
        patient[field, visit_label]
        patient[field, visit_policy]
        """

        if isinstance(key, _Field):
            return self.get_value(key)
        # only one argument passed and it wasn't a _Field
        elif not isinstance(key, tuple):
            raise TypeError(f"Expected _Field argument, got {type(key)}.")

        if isinstance(key, tuple):
            if len(key) not in range(1, 3):
                raise ValueError(f"Expected 1-2 elements, got {len(key)}")

            field, other_param = key
            if isinstance(other_param, VisitPolicy):
                return self.get_value(field, visit_policy=other_param)
            else:
                return self.get_value(field, visit_label=other_param)

        raise ValueError("Invalid element(s)")

    def __setitem__(self,
                    key: _Field[Field_T] | tuple[
                        _Field[Field_T], permitted_types],
                    value: Field_T):
        """
        patient[field] = value
        patient[field, visit_label] = value
        """
        if isinstance(key, _Field):
            self.set(field=key, value=value)
            return

        # means only 1 value was passed in brackets, and it was not a _Field, as
        # if it was several values it would've been packed into a tuple
        elif not isinstance(key, tuple):
            raise TypeError(f"Expected _Field argument, got {type(key)}.")

        # key is a tuple
        else:
            if len(key) not in range(1, 3):
                raise ValueError(f"Expected 1-2 elements, got {len(key)}")
            field, visit_label = key
            self.set(field=field, value=value, visit_label=visit_label)

    def __iter__(self) -> Iterator[tuple[permitted_types, dict[_Field, Any]]]:
        """Returns tuple (visit label, visit data [dict])"""
        yield from self.data.items()

    # make id read-only by not defining setter
    @property
    def id(self):
        return self._id

    @property
    def visits(self) -> list[permitted_types]:
        return self._visits

    def copy(self) -> '_Patient':
        new_patient_obj = _Patient(self.id)
        for visit_label, visit_data in self:
            new_patient_obj.add_visit(copy.deepcopy(visit_data),
                                      visit_label)

        return new_patient_obj

    def has_field(self, field: _Field) -> bool:
        """Will return True if this patient has the field in their dataset.
        Does not matter if the value for this field is None for any nor all visits.

        Raise error on incorrect type"""
        if not isinstance(field, _Field):
            raise TypeError(
                f"Expected type _Field for field argument, got {type(field)} instead.")

        if not self.has_data:
            return False
        all_field_objects = self.data[self.visits[0]].values()
        return field in all_field_objects

    @property
    def fields(self) -> set[_Field]:
        """Relies on dataset being square"""
        if not self.has_data:
            return set()
        else:
            first_visit_data = self.data[self.visits[0]]
            return set(first_visit_data.keys())

    def has_visit(self, visit_label: permitted_types) -> bool:
        if not self.has_data:
            return False
        visit_labels_type = type(self.visits[0])
        if not isinstance(visit_label, visit_labels_type):
            raise TypeError(f"Visit label is of wrong type - got {type(visit_label)}, expected {visit_labels_type}")

        return visit_label in self.data.keys()

    def set(self, field: _Field[Field_T], value: Field_T,
            visit_label: permitted_types | type[_UNSPECIFIED] = _UNSPECIFIED):
        """Set the value for this field.
            If no visit_labels are specified, defaults to -1 (not None as a visit can have label None) and the value for the field
            will be set for each visit.
            Can specify many visit labels by passing a list of visit labels.
            If field is a string, must match the name of the field object (field_object.name)
            stored in the dictionaries of self.data's values. If field as a string only matches
            the translation of a field object, this will throw an error for a missing field.
            visit_label passed as None means that this patient is not part of a longitudinal study
            (does not have more than one visit), and that visit_label is stored as None.

            :return: A copy of the value that the fields were set to
        '"""
        if self.data == dict():
            raise RuntimeError(
                "Cannot set field value as this patient has no data loaded")
        if not isinstance(field, _Field):
            raise TypeError(
                f"_Field must be of type _Field. Passed type {type(field)}")

        if not field.is_matching_type(value):
            raise TypeError(
                f"_Field {field.name} can only accept objects of type {field.type}, tried to set it to {type(value)}")

        if not visit_label is _UNSPECIFIED:
            # for static type checking
            visit_label = cast(permitted_types, visit_label)
            if self.has_visit(visit_label):
                raise ValueError(
                    f"Visit label {visit_label} not one of patient {self.id}'s visits")

            self.get_visit_data(visit_label)[field] = value

        # visit_label is _UNSPECIFIED
        else:
            for visit in self.data.keys():
                self.get_visit_data(visit)[field] = value

        return value

    def add_field(self, field: _Field[Field_T],
                  default_value: Field_T | None = None) -> Field_T | None:
        """Will raise RuntimeError if this patient has no data loaded (i.e. self.data == dict()).
        Else, will add the field to each visit, and will assign the value None.
        :param field: _Field object to be added
        :param default_value: The value that this new field will be set to for all visits.
            Can be None.
        :return: Returns value this new field was set to for all visits
        """
        if default_value is not None:
            if not isinstance(default_value, field.type):
                raise TypeError(
                    "Value that fields will be set to does not match the type"
                    f"specified by the field object ({field.type!r}). Got {type(default_value)} instead.")
        if self.data == dict():
            raise RuntimeError(
                "_Patient doesn't have any data loaded - cannot add field.")

        for _, visit_data in self.data.items():
            for f in visit_data.keys():
                # any fields that match
                if field.equals(f):
                    raise RuntimeError(
                        f"Cannot create field {field.name} because"
                        f"an equivalent field of name {f.name} already exists for patient {self.id}.")
            else:
                visit_data[field] = default_value

        return default_value

    def add_visit(self, data: dict[_Field, Any], visit_label: permitted_types):
        if not data:
            raise ValueError(f"Empty row for patient {self.id}")

        if visit_label in self.visits:
            raise RuntimeError(
                f"Visit {visit_label} already loaded for patient {self.id}")

        # are we trying to introduce new columns?
        if self.fields != set(data.keys()):
            raise RuntimeError(
                f"Trying to introduce new columns to patient {self.id} dataset")

        self.data[visit_label] = data
        self.visits.append(visit_label)

    def get_visit_data(self, visit_label: permitted_types) -> dict[_Field, Any]:
        """

        :param visit_label: if _UNSPECIFIED is passed, return se
        :return:
        """
        if not self.has_visit(visit_label):
            raise KeyError(f"Visit label {visit_label} does not exists for patient {self.id}")

        else:
            return self.data[visit_label]

    def get_value(self, field: _Field[Field_T],
                  visit_policy: VisitPolicy = DEFAULT_VISIT_POLICY,
                  visit_label: permitted_types | type[_UNSPECIFIED] = _UNSPECIFIED) -> Field_T | None:
        """
        :param field: The field for which we are grabbing the value
        :param visit_policy: Determines which non-None value is returned
            If no value is passed, will first try and find the policy for this field in config.FIELD_VISIT_POLICY, if it does not exist there, will use config.DEFAULT_VISIT_POLICY. Pass a VisitPolicy to override the policy for the field set in config.FIELD_VISIT_POLICY or config.DEFAULT_VISIT_POLICY

        :param visit_label: Optional parameter; visit to grab the field value from.
            ValueError raised if this visit does not exist.
        :return:: None if and only if None is the value for this field across all visits. Else, according to VisitPolicy.
        """

        if len(self.data) == 0:
            raise RuntimeError(f"_Patient {self.id} has no visits")

        if not isinstance(field, _Field):
            raise TypeError("field argument should be a _Field object")

        if field not in self.data[self.visits[0]].keys():
            raise ValueError(
                f"_Field {field!r} does not exist for patient {self.id}")

        if visit_policy is None:
            raise ValueError(f"Visit policy is None for patient {self.id}")

        # visit to choose was specified
        if visit_label is not _UNSPECIFIED:
            # for static type checking - runtime type checking done by self.has_visit
            visit_label = cast(permitted_types, visit_label)
            if not self.has_visit(visit_label):
                raise ValueError(
                    f"Visit label {visit_label} not present for patient {self.id}")
            else:
                return self.get_visit_data(visit_label)[field]

        # ONLY REACHED IF VISIT LABEL WAS UNSPECIFIED
        found_value: permitted_types | None = None

        for label, visit_data in self.data.items():

            tmp_value = visit_data[field]
            if tmp_value is None:
                continue

            if visit_policy == VisitPolicy.REQUIRE_CONSISTENT:
                # first non-None value encountered
                if found_value is None:
                    found_value = tmp_value
                    continue
                else:
                    # same as previously encountered value
                    if tmp_value == found_value:
                        continue
                    # not the same as previously encountered value
                    raise RuntimeError(
                        f"Values for field {field} is not consistent across visits "
                        f"for patient {self.id}.")

            elif visit_policy == VisitPolicy.FIRST:
                found_value = tmp_value
                break

            elif visit_policy == VisitPolicy.LATEST:
                found_value = tmp_value
                continue

        # for static type checking
        found_value = cast(Field_T, found_value)

        return found_value

    def visit_has_data(self, visit_label: str) -> bool:
        """
        :param visit_label: Visit to check for data
        :return: False if all fields have None for this visit, or if
            self.data[visit_label] == dict().
        """
        if not self.has_visit(visit_label):
            raise ValueError(f"_Patient has no visit {visit_label!r}")

        visit_data = self.get_visit_data(visit_label)

        for value in visit_data.values():
            if value is not None:
                return True

        return False

    @property
    def has_data(self) -> bool:
        if self.data == dict():
            return False

        for data in self.data.values():
            for value in data.values():
                if value is not None:
                    return True
        return False

    def remove(self, **kwargs) -> bool:
        """
            Will raise RuntimeError if try to remove nothing.

            :param kwargs: Keyword arguments. Must contain one of:
            field - _Field object,
            fields - Iterable[_Field]
            visit_label - a unique visit label
            visit_labels - Iterable[visit labels]
            Each extra field further specifies what values will be removed.
            To keep the dataset flat, removing a value means that the value will be
            set to None; the key will still exist in self.data[patient_id].

            Specifying visits means that every single patient that is looked at
            must have that/those visits.
            If visits remains unspecified, logic will only be applied to the visits
            each patient has.

            delete_visit_when_empty - bool
                Delete a visit for this patient when there is no more data after removal.
                Will not delete visits that were already empty

            raise_on_missing_fields: Raise ValueError if specified a field
            that this patient does not have.
                Defaults to True

            raise_on_missing_visits: Raise ValueError if specified a field
            that this patient does not have.
                Defaults to True

            :return: True if elements were removed
        """

        allowed_kwargs = {'field', 'fields', 'visit', 'visits', 'delete_visit_when_empty'
                                                                'raise_on_missing_fields', 'raise_on_missing_visits'}

        DEFAULT_RAISE_ON_MISSING_FIELDS = True
        DEFAULT_RAISE_ON_MISSING_VISITS = True
        DEFAULT_DELETE_VISIT_WHEN_EMPTY = False

        raise_on_missing_fields = kwargs.get('raise_on_missing_fields',
                                             DEFAULT_RAISE_ON_MISSING_FIELDS)
        raise_on_missing_visits = kwargs.get('raise_on_missing_visits',
                                             DEFAULT_RAISE_ON_MISSING_VISITS)

        delete_visit_when_empty = kwargs.get('delete_visit_when_empty', DEFAULT_DELETE_VISIT_WHEN_EMPTY)

        for kwarg in kwargs:
            disallowed_kwargs = set()

            if kwarg not in allowed_kwargs:
                disallowed_kwargs.add(kwarg)

            if len(disallowed_kwargs) != 0:
                raise TypeError(
                    f"Unexpected keyword argument(s) {disallowed_kwargs!r}")

        # So the logic here essentially is if you don't specify field/fields and/or visit/visits
        # parameters, all fields and/or visits respectively will be looked at.
        # if you pass field/fields, visit/visits, but those parameters hold no values,
        # that implies you are trying to remove nothing, which will throw an error.
        set_fields: set[_Field] = set()
        are_fields_set = False
        if 'fields' in kwargs:
            are_fields_set = True
            set_fields.update(kwargs['fields'])
        if 'field' in kwargs:
            are_fields_set = True
            set_fields.add(kwargs['field'])

        set_visits: set[permitted_types] = set()
        are_visits_set = False
        if 'visits' in kwargs:
            are_visits_set = True
            set_fields.update(kwargs['visits'])
        if 'visit' in kwargs:
            are_visits_set = True
            set_fields.add(kwargs['visit'])

        if not are_fields_set:
            set_fields = self.fields
        if not are_visits_set:
            set_visits = set(self.visits)

        for field in set_fields:
            missing_fields = set()
            if self.has_field(field):
                set_fields.add(field)
            else:
                missing_fields.add(field)

            if len(missing_fields) != 0:
                if raise_on_missing_fields:
                    raise ValueError(f"Unexpected field(s) {missing_fields!r}")

                set_fields.difference_update(missing_fields)
                # if we've removed all of them now...
                if set_fields == set():
                    return False

        for visit in set_visits:
            missing_visits = set()
            if self.has_visit(visit):
                set_visits.add(visit)
            else:
                missing_visits.add(visit)

            if len(missing_visits) != 0:
                if raise_on_missing_visits:
                    raise ValueError(f"Unexpected visit(s) {missing_visits!r}")

                set_visits.difference_update(missing_visits)
                # if we've removed all of them now...
                if set_visits == set():
                    return False

        removed_data = False
        while set_visits != set():
            visit = set_visits.pop()
            visit_data = self.get_visit_data(visit)

            # for the delete_visit_when_empty check - to avoid deleting already empty visits
            removed_visit_data = False
            for field in set_fields:
                visit_data[field] = None
                removed_data = True

            if delete_visit_when_empty:
                if removed_visit_data and all(value is None for value in visit_data.values()):
                    del self.data[visit]

        return removed_data

    def clear(self):
        """Removes all data"""
        self.data = {}
        self._visits = []
