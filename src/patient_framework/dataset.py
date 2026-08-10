import csv
from abc import ABC
from pathlib import Path
from typing import Callable, Any
import json

import requests
import datetime
import inspect

from . import schema
from .fields import Field, permitted_types
from .source_config import Source, VisitPolicy, DEFAULT_VISIT_POLICY
import copy

_OVERWRITE_CSV_FILES = False
_OVERWRITE_JSON_FILES = False
"""Flag to overwrite existing .csv files if its path is passed to Dataset.save_as_csv(self,path)"""


class Dataset(ABC):
    """ALL PATIENTS WILL ALWAYS HAVE ALL THE SAME FIELDS.
    NOT ALL PATIENTS WILL NECESSARILY HAVE ALL THE SAME VISITS"""

    REQUIRE_FIELD_CONFIG = False
    """Does field_data need to be passed and does it need to configure every field
    found in the dataset?"""
    DEFAULT_DATA_TYPE = str
    """Default data type filled into Dataset._field_obj_dict's Field objects when
    that field is not configured in self.field_data.
    Irrelevant if REQUIRE_FIELD_CONFIG == True
    """

    def __init__(self, source: Source, field_data: dict[str, dict[
        str, Any]] | None):
        self.source = source
        self.patients = {}
        """Dictionary holding all patients of dataset.
            Form: {patient_id : schema.Patient object}"""

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

        self._field_obj_dict = dict()
        """Initialized gradually as self.get_field_object() is called.
        Can ONLY be modified by self.get_field_object()"""

    def __getitem__(self, patient_id)->schema.Patient:
        if patient_id not in self.ids:
            raise KeyError(f"Patient {patient_id} does not exist")
        return self.patients[patient_id]

    def __setitem__(self, _):
        #TODO non-technical error messsage
        raise RuntimeError("Cannot modify Dataset this way")

    def __iter__(self):
        """Returns tuple (patient_id, patient) for all patients"""
        yield from self.patients.items()

    def _build_field_obj(self, field_name:str) -> Field:
        """Does NOT modify any internal structures - only returns the Field object
        specified by self.field_data.

        Creates a field object for a given field_name string.

            If there is no entry field_name in self.field_data,
            it will create a default Field object Field(field_name)."""
        if not isinstance(field_name,str):
            raise TypeError("field_name must be a string")

        if field_name not in self.field_data:
            if self.REQUIRE_FIELD_CONFIG:
                raise RuntimeError("Not all fields in dataset are configured via field_data argument."
                                   f"REQUIRE_FIELD_CONFIG == {self.REQUIRE_FIELD_CONFIG}")

            return Field(field_name, data_type = self.DEFAULT_DATA_TYPE)
        else:
            if 'name' in self.field_data[field_name].keys():
                return Field(**self.field_data[field_name])
            else:
                return Field(name=field_name, **self.field_data[field_name])

    def get_field_object(self, field:str|Field):
        if isinstance(field,Field):
            return field

        """The ONLY method allowed to modify self._field_obj_dict"""
        if field not in self.field_obj_dict:
            self.field_obj_dict[field]=self._build_field_obj(field)

        return self.field_obj_dict[field]

    def get_patient_object(self, patient):
        """
        :param patient: Two valid arguments - the patient ID, or the patient
            object itself that is being requested."""
        if isinstance(patient, schema.Patient):
            return patient
        else:
            if patient not in self.ids:
                raise ValueError(f"Could not find patient {patient!r}")

            return self.patients[patient]


    def save_as_csv(self, path: Path, append_date_time:bool = True) -> None:
        """Save the dataset as a csv.
        :param append_date_time: Boolean value indicating whether or not the
            method will append the date and time to the path (before the
            suffix .csv).
            e.g. path = "mycsv.csv", append_date_time==True
            File will be saved to mycsv_2026_6_30-14:15.csv
        """

        if path.exists():
            if not _OVERWRITE_CSV_FILES:
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
                for visit_label in patient_obj.visits:
                    writer.writerow(patient_obj.data[visit_label])

    def save_as_json(self, path:Path|None, append_date_time:bool=True)->str:
        """Converts data to JSON format. If path is not None, will save the data
        there and return the JSON string. If path is None, will only return the string.

        Will be of a list of dicts of the form:
        [{id_field:pt_id,event_field:event,dob_field:birthday,...}, {id_field:pt_id,event_field:event_2,...},
        {id_field:pt_id_2:event_field:event,...}, ... ]"""

        if path is not None:
            if path.exists():
                if not _OVERWRITE_JSON_FILES:
                    raise FileExistsError(f"{path} already exists")
            if path.is_dir():
                raise ValueError(f"{path} is a directory")
            if path.suffix != '.json':
                raise ValueError("File extension must be .json")

            if append_date_time:
                date_time = datetime.datetime.now()
                path = path.with_name(f"{path.stem}_{date_time.strftime('%Y_%m_%d_%H-%M')}.json")

        data = []
        for _, pt_obj in self.patients.items():
            for __, visit_data in pt_obj:
                tmp_dict = {f_obj.name:f_obj.serialize(value) for f_obj,value in visit_data.items()}
                data.append(tmp_dict)

        json_string = json.dumps(data)
        if path is not None:
            with open(file=path, mode='w') as f:
                f.write(json_string)

        return json_string

    @property
    def id_field(self):
        return self.source.id_field_name

    @property
    def raw_fields(self):
        return set(self._field_obj_dict.keys())

    @property
    def field_objects(self):
        return self._field_obj_dict.values()

    def has_field(self,field:Field|str)->bool:
        if isinstance(field,str):
            return field in self.raw_fields
        elif isinstance(field,Field):
            return field in self.field_objects
        else:
            raise TypeError(f"Expected type str or Field for argument field, got {type(field)} instead")

    @property
    def event_field(self):
        return self.source.event_field_name

    @property
    def field_obj_dict(self):
        return self._field_obj_dict

    def add_row(self, patient_id, event_label, row):
        if patient_id not in self.patients:
            self.patients[patient_id] = schema.Patient(patient_id)
        self.patients[patient_id].add_visit(data=row, visit_label=event_label)

    @staticmethod
    def match_by_field(ds_1: "Dataset", ds_2: "Dataset", field_1: str | Field,
                       field_2: str | Field) -> list[tuple[str, str]]:
        """:return: list of tuples (id_dataset1, id_dataset2) for patients that matched by field."""

        if isinstance(field_1, Field):
            field_1 = field_1.name
        if isinstance(field_2, Field):
            field_2 = field_2.name

        if not isinstance(ds_1, Dataset):
            raise TypeError("Expected type 'Dataset' for parameter ds_1."
                            f"Got {type(ds_1)}")
        if not isinstance(ds_2, Dataset):
            raise TypeError("Expected type 'Dataset' for parameter ds_2."
                            f"Got {type(ds_2)}")
        if not isinstance(field_1, str):
            raise TypeError("Expected type 'str' for parameter field_name_1."
                            f"Got {type(field_1)}")
        if not isinstance(field_2, str):
            raise TypeError("Expected type 'str' for parameter field_name_2."
                            f"Got {type(field_2)}")

        if not field_1 in ds_1.raw_fields:
            raise ValueError(
                f"Field {field_1!r} is not in {ds_1}.raw_fields")
        if not field_2 in ds_2.raw_fields:
            raise ValueError(
                f"Field {field_2!r} is not in {ds_2}.raw_fields")

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
    def parse_value(source: Source, field_obj: Field,
                    value: permitted_types) -> Any:
        """Called during data loading into Dataset object.
        If value is considered empty as indicated in source.empty_values, it will
        be converted to None before parsing.
        Any value of None will remain None
        If value is a string, will first strip leading+trailing whitespace from
        string and then apply relevant transformation.
        If is a non-string, will apply relevant transformation immediately.
        Transformation is applied by calling parse(value) on field_obj
        """
        if not isinstance(source, Source):
            raise TypeError("Expected type Source for source argument")
        if not isinstance(field_obj, Field):
            raise TypeError("Expected type Field for field_obj argument")

        if isinstance(value, str):
            # strip leading + trailing whitespaces
            value = value.strip()

        if value in source.empty_values:
            value = None

        return field_obj.parse(value)

    @staticmethod
    def difference(ds_1: "Dataset", ds_2: "Dataset", ):
        """Takes two datasets where it is assumed identical patient IDs means
        identical patients and compares all fields that can be compared on the
        basis of field names, and field name translations.
        e.g. if field_1 is in ds_1, and in ds_2 there is a field of the same name
        or a field whose translation is the same string as field_1 or the translation
        of field_1, and vice versa for ds_2 to ds_1.

        :return:: List of dicts indicating fields that did not match by value
        (incongruencies) of the form
            [{pt_id : { ( (field_1, field_2) , (value_1, value_2) ), ...}]
            where (field_1,field_2) pairs may not be identical as they may have
            been matched on the basis of their translations and value is the value
            both datasets have for their fields field_1 and field_1.
            (value_1, value_2) are the values of field_1 in ds_1 and field_2
            in ds_2 respectively, and are not equal to each other.
            """

        raw_fields_1 = ds_1.raw_fields.copy()
        raw_fields_2 = ds_2.raw_fields.copy()
        overlapping_raw_fields = raw_fields_1.intersection(raw_fields_2)

        fields_to_compare = {(x, x) for x in overlapping_raw_fields}
        """Of form (field_in_ds_1,field_in_ds_2) as these fields are
        deemed equivalent on the basis of their names or translations"""

        translations_1 = ds_1.translations()
        translations_2 = ds_2.translations()

        for f_1, t_1 in translations_1.items():

            # if field was part of overlapping fields (already accounted for)
            if f_1 in overlapping_raw_fields:
                continue

            for f_2, t_2 in translations_2.items():
                # if field was part of overlapping fields (already accounted for)
                if f_2 in overlapping_raw_fields:
                    continue

                if t_1 == t_2 or f_1 == t_2 or t_1 == f_2:
                    fields_to_compare.add((f_1, f_2))

        out = []
        id_overlap = ds_1.ids.intersection(ds_2.ids)
        for pt_id in id_overlap:
            pt_set = set()
            for f_1, f_2 in fields_to_compare:
                v_1 = ds_1.get_value(pt_id, f_1)
                v_2 = ds_2.get_value(pt_id, f_2)

                if v_1 != v_2:
                    pt_set.add(((f_1, f_2), (v_1, v_2)))

            if not len(pt_set) == 0:
                out.append({pt_id: pt_set})

        return out

    @property
    def ids(self) -> set[str]:
        return set(self.patients.keys())

    @property
    def flat(self) -> bool:
        return not self.source.is_longitudinal

    def translations(self):
        """
        :return: Dict of form {field:translation} . Empty dict if
                no fields have translations.
        """
        out = {}
        for field, field_obj in self._field_obj_dict.items():
            if field_obj.translation is not None:
                out[field] = field_obj.translation

        return out

    def get_patient(self, patient_id: str):
        if patient_id not in self.patients:
            raise ValueError(f"Patient {patient_id} does not exist")

        return self.patients[patient_id]

    def has_patient(self,patient):
        """Accepts schema.Patient objects or patient id field values"""
        if isinstance(patient, schema.Patient):
            return patient in self.patients.values()
        else:
            return patient in self.ids

    def get_value(self, patient_id: str, field: str|Field,
                  visit_policy: VisitPolicy = DEFAULT_VISIT_POLICY) -> str | None:
        if isinstance(field, str):
            field = self.get_field_object(field)
        return self[patient_id].get_value(field, visit_policy)

    def add_column(self, field:str, default_value=None, transform:bool=True,**field_attributes)->None:
        """
        :param default_value: default value to be added to each row for this column.
        :param transform: will the transformation stored in the generated Field object
            be applied to the default_value for all rows? (i.e. the transformation
            specified in field_attributes, if not specified then the default transformation
            specified in the Field class).
        :param field: Field name - will raise error if already part of dataset.
        :param field_attributes: Of form {'name':field_name, 'data_type':field_type,...}
            for any or all of the arguments used to initialize an instance of the Field class
        :return: None
        """
        # make sure field_data is formatted correctly
        self._validate_field_data({field:field_attributes})

        # some of the attributes were specified, so add it to our dict of field data
        if field_attributes != dict():
            self.field_data[field] = field_attributes

        # get field object
        field_object = self.get_field_object(field)

        for _, pt_obj in self:
            pt_obj.add_field(field_object, default_value, transform)

    def remove_field(self, field:Field):
        """Removes a Field for all patients, for all visits.
        All patients must always have all the same fields (square dataset) so
        cannot customize."""

    def remove_patient(self, patient_id):
        """Remove patient from this dataset"""
        pass

    def remove(self,delete_patient_when_empty:bool=True,
               delete_visit_when_empty:bool=True,
               delete_field_when_empty:bool=True, **kwargs):
        """
        :param delete_patient_when_empty:
            Switch to delete the patient from the dataset if they no longer
            have any data after this operation (patient.has_data == False)

        :param delete_visit_when_empty:
            Switch to delete the visit for the patient if it no longer
            has any data after this operation (all values are Null or all
            fields are deleted)
        :param delete_field_when_empty:
            Switch to delete the field for all patients if no patient has a value
            for this field, across all their visits.

        :param kwargs:
            patient - str or schema.Patient object
            patients - Iterable[str | schema.Patient]
            field - str or fields.Field object
            fields - Iterable[str | fields.Field]
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
            argument to the Patient.remove() call. See Patient.remove() for
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
            Patient.remove().
        :return: None
        """
        allowed_kwargs = {'patient', 'patients', 'field','fields','visit','visits','raise_on_missing_visits','raise_on_missing_fields'}

        for kwarg in kwargs:
            if kwarg not in allowed_kwargs:
                raise TypeError(f"Unexpected argument {kwarg!r}")

        # if is False by end of if statements below, will ADD all patients to set
        specified_patients=False

        # will only store schema.Patient objects
        set_patients=set()
        if 'patients' in kwargs:
            specified_patients=True

            for patient in kwargs['patients']:
                if not self.has_patient(patient):
                    raise ValueError(f"Missing patient {patient!r}")

                if isinstance(patient,schema.Patient):
                    set_patients.add(patient)
                # if is not a schema.Patient object, must be a patient ID
                else:
                    set_patients.add(self.get_patient_object(patient))

        if 'patient' in kwargs:
            specified_patients=True
            patient = kwargs['patient']
            if not self.has_patient(patient):
                raise ValueError(f"Missing patient {patient!r} for removal operation")
            else:
                if isinstance(patient, schema.Patient):
                    set_patients.add(patient)
                else:
                    set_patients.add(self.get_patient_object(patient))

        if not specified_patients:
            set_patients = self.ids

        # ERROR CHECKING FOR VISITS AND FIELDS WILL HAPPEN ON PATIENT SIDE FOR
            # FUTURE ERROR HANDLING

        # flag is needed in case 'field' or 'fields' was passed but were empty
        specified_fields = False
        # will only hold objects of type Field, not str (converted in loop below)
        set_fields=set()
        if 'fields' in kwargs:
            specified_fields = True
            for field in kwargs['fields']:
                if isinstance(field,str):
                    set_fields.add(self.get_field_object(field))
                # is of type Field
                else:
                    set_fields.add(field)
        if 'field' in kwargs:
            specified_fields = True
            field = kwargs['field']
            if not self.has_field(field):
                raise ValueError(f"Missing field {field!r} for removal operation")

            if isinstance(field,str):
                set_fields.add(self.get_field_object(field))
                # is of type Field
            else:
                set_fields.add(field)

        # flag is needed in case 'visit' or 'visits' were passed but were empty
        specified_visits = False
        set_visits=set()
        if 'visits' in kwargs:
            specified_visits=True
            set_visits.update(set(kwargs['visits']))
        if 'visit' in kwargs:
            specified_visits=True
            set_visits.add(kwargs['visit'])

        for patient_id in set_patients:
            arguments={'fields':set_fields,
                       'visits':set_visits}





    def _parse_row(self, row):
        """Returns list of dicts, each dict of form {Field object : value}"""
        parsed_row = dict()
        for field, value in row.items():
            field_obj = self.get_field_object(field)
            parsed_row[field_obj] = self.parse_value(self.source, field_obj, value)

        return parsed_row

    @staticmethod
    def _square_row(row:dict[str,Any], expected_fields:set[str]):
        """If this row has fields that are missing from the set of all
        fields in this dataset, pad those cells with None (i.e. fill missing
        columns with None)."""
        row_fields = set(row.keys())
        fields_not_in_row = expected_fields - row_fields
        for field in fields_not_in_row:
            row[field] = None

    @staticmethod
    def _validate_field_data(field_data:dict[str,dict[str,Any]])->None:
        """Makes sure that all attributes specified in self.field_data
        are attributes that are used to initialize Field objects (i.e. no extras),
        and that if name attribute is specified, it matches the name that indexes
        the attributes for that field.
        i.e. self.field_data={'height' : {'name':''how tall'} } will throw a RuntimeError."""

        if field_data==dict():
            return

        field_class_attributes = set(inspect.signature(Field.__init__).parameters.keys()) - {'self'}

        for field_name, field_attributes in field_data.items():

            # ENSURE NO EXTRA ATTRIBUTES IN self.field_data
            extra_attributes = set(field_attributes.keys()).difference(field_class_attributes)
            if extra_attributes != set():
                raise RuntimeError("Attempted to specify field attributes not defined in class Field:"
                                   f"{extra_attributes}")

            # ENSURE NAME MATCHES SPECIFIED NAME
            if 'name' in field_attributes:
                if field_attributes['name'] != field_name:
                    raise RuntimeError(f"Incongruency between field_data key (name of field) {field_name}"
                                       f"and specified Field attribute 'name' {field_attributes['name']}")

    def validate_dataset(self):
        """Post construction/loading quality control"""
        self._check_id_field_present()
        self._check_event_field_present()
        self._check_no_field_translation_overlap()

    def _check_id_field_present(self):
        if self.id_field not in self.raw_fields:
            raise RuntimeError(
                f"Missing id field: {self.id_field} in dataset raw_fields: {self.raw_fields}")

    def _check_event_field_present(self):
        if not self.flat and self.event_field not in self.raw_fields:
            raise RuntimeError(
                f"Missing event field: {self.event_field} in dataset raw_fields: {self.raw_fields}")

    def _check_no_field_translation_overlap(self):
        """
        Raise error if a field has a translation that matches the name of another field.
        Will raise an error if two fields have the same translation (how could they be different things)
        Will NOT raise an error if a field's name is the same as it's translation.
        """
        translations=set()
        for f_name, f_obj in self.field_obj_dict.items():

            prev_num_translations=len(translations) # to see if it changes

            if f_obj.translation is None:
                continue

            translations.add(f_obj.translation)

            if len(translations) == prev_num_translations:
                raise RuntimeError(f"2+ fields with translation to {f_obj.translation}")

            # if there is a field whose name is the same as the translation of this field
            if f_obj.translation in self.raw_fields and f_obj.translation != f_obj.name:
                raise RuntimeError(f"Translation of field {f_obj.name} is the "
                                   f"same as existing field's name {f_obj.translation}")

    def _check_all_fields_present(self, expected_fields:set[str]):
        if self.raw_fields != expected_fields:
            error_msg=""
            # dataset has fields that are not present in expected fields?
            unexpected_fields = self.raw_fields.difference(expected_fields)
            missing_fields = expected_fields.difference(self.raw_fields)

            if len(unexpected_fields) > 0:
                error_msg = error_msg+f"Unexpected fields present: {unexpected_fields}\n."
            if len(missing_fields) > 0:
                error_msg = error_msg+f"Missing fields: {missing_fields}\n."

            raise RuntimeError(error_msg)



class CsvDataset(Dataset):
    """For all fields not configured in field_data, will assume this is the form and will be coerced into it"""

    def __init__(self, source:Source,
                 field_data: dict[str, dict[
                     str, Any]] | None = None):
        """:param field_data: A dictionary of the form: {"field_name": {"Field object attribute name":"attribute value"}}.
        """

        super().__init__(source, field_data)

        self.validate_path(path=self.source.path)
        self._load(path=self.source.path)

    def _load(self, path):
        with open(path, mode="r", newline="", encoding="utf-8") as f:

            rows = csv.DictReader(f)

            if len(self.raw_fields) != len(rows.fieldnames):
                raise RuntimeError(
                    "Duplicate column headers found in csv file")

            for row in rows:
                # more values in this row than headers in this csv, extra values placed
                # into row[None] as restval == None by default for csv.DictReader()
                if None in row:
                    raise RuntimeError(f"Row has more columns than headers: extra values = {row[None]!r}")

                parsed_row = self._parse_row(row)
                """Stores {Field object : parsed_value}"""

                row_id = parsed_row[self.get_field_object(self.id_field)]
                event_label = None if self.flat else parsed_row[
                    self.get_field_object(self.event_field)]

                self.add_row(patient_id=row_id, event_label=event_label,
                             row=parsed_row)

    def validate_path(self, path):

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

    def __init__(self, url, source: Source, method: str,
                 field_data: dict[str, dict[
                     str, Any]] | None = None,
                 unpack_json: Callable = lambda r: r, **request_kwargs):
        """
        :param field_data: dictionary of the form: {"field_name": {"Field object attribute name":"attribute value"}}
        :param unpack_json: A callable that takes the object returned by response.json()
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

        :type unpack_json: Callable[[Any], list[dict]]
        :param method: "GET" or "POST" depending on what call is used by this API to fetch data
        :param request_kwargs: Keyword arguments to pass to requests.request"""

        self.url = url
        self.method = method
        self.unpack_json = unpack_json
        self.request_kwargs = request_kwargs

        super().__init__(source, field_data)
        self._load()

    def _load(self):

        json_data = self._fetch_json()

        data = self.unpack_json(json_data)
        if not isinstance(data, list) or not all(
                isinstance(row, dict) for row in data):
            raise RuntimeError(
                f"API response could not be unpacked into a list of record dicts.\n"
                f"Got: {data}"
            )
        all_fields = set()
        for row in data:
            all_fields.update(row.keys())
        for row in data:
            self._square_row(row, expected_fields=all_fields)
            parsed_row = self._parse_row(row)
            """Stores {Field object : parsed_value}"""

            row_id = parsed_row[self.get_field_object(self.id_field)]
            event_label = None if self.flat else parsed_row[self.get_field_object(self.event_field)]

            self.add_row(patient_id=row_id, event_label=event_label,
                         row=parsed_row)

    def _fetch_json(self):
        response = requests.request(method=self.method, url=self.url,
                                    **self.request_kwargs)
        try:
            result = response.json()
        except ValueError as e:
            raise RuntimeError(f"API did not return valid JSON: {e}") from e
        return result


class BuildDataset(Dataset):
    """Will NOT take Field objects in initializer as the idea behind this class
        is you build the dataset as you go, so you can transform the fields as you wish
        once you have them in, and you can add translations too."""
    def __init__(self, source:Source, dataset:Dataset|None, field_data : dict[str,dict[str,Any]] | None=None):
        """
            :param source: For the general dataset configurations despite this dataset
                not necessarily being populated from a single source.

            :param dataset: Can pass a dataset to initialize this dataset.
                Will make a deep copy of dataset.patients and assign the copy to self.patients.
                Will make a deep copy of dataset._field_obj_dict and assign it to self._field_obj_dict.
        """
        super().__init__(source=source,field_data=field_data)

        if dataset is not None:
            self._merge_dataset(dataset)

    def _merge_dataset(self,dataset:Dataset):
        """Merge a dataset into this one.
        ONLY to be called upon construction of this instance (i.e. by initializer).
        Requires that all fields that are present in both dataset.raw_fields and
        self.field_data.keys() have the same configurations (yield same Field
        objects from Dataset._build_field_obj(field_name)
        """
        if not isinstance(dataset, Dataset):
            raise TypeError(f"dataset argument can be only of type Dataset or NoneType, got {type(dataset)} instead.")

        configured_field_overlap = set(self.field_data.keys()).intersection(dataset.raw_fields)
        for field_name in configured_field_overlap:
            if self._build_field_obj(field_name) != dataset._build_field_obj(field_name):
                # use self._build_field_obj() and not self.get_field_object() as the latter will add it to self._field_obj_dict
                # if not already added

                raise RuntimeError("Dataset to be copied into new dataset has different"
                                   f"field configurations for field {field_name}")

        # add the dataset's field objects
        for f_name, f_obj in dataset.field_obj_dict.items():
            self._field_obj_dict[f_name]=f_obj.copy()

        # if not an empty dataset
        if dataset.patients != {}:
            for pt_id, pt_obj in dataset:
                # perform a deep copy of the patient using the built in method Patient.copy()
                self.patients[pt_id] = pt_obj.copy()


