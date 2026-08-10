import copy
from typing import Any

from .fields import Field
from .source_config import VisitPolicy, DEFAULT_VISIT_POLICY

"""Data for the patient should ALWAYS be square"""


class Patient:
    """Only deals with fields as Field objects, not as strings.

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
    def __init__(self, pt_id):
        self._id = pt_id
        self.data = {}
        """Of form {visit_label_str : {Field object : value,...}, ...}"""
        self._visits = []  # order = order of addition to self.data. Ordered list of visits required to implement VisitPolicy

    def __repr__(self):
        return f"ID: {self.id}"

    def __getitem__(self, key: Field | tuple[Field, str | None] | tuple[
        Field, VisitPolicy]):
        """
        patient[field]
        patient[field, visit_label]
        patient[field, visit_policy]
        """
        if len(key) not in range(1, 3):
            raise ValueError(f"Expected 1-2 elements, got {len(key)}")

        if isinstance(key, Field):
            return self.get_value(key, visit_policy=DEFAULT_VISIT_POLICY)

        if isinstance(key, tuple):
            field, other_param = key
            # is it a visit_label?
            if isinstance(other_param, str):
                return self.get_value(field, visit_label=other_param,
                                      visit_policy=DEFAULT_VISIT_POLICY)

            elif isinstance(other_param, VisitPolicy):
                return self.get_value(field, visit_policy=other_param)

            raise ValueError(
                "Expected second element in key to be a visit label (string) or a VisitPolicy")

        raise ValueError("Invalid elements")

    def __setitem__(self, key, value):
        """
        patient[field] = value
        patient[field, visit_label] = value
        patient[field, visit_label, transform] = value
        patient[field, transform] = value
        """
        if len(key) not in range(1, 4):
            raise ValueError(f"Expected 1-3 elements, got {len(key)}")

        if isinstance(key, Field):
            self.set(field=key, value=value)

        # key is a tuple
        else:
            if len(key) == 2:
                field, other_param = key

                # is the visit label
                if isinstance(other_param, str):
                    self.set(field=field, value=value, visit_label=other_param)
                # is the transformation
                elif isinstance(other_param, bool):
                    self.set(field=field, value=value, transform=other_param)
                else:
                    raise ValueError(
                        "Expected visit label or transform (bool) when passing 2 elements")

            else:
                field, param_2, param_3 = key
                if not isinstance(param_2, str):
                    raise TypeError("Expected string for visit_label")
                if not isinstance(param_3, bool):
                    raise TypeError("Expected bool for transform")

                self.set(field=field, value=value, visit_label=param_2,
                         transform=param_3)

    def __iter__(self):
        """Returns tuple (visit label [str], visit data [dict])"""
        yield from self.data.items()

    # make id read-only by not defining setter
    @property
    def id(self):
        return self._id

    @property
    def visits(self):
        return self._visits

    def copy(self):
        new_patient_obj = Patient(self.id)
        for visit_label, visit_data in self:
            new_patient_obj.add_visit(copy.deepcopy(visit_data),
                                      visit_label)

        return new_patient_obj

    def has_field(self, field: Field) -> bool:
        """Will return True if this patient has the field in their dataset.
        Does not matter if the value for this field is None for any nor all visits.

        Raise error on incorrect type"""
        if not isinstance(field, Field):
            raise TypeError(
                f"Expected type Field for field argument, got {type(field)} instead.")

        all_field_objects = self.data[self.visits[0]].values()
        return field in all_field_objects

    @property
    def fields(self) -> set[Field]:
        """Relies on dataset being square"""
        if not self.has_data:
            return set()
        else:
            first_visit_data = self.data[self.visits[0]]
            return set(first_visit_data.keys())

    def has_visit(self, visit_label) -> bool:
        return visit_label in self.data.keys()

    def set(self, field: Field, value,
            visit_label: str | None = -1, transform: bool = True):
        """Set the value for this field.
            If no visit_labels are specified, defaults to -1 (not None as a visit can have label None) and the value for the field
            will be set for each visit.
            Can specify many visit labels by passing a list of visit labels.
            If field is a string, must match the name of the field object (field_object.name)
            stored in the dictionaries of self.data's values. If field as a string only matches
            the translation of a field object, this will throw an error for a missing field.
            visit_label passed as None means that this patient is not part of a longitudinal study
            (does not have more than one visit), and that visit_label is stored as None.

            :param transform: Specifies if the value should be transformed before
                being set in accordance to the transformation Callable stored in
                the Field object. Defaults to True.
            :return: A copy of the value that the fields were set to
        '"""
        if self.data == dict():
            raise RuntimeError(
                "Cannot set field value as this patient has no data loaded")
        if not isinstance(transform, bool):
            raise TypeError(
                f"Expected type bool argument for transform parameter, got {type(transform)} instead")
        if not isinstance(field, Field):
            raise TypeError(
                f"Field must be of type Field. Passed type {type(field)}")

        if transform:
            set_value = field.parse(value)
        else:
            set_value = value

        if not field.compatible(set_value):
            raise TypeError(
                f"Field {field.name} can only accept objects of type {field.type}, tried to set it to {type(set_value)}")

        if visit_label != -1:
            if not self.has_visit(visit_label):
                raise ValueError(
                    f"Visit label {visit_label} not one of patient {self.id}'s visits")

            self.get_visit_data(visit_label)[field] = set_value

        else:
            for visit in self.data.keys():
                self.get_visit_data(visit)[field] = set_value

        return set_value

    def add_field(self, field: Field, default_value=None,
                  transform: bool = True):
        """Will raise RuntimeError if this patient has no data loaded (i.e. self.data == dict()).
        Else, will add the field to each visit, and will assign the value None.
        :param field: Field object to be added
        :param default_value: The value that this new field will be set to for all visits.
            Can be None, if not None must match field.type if transform==False.
            If transform==True, the value will be parsed, and the parsed value must match field.type.
            If none of the above conditions are met, a TypeError will be raised.
        :param transform: Boolean value to determine if the default_value will be
            parsed via field.parse(default_value). Ignored if default_value is None.
        :return: Returns value this new field was set to for all visits
        """
        if default_value is not None:
            if transform:
                set_value = field.parse(default_value)
            else:
                set_value = default_value

            if not isinstance(default_value, field.type):
                raise TypeError(
                    "Value that fields will be set to does not match the type"
                    f"specified by the field object ({field.type!r}). Got {type(set_value)} instead.")
        else:
            set_value = None

        if self.data == dict():
            raise RuntimeError(
                "Patient doesn't have any data loaded - cannot add field.")

        for _, visit_data in self.data:
            if field in visit_data.keys():
                raise RuntimeError(
                    f"Field of name {field.name} already exists for patient {self.id}")
            else:
                visit_data[field] = set_value

        return set_value

    def add_visit(self, data: dict[Field:Any], visit_label: str | None):
        if not data:
            raise ValueError(f"Empty row for patient {self.id}")

        if visit_label in self.visits:
            raise RuntimeError(
                f"Visit {visit_label} already loaded for patient {self.id}")

        # are we trying to introduce new columns?
        if self.fields != set(data.keys()):
            raise RuntimeError(f"Trying to introduce new columns to patient {self.id} dataset")

        self.data[visit_label] = data
        self.visits.append(visit_label)

    def get_visit_data(self, visit_label: str | None) -> dict:
        try:
            return self.data[visit_label]
        except KeyError:
            raise ValueError(
                f"Visit label {visit_label} does not exists for patient {self.id}")

    def get_value(self, field: Field,
                  visit_policy: VisitPolicy,
                  visit_label: str | None = -1) -> str | None:
        """
        :param field: The field for which we are grabbing the value
        :param visit_policy: Determines which non-None value is returned
            If no value is passed, will first try and find the policy for this field in config.FIELD_VISIT_POLICY, if it does not exist there, will use config.DEFAULT_VISIT_POLICY. Pass a VisitPolicy to override the policy for the field set in config.FIELD_VISIT_POLICY or config.DEFAULT_VISIT_POLICY

        :param visit_label: Optional parameter; visit to grab the field value from.
            ValueError raised if this visit does not exist.
        :return:: None if and only if None is the value for this field across all visits. Else, according to VisitPolicy.
        """

        if len(self.data) == 0:
            raise RuntimeError(f"Patient {self.id} has no visits")

        if not isinstance(field, Field):
            raise TypeError("field argument should be a Field object")

        if field not in self.data[self.visits[0]].keys():
            raise ValueError(
                f"Field {field!r} does not exist for patient {self.id}")

        if visit_policy is None:
            raise ValueError(f"Visit policy is None for patient {self.id}")

        # visit to choose was specified
        if visit_label != -1:
            if visit_label not in self.data:
                raise ValueError(
                    f"Visit label {visit_label} not present for patient {self.id}")
            else:
                return self.get_visit_data(visit_label)[field]

        found_value = None

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

        return found_value

    def visit_has_data(self, visit_label) -> bool:
        """
        :param visit_label: Visit to check for data
        :return: False if all fields have None for this visit, or if
            self.data[visit_label] == dict().
        """
        if not self.has_visit(visit_label):
            raise ValueError(f"Patient has no visit {visit_label!r}")

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

    def remove(self,**kwargs):
        """:param kwargs: Keyword arguments. Must contain one of field - Field object,
            fields - Iterable[Field]
            visit_label - a unique visit label
            visit_labels - Iterable[visit labels]
            Each extra field further specifies what values will be removed.
            To keep the dataset flat, removing a value means that the value will be
            set to None; the key will still exist in self.data[patient_id].

            Specifying visits means that every single patient that is looked at
            must have that/those visits.
            If vists remains unspecified, logic will only be applied to the visits
            each patient has.

            raise_on_missing_fields: Raise ValueError if specified a field
            that this patient does not have.
                Defaults to True

            raise_on_missing_visits: Raise ValueError if specified a field
            that this patient does not have.
                Defaults to True
        """

        allowed_kwargs = {'field', 'fields', 'visit', 'visits','raise_on_missing_fields','raise_on_missing_visits'}


        DEFAULT_RAISE_ON_MISSING_FIELDS = True
        DEFAULT_RAISE_ON_MISSING_VISITS = True

        raise_on_missing_fields=kwargs.get('raise_on_missing_fields',DEFAULT_RAISE_ON_MISSING_FIELDS)
        raise_on_missing_visits=kwargs.get('raise_on_missing_visits',DEFAULT_RAISE_ON_MISSING_VISITS)


        for kwarg in kwargs:
            disallowed_kwargs = set()

            if kwarg not in allowed_kwargs:
                disallowed_kwargs.add(kwarg)

            if len(disallowed_kwargs) != 0:
                raise TypeError(
                    f"Unexpected keyword argument(s) {disallowed_kwargs!r}")

        # flag is needed in case 'field' or 'fields' was passed but were empty
        specified_fields = False
        set_fields = set()
        if 'field' in kwargs:
            specified_fields = True
            field = kwargs['field']
            if self.has_field(field):
                set_fields.add(field)

            elif raise_on_missing_fields:
                raise ValueError(f"Unexpected field {field!r}.")

        if 'fields' in kwargs:
            specified_fields = True
            missing_fields = set()
            for field in kwargs['fields']:
                if self.has_field(field):
                    set_fields.add(field)
                else:
                    missing_fields.add(field)

            if len(missing_fields) != 0 and raise_on_missing_fields:
                raise ValueError(f"Unexpected field(s) {missing_fields!r}")

        # flag is needed in case 'visit_label' or 'visit_labels' were passed but were empty
        specified_visits = False
        set_visits = set()
        if 'visit' in kwargs:
            specified_visits = True
            visit = kwargs['visit']
            if self.has_visit(visit):
                set_visits.add(visit)
            elif raise_on_missing_visits:
                raise ValueError(f"Unexpected visit {visit!r}.")

        if 'visits' in kwargs:
            specified_visits = True
            missing_visits = set()
            for visit in kwargs['visits']:
                if self.has_visit(visit):
                    set_visits.add(visit)
                else:
                    missing_visits.add(visit)

            if len(missing_visits) != 0 and raise_on_missing_visits:
                raise ValueError(f"Unexpected visit(s) {missing_visits!r}")

        if not specified_fields:
            set_fields = self.fields
        if not specified_visits:
            set_visits = set(self.visits)

        for visit in set_visits:
            for field in set_fields:
                self[field,visit] = None


    def clear(self):
        """Removes all data"""
        self.data = {}
        self._visits = []
