import csv
from abc import ABC
from pathlib import Path
from typing import Callable, Any

import requests

from . import schema
from .fields import Field, permitted_types
from .source_config import Source, VisitPolicy, DEFAULT_VISIT_POLICY

_OVERWRITE_CSV_FILES = False
"""Flag to overwrite existing .csv files if its path is passed to Dataset.save_as_csv(self,path)"""


class Dataset(ABC):
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
        self.raw_fields = set()
        self.field_data = field_data if field_data is not None else dict()

    def __iter__(self):
        """Returns tuple (patient_id, patient) for all patients"""
        yield from self.patients.items()

    def _build_field_obj_dict(self) -> None:
        """Should only be called by Dataset._setup_field_objects.
        Creates self._field_obj_dict attribute.
        Must be called after self.raw_fields is set.
        Populate self._field_obj_dict for every field in raw_fields —
        using field_data overrides where given, defaulting to a plain
        Field(field_name) otherwise."""

        self._field_obj_dict = dict()

        for field in self.raw_fields:
            # if we did not specify attributes for this field
            if field not in self.field_data:
                if self.REQUIRE_FIELD_CONFIG:
                    raise RuntimeError(f"Field: {field} data is not specified,"
                                       f"and REQUIRED_FIELD_CONFIG = {self.REQUIRE_FIELD_CONFIG}")

                self._field_obj_dict[field] = Field(name=field,
                                                    data_type=self.DEFAULT_DATA_TYPE)
            else:
                self._field_obj_dict[field] = Field(name=field,
                                                    **self.field_data[field])

    def _all_field_data_fields_in_dataset(self) -> None:
        """Should only be called by Dataset._setup_field_objects
        Checking to see that there were no fields passed in field_data that do not exist in the raw_fields"""
        fields_from_field_data = set(self.field_data.keys())

        if fields_from_field_data.intersection(
                self.raw_fields) != fields_from_field_data:
            # fields specified in field_data that were not found in raw_fields
            not_in_raw_fields = fields_from_field_data.difference(
                self.raw_fields)
            raise ValueError(
                f"Fields {not_in_raw_fields} passed in field_data argument are not present in raw_fields: {self.raw_fields}")

    """Cannot be called before: self.field_data is initialized and self.raw_fields is filled"""

    def _setup_field_objects(self):
        if not self.raw_fields:
            raise RuntimeError(
                "Raw fields must be set before _field_obj_dict can be built")

        # collect translations as we iterate over self.field_data
        translations = set()

        # make sure none of the translations configured are pre-existing fields
        for configured_field, configured_field_attributes in self.field_data.items():
            if not any(
                    attribute.strip().lower() == 'translation' for attribute in
                    configured_field_attributes):
                continue

            translation = configured_field_attributes['translation']

            if translation in self.raw_fields:
                raise RuntimeError(
                    f"Translation '{translation}' of field '{configured_field}'"
                    f"is a pre-existing field")

            # is there another field that has the same translation?
            if translation in translations:
                raise RuntimeError(f"2+ fields translated to {translation}")

            translations.add(translation)

        # ensure there are no fields in self.field_data that do not exist in raw fields
        self._all_field_data_fields_in_dataset()

        # populate self._field_obj_dict
        self._build_field_obj_dict()

    def save_as_csv(self, path: Path) -> None:
        """Save the dataset as a csv"""

        if path.exists():
            if not _OVERWRITE_CSV_FILES:
                raise FileExistsError(f"{path} already exists")
            if path.is_dir():
                raise ValueError(f"{path} is a directory")

        if path.suffix != '.csv':
            raise ValueError("File extension must be .csv")

        with open(path, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=self.raw_fields)
            writer.writeheader()

            for patient_id, patient_obj in self.patients.items():
                for visit_label in patient_obj.visit_order:
                    writer.writerow(patient_obj.visits[visit_label])

    @property
    def id_field(self):
        return self.source.id_field_name

    @property
    def event_field(self):
        return self.source.event_field_name

    def add_row(self, patient_id, event_label, row):
        if patient_id not in self.patients:
            self.patients[patient_id] = schema.Patient(patient_id, self.source)
        self.patients[patient_id].load_visit_data(row=row,
                                                  visit_label=event_label)

    @staticmethod
    def match_by_field(ds_1: "Dataset", ds_2: "Dataset", field_name_1: str,
                       field_name_2: str) -> list[tuple[str, str]]:
        """:return: list of tuples (id_dataset1, id_dataset2) for patients that matched by field."""

        if not isinstance(ds_1, Dataset):
            raise TypeError("Expected type 'Dataset' for parameter ds_1."
                            f"Got {type(ds_1)}")
        if not isinstance(ds_2, Dataset):
            raise TypeError("Expected type 'Dataset' for parameter ds_2."
                            f"Got {type(ds_2)}")
        if not isinstance(field_name_1, str):
            raise TypeError("Expected type 'str' for parameter field_name_1."
                            f"Got {type(field_name_1)}")
        if not isinstance(field_name_2, str):
            raise TypeError("Expected type 'str' for parameter field_name_2."
                            f"Got {type(field_name_2)}")

        if not field_name_1 in ds_1.raw_fields:
            raise ValueError(
                f"Field {field_name_1!r} is not in {ds_1}.raw_fields")
        if not field_name_2 in ds_2.raw_fields:
            raise ValueError(
                f"Field {field_name_2!r} is not in {ds_2}.raw_fields")

        out = list()
        patients_1 = ds_1.patients.copy()
        patients_2 = ds_2.patients.copy()

        for id_1 in patients_1:
            val_1 = ds_1.get_value(id_1, field_name_1)

            for id_2 in patients_2:
                val_2 = ds_2.get_value(id_2, field_name_2)
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

        fields_only_in_1 = raw_fields_1.difference(overlapping_raw_fields)
        fields_only_in_2 = raw_fields_2.difference(overlapping_raw_fields)

        fields_to_compare = {(x, x) for x in overlapping_raw_fields}
        """Of form (field_in_ds_1,field_in_ds_2) as these fields are
        deemed equivalent on the basis of their names or translations"""

        translations_1 = ds_1.translations()
        translations_2 = ds_2.translations()

        for t_1, f_1 in translations_1.items():

            # if field was part of overlapping fields (already accounted for)
            if f_1 not in fields_only_in_1:
                continue

            for t_2, f_2 in translations_2.items():
                # if field was part of overlapping fields (already accounted for)
                if f_2 not in fields_only_in_2:
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
        return set(self.patients)

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

    def get_value(self, patient_id: str, field: str,
                  visit_policy: VisitPolicy = DEFAULT_VISIT_POLICY) -> str | None:

        return self.get_patient(patient_id).get_value(field, visit_policy)

    def _parse_row(self, row):
        parsed_row = dict()
        for field, value in row.items():
            field_obj = self._field_obj_dict[field]
            parsed_row[field] = self.parse_value(self.source, field_obj, value)

        return parsed_row

    def _square_row(self, row):
        row_fields = set(row.keys())
        fields_not_in_row = self.raw_fields - row_fields
        for field in fields_not_in_row:
            row[field] = None


class CsvDataset(Dataset):
    """For all fields not configured in field_data, will assume this is the form and will be coerced into it"""

    def __init__(self, source: schema.Source,
                 field_data: dict[str, dict[
                     str, Any]] | None = None):
        """:param field_data: A dictionary of the form: {"field_name": {"Field object attribute name":"attribute value"}}"""

        super().__init__(source, field_data)

        self.validate_path(path=self.source.path)
        self._load(path=self.source.path)

    def _load(self, path):
        with open(path, mode="r", newline="", encoding="utf-8-sig") as f:

            rows = csv.DictReader(f)
            self.raw_fields = set(rows.fieldnames)
            self._setup_field_objects()

            if len(self.raw_fields) != len(rows.fieldnames):
                raise RuntimeError(
                    "Duplicate column headers found in csv file")

            if self.id_field not in self.raw_fields:
                raise RuntimeError(
                    f"Missing id field: {self.id_field} in dataset raw_fields: {self.raw_fields}")

            if not self.flat and self.event_field not in self.raw_fields:
                raise RuntimeError(
                    f"Missing event field: {self.event_field} in dataset raw_fields: {self.raw_fields}")

            for row in rows:
                parsed_row = self._parse_row(row)
                """Stores {field name (string) : parsed_value}"""

                row_id = parsed_row[self.id_field]
                event_label = None if self.flat else parsed_row[
                    self.event_field]

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
    # overwrite dataset flag
    REQUIRE_FIELD_CONFIG = True

    # TODO Not really sure how to make this generalizable to different APIs. Maybe set this as an abstract class and leave it to client implementation on a per API basis? Also some APIs have an error_key? not sure what to do with that...
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

        self.raw_fields = set()
        for row in data:
            self.raw_fields.update(set(row.keys()))

        self._setup_field_objects()

        if self.id_field not in self.raw_fields:
            raise ValueError(
                f"Missing id field: {self.id_field} in dataset raw_fields: {self.raw_fields}")
        if not self.flat and self.event_field not in self.raw_fields:
            raise RuntimeError(
                f"Dataset is not flat, but {self.event_field} not found in dataset raw_fields")

        for row in data:
            self._square_row(row)  # if API data skips empty fields in a row
            parsed_row = self._parse_row(row)
            """Stores {field name (string) : parsed_value}"""

            row_id = parsed_row[self.id_field]
            event_label = None if self.flat else parsed_row[self.event_field]

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
