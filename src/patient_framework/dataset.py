import copy
import csv
import datetime
import inspect
import json
from abc import ABC
from math import isclose
from pathlib import Path
from typing import Callable, Any, Iterator

import requests

from .fields import _Field, permitted_types
from .schema import _Patient
from .source_config import Source, VisitPolicy, DEFAULT_VISIT_POLICY

__all__ = ['OVERWRITE_CSV_FILES', 'OVERWRITE_JSON_FILES', 'Dataset','ApiDataset','CsvDataset','BuildDataset']


OVERWRITE_CSV_FILES = False
"""Flag to overwrite existing .csv files if its path is passed to Dataset.save_as_csv(self,path,append_date_time)"""

OVERWRITE_JSON_FILES = False
"""Flag to overwrite existing .json files if its path is passed to Dataset.save_as_json(self,path,append_date_time)"""


class Dataset(ABC):
    """ALL PATIENTS WILL ALWAYS HAVE ALL THE SAME FIELDS.
    NOT ALL PATIENTS WILL NECESSARILY HAVE ALL THE SAME VISITS"""

    REQUIRE_FIELD_CONFIG = False
    """Does field_data need to be passed and does it need to configure every field
    found in the dataset?"""
    DEFAULT_DATA_TYPE = str
    """Default data type filled into Dataset._field_obj_dict's _Field objects when
    that field is not configured in self.field_data.
    Irrelevant if REQUIRE_FIELD_CONFIG == True
    """

    def __init__(self, source: Source, field_data: dict[str, dict[str, Any]] | None):
        self.source = source
        self.patients: dict[permitted_types, _Patient] = {}
        """Dictionary holding all patients of dataset.
            Form: {patient_id : _Patient object}"""

        self.field_data = dict()
        """Acceptable for there to be fields in this object that are not found in 
        the loaded dataset. i.e. it is possible for len(self.field_data) > len(self.raw_fields)
        after dataset is fully loaded/initialized.
        Fields configured in field_data that are not present in the data that is loaded
        will NOT be added as fields to this dataset object; the extra fields will
        just be ignored."""
        if field_data is not None:
            # want to copy the inner dicts to remove mutability
            for f, data in field_data.items():
                self.field_data[f] = copy.deepcopy(data)
            self._validate_field_data(self.field_data)

        self._field_obj_dict: dict[str, _Field] = dict()
        """Initialized gradually as self.get_field_object() is called.
        Can ONLY be modified by self._get_or_build_field_object()"""

    # if you want to print it
    def __str__(self) -> str:
        """
        Patient ID will always be first column.
        Visit/event will always be second column (if present)

        :return: string representation of dataset
        """
        # maximum width of each column (width of largest value)
        # field name : max width
        col_widths: dict[str, int] = {}
        headers = []
        out_str = ""

        column_delimiter = " | "
        headers.append(self.id_field)
        col_widths[self.id_field] = len(self.id_field)
        # i.e. if self.event_field is not None
        if not self.flat:
            headers.append(self.event_field)
            col_widths[self.event_field] = len(self.event_field)
        for field_name in self.raw_fields:
            # for id field and event field already added
            if field_name in headers:
                continue
            headers.append(field_name)
            col_widths[field_name] = len(field_name)

        # not add it to a final string yet so we can space them
        serialized_data: list[dict[str, str]] = []

        for pt_id, pt_obj in self.patients.items():
            for _, row_data in pt_obj:
                row_dict = {}
                for f_obj, val in row_data.items():

                    serialized_val = f_obj.serialize(val)

                    if len(serialized_val) > col_widths[f_obj.name]:
                        col_widths[f_obj.name] = len(serialized_val)

                    row_dict[f_obj.name] = serialized_val
                serialized_data.append(row_dict)

        for row in serialized_data:
            out_str += "".join(
                value + column_delimiter + " " * (col_widths[field_name] - len(value)) for field_name, value in
                row.items())
            out_str += '\n'

        out_str = column_delimiter.join([*headers, out_str])

        return out_str

    def __getitem__(self, patient_id: permitted_types) -> _Patient:
        if patient_id not in self.ids:
            raise KeyError(f"_Patient {patient_id} does not exist")
        return self.patients[patient_id]

    def __setitem__(self, _):
        # TODO non-technical error message
        raise RuntimeError("Cannot modify Dataset this way")

    def __iter__(self) -> Iterator[tuple[permitted_types, _Patient]]:
        """Returns tuple (patient_id, patient) for all patients"""
        yield from self.patients.items()

    def _get_or_build_field_object(self, field: str) -> _Field:
        """
        If field object already exists with this field name, will simply return that.

        Creates a field object for a given field_name string if it does not exist.

            If there is no entry field_name in self.field_data,
            it will create a default _Field object _Field(field_name).
        """
        if self.has_field(field):
            return self._get_field_object(field)

        if field not in self.field_data:
            if self.REQUIRE_FIELD_CONFIG:
                raise RuntimeError("Not all fields in dataset are configured via field_data argument."
                                   f"REQUIRE_FIELD_CONFIG == {self.REQUIRE_FIELD_CONFIG}")
            field_object = _Field(field, data_type=self.DEFAULT_DATA_TYPE)
        else:
            if 'name' in self.field_data[field].keys():
                field_object = _Field(**self.field_data[field])
            else:
                field_object = _Field(name=field, **self.field_data[field])

        self._field_obj_dict[field] = field_object
        return field_object

    def _get_field_object(self, field: str) -> _Field:
        if field not in self._field_objects:
            raise KeyError(f"No field {field!r}")
        return self._field_obj_dict[field]

    @property
    def field_object_dict(self) -> dict[str, _Field]:
        return self._field_obj_dict

    def save_as_csv(self, path: Path | str, append_date_time: bool = True) -> None:
        """Save the dataset as a csv.
        :param path: Path to CSV to be saved.
        :param append_date_time: Boolean value indicating whether or not the
            method will append the date and time to the path (before the
            suffix .csv).
            e.g. path = "mycsv.csv", append_date_time==True
            File will be saved to mycsv_2026_6_30-14:15.csv
        """
        # if passed as a string
        path = Path(path)
        if path.exists():
            if not OVERWRITE_CSV_FILES:
                raise FileExistsError(f"{path} already exists")
            if path.is_dir():
                raise IsADirectoryError(f"{path} is a directory")

        if path.suffix != '.csv':
            raise ValueError("File extension must be .csv")

        if append_date_time:
            date_time = datetime.datetime.now()
            path = path.with_name(f"{path.stem}_{date_time.strftime('%Y_%m_%d_%H-%M')}.csv")

        with open(path, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.raw_fields)
            writer.writeheader()

            for patient_id, patient_obj in self.patients.items():
                for visit_label, visit_data in patient_obj.data.items():
                    serialized_row = {f_obj.name: f_obj.serialize(val) for f_obj, val in visit_data.items()}
                    writer.writerow(serialized_row)

    @property
    def json(self) -> str:
        """Returns json string of the dataset"""
        data = []
        for _, pt_obj in self.patients.items():
            for __, visit_data in pt_obj:
                tmp_dict = {f_obj.name: f_obj.serialize(value) for f_obj, value in visit_data.items()}
                data.append(tmp_dict)

        return json.dumps(data)

    def save_as_json(self, path: Path | str, append_date_time: bool = True) -> Path:
        """
        Converts data to JSON format, and saves it to a .json file.
        Returns path of the .json.

        Will be of a list of dicts of the form:
        [{id_field:pt_id,event_field:event,dob_field:birthday,...}, {id_field:pt_id,event_field:event_2,...},
        {id_field:pt_id_2:event_field:event,...}, ... ]
        """

        # if passed as a string:
        path = Path(path)
        if path.exists():
            if not OVERWRITE_JSON_FILES:
                raise FileExistsError(f"{path} already exists")
        if path.is_dir():
            raise ValueError(f"{path} is a directory")
        if path.suffix != '.json':
            raise ValueError("File extension must be .json")

        if append_date_time:
            date_time = datetime.datetime.now()
            path = path.with_name(f"{path.stem}_{date_time.strftime('%Y_%m_%d_%H-%M')}.json")

        with open(file=path, mode='w') as f:
            f.write(self.json)

        return path

    @property
    def id_field(self) -> str:
        return self.source.id_field_name

    @property
    def event_field(self) -> str:
        if self.flat:
            raise RuntimeError("Dataset is flat, no event field")
        return self.source.event_field_name

    @property
    def raw_fields(self) -> set[str]:
        return set(self._field_obj_dict.keys())

    @property
    def _field_objects(self) -> set[_Field]:
        return set(self._field_obj_dict.values())

    @property
    def _patient_objects(self) -> set[_Patient]:
        return set(self.patients.values())

    def has_field(self, field: str) -> bool:
        if isinstance(field, str):
            return field in self.raw_fields
        else:
            raise TypeError(f"Expected type str for argument field, got {type(field)} instead")

    def _in(self, patient_id: permitted_types, event_label: permitted_types,
            row: dict[_Field, permitted_types]) -> None:

        if patient_id not in self.patients:
            self.patients[patient_id] = _Patient(patient_id)
        self.patients[patient_id].add_visit(data=row, visit_label=event_label)

    def add_row(self, row: dict[str, Any], transform: bool = True) -> None:
        """
        Cannot have extra fields.
        Missing fields will be filled with None.

        Fields are matched on the basis of _Field.name and the string keys (field names) of the row dict.
        :param row: Data to be added
        :param transform: Apply the transformation associated to each _Field
        in this dataset, True by default.
        """

        # check for extra keys
        for field in row.keys():
            extra_fields = set()
            if not self.has_field(field):
                extra_fields.add(field)
            if len(extra_fields) > 0:
                raise ValueError(f"Extra fields detected: {extra_fields}")

        parsed_row = self._parse_row(row, transform)

        if self.flat:
            event_label = None
        else:
            event_label = row[self.event_field]
        self._in(patient_id=row[self.id_field], event_label=event_label, row=parsed_row)

    def add_column(self, field: str, default_value=None, **field_attributes) -> None:
        """
        :param default_value: default value to be added to each row for this column.
        :param field: _Field name - will raise error if already part of dataset.
        :param field_attributes: Of form {'name':field_name, 'data_type':field_type,...}
            for any or all of the arguments used to initialize an instance of the _Field class
        :return: None
        """
        # make sure field_data is formatted correctly
        self._validate_field_data({field: field_attributes})

        # check for field with matching name before adding field attributes to dict.
        # Comparing the newly built field object to existing field objects will
        # account for overlap in translations. This is just to avoid overwriting
        # an entry in self.field_data before the field object for this new field
        # is built
        if self.has_field(field):
            raise ValueError("_Field by this name already exists")

        # some of the attributes were specified, so add it to our dict of field data
        if field_attributes != dict():
            self.field_data[field] = field_attributes

        # make/get field object
        field_object = self._get_or_build_field_object(field)
        # any other equivalent fields to this new one, check for instance equivalence as this new field
        # was already added to self._field_objects
        if any((other_field_obj.equals(field_object) and not other_field_obj is field_object) for other_field_obj in
               self._field_objects):
            raise ValueError("Identical field already exists (check field names and translations")

        for _, pt_obj in self:
            pt_obj.add_field(field_object, default_value)

    # generic, cant compare fields of different types
    @staticmethod
    def match_by_field(ds_1: "Dataset", ds_2: "Dataset", field_1: str, field_2: str) -> list[
        tuple[permitted_types, permitted_types]]:
        """:return: list of tuples (id_dataset1, id_dataset2) for patients that matched by field."""

        if not ds_1.has_field(field_1):
            raise ValueError(f"_Field {field_1} missing from dataset 1")
        if not ds_2.has_field(field_2):
            raise ValueError(f"_Field {field_2} missing from dataset 2")

        out = list()
        patients_1 = ds_1.patients
        patients_2 = ds_2.patients

        for id_1 in patients_1:
            val_1 = ds_1.get_value(id_1, field_1)

            for id_2 in patients_2:
                val_2 = ds_2.get_value(id_2, field_2)
                if val_1 != val_2:
                    continue
                else:
                    out.append((id_1, id_2))
        return out

    @staticmethod
    def difference(ds_1: "Dataset", ds_2: "Dataset", ) -> dict[permitted_types, list[dict[str, Any]]]:
        """
        *** Relies on IDs being of the same data type (as indicated in _Field).

        Determines if two fields are equal (and can be compared) using the
        _Field.equals() method.

        Takes two datasets where it is assumed identical patient IDs means
        identical patients and compares all fields that can be compared on the
        basis of field names, and field name translations.
        e.g. if field_1 is in ds_1, and in ds_2 there is a field of the same name
        or a field whose translation is the same string as field_1 or the translation
        of field_1, and vice versa for ds_2 to ds_1.

        :return:: Dict of lists indicating fields that did not match by value
        (incongruencies) of the form
            {pt_id : [{f_1_1:v_1_1, f_2_1:v_2_1}, {f_1_2:v_1_2, f_2_2:v_2_2}]}
            where (field_1,field_2) pairs may not be identical as they may have
            been matched on the basis of their translations and value is the value
            both datasets have for their fields field_1 and field_1.
            (value_1, value_2) are the values of field_1 in ds_1 and field_2
            in ds_2 respectively, and are not equal to each other.


            """
        id_overlap = ds_1.ids.intersection(ds_2.ids)
        out = {}
        for pt in id_overlap:
            pt_list = []

            for f_1_name, f_1_obj in ds_1.field_object_dict.items():

                for f_2_name, f_2_obj in ds_2.field_object_dict.items():

                    if not f_1_obj.equals(f_2_obj):
                        continue

                    v_1 = ds_1.get_value(pt, f_1_name)
                    v_2 = ds_2.get_value(pt, f_2_name)

                    are_equal = False
                    if isinstance(v_1, float) and isinstance(v_2, float):
                        are_equal = isclose(v_1, v_2)
                    else:
                        are_equal = v_1 == v_2

                    if are_equal:
                        pt_list.append({f_1_name: v_1, f_2_name: v_2})

            if len(pt_list) > 0:
                out[pt] = pt_list

        return out

    @property
    def ids(self) -> set[permitted_types]:
        return set(self.patients.keys())

    @property
    def flat(self) -> bool:
        return not self.source.is_longitudinal

    def translations(self) -> dict[str, str]:
        """
        :return: Dict of form {field:translation} . Empty dict if
                no fields have translations.
        """
        out = {}
        for field, field_obj in self._field_obj_dict.items():
            if field_obj.translation is not None:
                out[field] = field_obj.translation

        return out

    def _get_patient(self, patient_id: permitted_types) -> _Patient:
        if not self.has_patient(patient_id):
            raise ValueError(f"_Patient {patient_id} does not exist")

        return self.patients[patient_id]

    def has_patient(self, patient: permitted_types) -> bool:
        """Accepts patient id field values"""
        patient_field_obj = self._get_field_object(self.id_field)
        if not isinstance(patient, patient_field_obj.type):
            raise TypeError(f"Expected type {patient_field_obj.type} for patient_id, got {type(patient)}.")
        else:
            return patient in self.ids

    def get_value(self, patient_id: permitted_types, field: str,
                  visit_policy: VisitPolicy = DEFAULT_VISIT_POLICY) -> permitted_types | None:
        field_obj = self._get_field_object(field)
        return self[patient_id].get_value(field_obj, visit_policy)

    def pop_column(self, field: str, raise_on_missing: bool = True) -> dict[permitted_types, list[permitted_types]]:
        """Removes a _Field for all patients, for all visits.
        All patients must always have all the same fields (square dataset) so
        cannot customize.

        :return: {pt_id: [v_1,v_2,..], pt_id_2:[v....]}. Dict values are lists
            to reflect possibility of many visits
        """
        if not self.has_field(field):
            raise ValueError(f"_Field {field} does not exist in dataset")

        field_object = self._get_field_object(field)

        out = {}
        for _, pt_obj in self.patients.items():
            val_list = []
            for visit in pt_obj.visits:
                val_list.append(pt_obj.get_value(field_object, visit_label=visit))

            pt_obj.remove(field=field_object, visit_labels=pt_obj.visits)

            out[pt_obj.id] = val_list

        del self._field_obj_dict[field]

        return out

    def pop_patient(self, patient_id: permitted_types, raise_on_missing: bool = True) -> list[
        dict[str, permitted_types]]:
        """Remove patient from this dataset, and return the data.

        :return: [{'id':id, 'event'=event1,...}, {'id':id, 'event'=event2,...}]
        """
        if not self.has_patient(patient_id):
            raise ValueError(f"_Patient {patient_id} does not exist.")

        pt_obj = self._get_patient(patient_id)
        out = []
        for visit, data in pt_obj:
            out.append({field.name: value for field, value in data.items()})

        del self.patients[patient_id]

        return out

    def remove(self, delete_patient_when_empty: bool = False, delete_visit_when_empty: bool = False, **kwargs):
        """
        Could maybe more aptly be described as clear_data as it sets values to None
        unless the criteria for actual data structures to be removed from the Dataset
        is met, as specified by the delete_... params and the kwargs params.
        There is no other delete feature here, and so the reason why it often just "clears"
        data is in order to keep the dataset square.

        Structures can be explicitely deleted with remove_row, pop_column,
        and pop_patient.
        :param delete_patient_when_empty:
            Switch to delete the patient from the dataset if they no longer
            have any data after this operation (patient.has_data == False)

        :param delete_visit_when_empty:
            Switch to delete the visit for the patient if it no longer
            has any data after this operation (all values are Null or all
            fields are deleted)

        :param kwargs:
            patient - str or _Patient object
            patients - Iterable[str | _Patient]
            field - str or fields._Field object
            fields - Iterable[str | fields._Field]
            visit - visit label
            visits - Iterable[visit labels]
            raise_on_missing_visits - bool
            raise_on_missing_fields - bool

            Each extra layer of specification: patient -> visit -> field
            restricts the amount of information to be removed.

            For any of the 3 layers of specification, if one of them is omitted,
            then all of the possible elements of that layer will be removed in
            accordance with the other layers.
            For fields or visits, when they are not specified, we will ask
            for all fields or visits respectively to be removed by omitting the
            argument to the _Patient.remove() call. See _Patient.remove() for
            further clarification.

            If only patient(s) is/are specified, the specified patient(s) will be
            completely removed from the dataset.

            If only visit(s) is/are specified, the specified visit(s) will be
            completely removed from the dataset.

            If only field(s) is/are specified, the specified field(s) will be
            completely removed from the dataset.

            If patient(s) and field(s) are specified, the field(s) for the specified
            patient(s) will be set to None.

            If patient(s) and visit(s) are specified, values for each field for the patients
            will be set to None.

            If field(s) and visit(s) are specified, the values for the field(s)
            for the visit(s) will be set to None, for all patients.

            If patient(s), field(s), and visit(s) are specified, the value for
            the patient(s) at each field will be set to None, for the specified visit(s).

            raise_on_missing_visits, raise_on_missing_fields passed directly to
            _Patient.remove().
        :return: None
        """
        allowed_kwargs = {'patient', 'patients', 'field', 'fields', 'visit', 'visits', 'raise_on_missing_visits',
                          'raise_on_missing_fields'}

        if not any(kwarg_field in kwargs.keys() for kwarg_field in
                   ['patient', 'patients', 'field', 'fields', 'visit', 'visits']):
            raise ValueError("Must specify at least one element for patient or field or visit.")

        for kwarg in kwargs:
            if kwarg not in allowed_kwargs:
                raise TypeError(f"Unexpected argument {kwarg!r}")

        # if is False by end of if statements below, will ADD all patients to set
        specified_patients = False

        # will only store _Patient objects
        set_patients: set[_Patient] = set()
        if 'patients' in kwargs:
            specified_patients = True

            for patient in kwargs['patients']:
                if not self.has_patient(patient):
                    raise ValueError(f"Missing patient {patient!r}")

                if isinstance(patient, _Patient):
                    set_patients.add(patient)
                # if is not a _Patient object, must be a patient ID
                else:
                    set_patients.add(self._get_patient(patient))

        if 'patient' in kwargs:
            specified_patients = True
            patient = kwargs['patient']
            if not self.has_patient(patient):
                raise ValueError(f"Missing patient {patient!r} for removal operation")
            else:
                if isinstance(patient, _Patient):
                    set_patients.add(patient)
                else:
                    set_patients.add(self._get_patient(patient))

        # ERROR CHECKING FOR VISITS AND FIELDS WILL HAPPEN ON PATIENT SIDE FOR
        # FUTURE ERROR HANDLING

        # flag is needed in case 'field' or 'fields' was passed but were empty
        specified_fields = False
        # will only hold objects of type _Field, not str (converted in loop below)
        set_fields = set()
        if 'fields' in kwargs:
            specified_fields = True
            for field in kwargs['fields']:
                if isinstance(field, str):
                    set_fields.add(self._get_field_object(field))
                # is of type _Field
                else:
                    set_fields.add(field)

        if 'field' in kwargs:
            specified_fields = True
            field = kwargs['field']
            if not self.has_field(field):
                raise ValueError(f"Missing field {field!r} for removal operation")

            if isinstance(field, str):
                set_fields.add(self._get_field_object(field))  # is of type _Field
            else:
                set_fields.add(field)

        # flag is needed in case 'visit' or 'visits' were passed but were empty
        specified_visits = False
        set_visits = set()
        if 'visits' in kwargs:
            specified_visits = True
            set_visits.update(set(kwargs['visits']))

        if 'visit' in kwargs:
            specified_visits = True
            set_visits.add(kwargs['visit'])

        # only specified patients
        if specified_patients and (not specified_visits and not specified_fields):
            for patient in set_patients:
                del self.patients[patient.id]
            return

        # rest of combinations of fields/visits/patients can be dealt with
        # with this loop
        if not specified_patients:
            set_patients = self._patient_objects

        arguments = {'fields': set_fields, 'visits': set_visits, 'delete_visit_when_empty': delete_visit_when_empty}

        if 'raise_on_missing_visits' in kwargs:
            arguments['raise_on_missing_visits'] = kwargs['raise_on_missing_visits']
        if 'raise_on_missing_fields' in kwargs:
            arguments['raise_on_missing_fields'] = kwargs['raise_on_missing_fields']

        for pt_obj in set_patients:
            pt_obj.remove(**arguments)

            if not pt_obj.has_data and delete_patient_when_empty:
                del self.patients[pt_obj.id]

    def _parse_row(self, row: dict[str, Any], transform: bool = True) -> dict[_Field[Any], permitted_types]:
        """Returns a dict of form {_Field object : value}"""
        if not isinstance(transform, bool):
            raise TypeError(f"Parameter transform should be of type bool, got type {type(transform)}.")
        parsed_row = dict()
        for field, value in row.items():
            field_obj = self._get_or_build_field_object(field)

            if transform:
                parsed_row[field_obj] = field_obj.parse(value)
            # if we can't transform it, need to make sure this is ready to be stored as-is
            else:
                if not field_obj.is_matching_type(value):
                    raise TypeError(f"Value {value} for field {field} is of the incorrect type."
                                    f"Try changing type of value, allowing transform to _parse_row or change the transformation for _Field.transform")
                parsed_row[field_obj] = value

        return parsed_row

    @staticmethod
    def _square_row(row: dict[str, Any], expected_fields: set[str]) -> None:
        """If this row has fields that are missing from the set of all
        fields in this dataset, pad those cells with None (i.e. fill missing
        columns with None)."""
        row_fields = set(row.keys())
        fields_not_in_row = expected_fields - row_fields
        for field in fields_not_in_row:
            row[field] = None

    @staticmethod
    def _validate_field_data(field_data: dict[str, dict[str, Any]]) -> None:
        """Makes sure that all attributes specified in self.field_data
        are attributes that are used to initialize _Field objects (i.e. no extras),
        and that if name attribute is specified, it matches the name that indexes
        the attributes for that field.
        i.e. self.field_data={'height' : {'name':''how tall'} } will throw a RuntimeError."""

        if field_data == dict():
            return

        field_class_attributes = set(inspect.signature(_Field.__init__).parameters.keys()) - {'self'}

        for field_name, field_attributes in field_data.items():

            # ENSURE NO EXTRA ATTRIBUTES IN self.field_data
            extra_attributes = set(field_attributes.keys()).difference(field_class_attributes)
            if extra_attributes != set():
                raise RuntimeError("Attempted to specify field attributes not defined in class _Field:"
                                   f"{extra_attributes}")

            # ENSURE NAME MATCHES SPECIFIED NAME
            if 'name' in field_attributes:
                if field_attributes['name'] != field_name:
                    raise RuntimeError(f"Incongruency between field_data key (name of field) {field_name}"
                                       f"and specified _Field attribute 'name' {field_attributes['name']}")

    def _validate_dataset(self):
        """Post construction/loading quality control"""
        self._check_id_field_present()
        self._check_event_field_present()
        self._check_no_field_translation_overlap()

    def _check_id_field_present(self):
        if self.id_field not in self.raw_fields:
            raise RuntimeError(f"Missing id field: {self.id_field} in dataset raw_fields: {self.raw_fields}")

    def _check_event_field_present(self):
        if not self.flat and self.event_field not in self.raw_fields:
            raise RuntimeError(f"Missing event field: {self.event_field} in dataset raw_fields: {self.raw_fields}")

    def _check_no_field_translation_overlap(self):
        """
        Raise error if a field has a translation that matches the name of another field.
        Will raise an error if two fields have the same translation (how could they be different things)
        Will NOT raise an error if a field's name is the same as it's translation.
        """
        translations = set()
        for f_name, f_obj in self.field_object_dict.items():

            prev_num_translations = len(translations)  # to see if it changes

            if f_obj.translation is None:
                continue

            translations.add(f_obj.translation)

            if len(translations) == prev_num_translations:
                raise RuntimeError(f"2+ fields with translation to {f_obj.translation}")

            # if there is a field whose name is the same as the translation of this field
            if f_obj.translation in self.raw_fields and f_obj.translation != f_obj.name:
                raise RuntimeError(f"Translation of field {f_obj.name} is the "
                                   f"same as existing field's name {f_obj.translation}")

    def _check_all_fields_present(self, expected_fields: set[str]) -> None:
        if self.raw_fields != expected_fields:
            error_msg = ""
            # dataset has fields that are not present in expected fields?
            unexpected_fields = self.raw_fields.difference(expected_fields)
            missing_fields = expected_fields.difference(self.raw_fields)

            if len(unexpected_fields) > 0:
                error_msg = error_msg + f"Unexpected fields present: {unexpected_fields}\n."
            if len(missing_fields) > 0:
                error_msg = error_msg + f"Missing fields: {missing_fields}\n."

            raise RuntimeError(error_msg)

class CsvDataset(Dataset):
    """For all fields not configured in field_data, will assume this is the form and will be coerced into it"""

    def __init__(self, source: Source, field_data: dict[str, dict[str, Any]] | None = None):
        """:param field_data: A dictionary of the form: {"field_name": {"_Field object attribute name":"attribute value"}}.
        """

        super().__init__(source, field_data)

        self._validate_path(path=self.source.path)
        self._load(path=self.source.path)

        self._validate_dataset()

    def _load(self, path) -> None:
        with open(path, mode="r", newline="", encoding="utf-8") as f:

            rows = csv.DictReader(f)

            # if CSV file is empty
            if rows.fieldnames is None:
                return

            if len(set(rows.fieldnames)) != len(rows.fieldnames):
                raise RuntimeError("Duplicate column headers found in csv file")

            for row in rows:
                # more values in this row than headers in this csv, extra values placed
                # into row[None] as restval == None by default for csv.DictReader()
                if None in row:
                    raise RuntimeError(f"Row has more columns than headers: extra values = {row[None]!r}")

                parsed_row: dict[_Field, permitted_types] = self._parse_row(row)
                """Stores {_Field object : parsed_value}"""

                row_id = parsed_row[self._get_field_object(self.id_field)]
                if self.flat:
                    event_label = None
                else:
                    event_label = parsed_row[self._get_field_object(self.event_field)]

                self._in(patient_id=row_id, event_label=event_label, row=parsed_row)

    def _validate_path(self, path) -> None:

        if path is None:
            raise ValueError('Path must be set for .csv sources.'
                             f"Source: {self.source}")

        if path.suffix.lower() != '.csv':
            raise ValueError('Path must be set to a csv for .csv sources.'
                             f"Path is set to: {path}, for source {self.source}")

        if not path.is_file():
            raise ValueError(f'{path} is not a file or does not exist')


class ApiDataset(Dataset):
    # overwrite Dataset flag
    REQUIRE_FIELD_CONFIG = True

    def __init__(self, url, source: Source, method: str, field_data: dict[str, dict[str, Any]] | None = None,
                 unpack_json_data: Callable[[Any], list[dict[str, Any]]] = lambda r: r, **request_kwargs):
        """
        :param field_data: dictionary of the form: {"field_name": {"_Field object attribute name":"attribute value"}}
        :param unpack_json_data: A callable that takes the object returned by response.json()
            after the api call, and unpacks it into a list of dicts, where each
            dict is of the form {field:value}.
            If response.json() returns a list of dicts (i.e. the appropriate format),
            no need to specify it, and unpack_json will default to lambda r:r.

            Example - API already returns a flat list::

                # Response: [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
                unpack_json=lambda r: r

            Example - records nested under a key::

                # Response: {"data": {"records": [{"id": 1}, {"id": 2}]}}
                unpack_json=lambda r: r["data"]["records"]

            Example - dict of records keyed by ID::

                # Response: {"1": {"name": "A"}, "2": {"name": "B"}}
                unpack_json=lambda r: list(r.values())

            Example - single record, not a collection::

                # Response: {"id": 1, "name": "A"}
                unpack_json=lambda r: [r]

        :type unpack_json_data: Callable[[Any], list[dict]]
        :param method: "GET" or "POST" depending on what call is used by this API to fetch data
        :param request_kwargs: Keyword arguments to pass to requests.request"""

        self.url = url
        self.method = method
        self.unpack_json_data = unpack_json_data
        self.request_kwargs = request_kwargs

        super().__init__(source, field_data)
        self._load()

    def _load(self):

        json_data = self._fetch_json_data()

        data = self.unpack_json_data(json_data)
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise RuntimeError(f"API response could not be unpacked into a list of record dicts.\n"
                               f"Got: {data}")
        all_fields = set()
        for row in data:
            all_fields.update(row.keys())
        for row in data:
            self._square_row(row, expected_fields=all_fields)
            parsed_row = self._parse_row(row)
            """Stores {_Field object : parsed_value}"""
            row_id = parsed_row[self._get_or_build_field_object(self.id_field)]

            if self.flat:
                event_label = None
            else:
                event_label = parsed_row[self._get_or_build_field_object(self.event_field)]

            self._in(patient_id=row_id, event_label=event_label, row=parsed_row)

    def _fetch_json_data(self):
        response = requests.request(method=self.method, url=self.url, **self.request_kwargs)
        try:
            result = response.json()
        except ValueError as e:
            raise RuntimeError(f"API did not return valid JSON: {e}") from e
        return result


class BuildDataset(Dataset):
    """Will NOT take _Field objects in initializer as the idea behind this class
        is you build the dataset as you go, so you can transform the fields as you wish
        once you have them in, and you can add translations too."""

    def __init__(self, source: Source, dataset: Dataset | None, field_data: dict[str, dict[str, Any]] | None = None):
        """
            :param source: For the general dataset configurations despite this dataset
                not necessarily being populated from a single source.

            :param dataset: Can pass a dataset to initialize this dataset.
                Will make a deep copy of dataset.patients and assign the copy to self.patients.
                Will make a deep copy of dataset._field_obj_dict and assign it to self._field_obj_dict.
        """
        super().__init__(source=source, field_data=field_data)

        if dataset is not None:
            self._merge_dataset(dataset)

    def _merge_dataset(self, dataset: Dataset):
        """Merge a dataset into this one.
        ONLY to be called upon construction of this instance (i.e. by initializer).
        Requires that all fields that are present in both dataset.raw_fields and
        self.field_data.keys() have the same configurations (yield same _Field
        objects from Dataset._build_field_obj(field_name)
        """
        if not isinstance(dataset, Dataset):
            raise TypeError(f"dataset argument can be only of type Dataset or NoneType, got {type(dataset)} instead.")

        configured_field_overlap = set(self.field_data.keys()).intersection(dataset.raw_fields)
        for field_name in configured_field_overlap:
            if self._get_or_build_field_object(field_name) != dataset._get_or_build_field_object(field_name):
                # use self._build_field_obj() and not self.get_field_object() as the latter will add it to self._field_obj_dict
                # if not already added

                raise RuntimeError("Dataset to be copied into new dataset has different"
                                   f"field configurations for field {field_name}")

        # add the dataset's field objects
        for f_name, f_obj in dataset.field_object_dict.items():
            self._field_obj_dict[f_name] = f_obj.copy()

        # if not an empty dataset
        if dataset.patients != {}:
            for pt_id, pt_obj in dataset:
                # perform a deep copy of the patient using the built in method _Patient.copy()
                self.patients[pt_id] = pt_obj.copy()
