from typing import Any

from .source_config import Source, VisitPolicy


class Patient:
    _id: Any
    _source: Source
    visits: dict[
        str | None, dict]  # event name (none if no event labels) : data (data --> {field name : value} )

    # unexpected visit labels (not passed to __init__ in argument expected_events will be appended to end of list self.visits
    def __init__(self, pt_id: str, source: Source):
        self._id = pt_id
        self._source = source
        self.visits = {}
        self._visit_order = []  # order = order of addition to self.visits

    def __iter__(self):
        """Returns tuple (visit label [str], visit data [dict])"""
        yield from self.visits.items()

    # make id read-only by not defining setter
    @property
    def id(self):
        return self._id

    @property
    def visit_order(self):
        return self._visit_order

    # make source read-only by not defining setter
    @property
    def source(self):
        return self._source

    def load_visit_data(self, row: dict[str:Any], visit_label: str | None):
        if not row:
            raise ValueError(f"Empty row for patient {self.id}")

        if visit_label in self.visit_order:
            raise RuntimeError(
                f"Visit {visit_label} already loaded for patient {self.id}")

        self.visits[visit_label] = row
        self.visit_order.append(visit_label)

    def get_visit_data(self, visit_label: str | None) -> dict:
        try:
            return self.visits[visit_label]
        except KeyError:
            raise ValueError(
                f"Visit label {visit_label} does not exists for patient {self.id}")

    def get_value(self, field: str,
                  visit_policy: VisitPolicy) -> str | None:
        """
        :param field: The field for which we are grabbing the value
        :param visit_policy: Determines which non-None value is returned
        If no value is passed, will first try and find the policy for this field in config.FIELD_VISIT_POLICY, if it does not exist there, will use config.DEFAULT_VISIT_POLICY. Pass a VisitPolicy to override the policy for the field set in config.FIELD_VISIT_POLICY or config.DEFAULT_VISIT_POLICY

        :return:: None if and only if None is the value for this field across all visits. Else, according to VisitPolicy.
        """

        if len(self.visits) == 0:
            raise RuntimeError(f"Patient {self.id} has no visits")

        if not isinstance(field, str):
            raise TypeError("field arg. should be a string")

        if field not in self.visits[self.visit_order[0]].keys():
            raise ValueError(
                f"Field {field!r} does not exist for patient {self.id}")

        if visit_policy is None:
            raise ValueError(f"Visit policy is None for patient {self.id}")

        found_value = None

        for visit_label, visit_data in self.visits.items():

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
                        f"for patient {self.id}, from source named {self.source.name}")

            elif visit_policy == VisitPolicy.FIRST:
                found_value = tmp_value
                break

            elif visit_policy == VisitPolicy.LATEST:
                found_value = tmp_value
                continue

        return found_value
