from pathlib import Path
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Source:
    name : str  # name of data source (e.g. Google)
    id_field_name : str  # identify row(s) of data as belonging to one entity
    event_field_name : str | None # differentiate rows with same id_field_name
    is_longitudinal:bool
    path: Path | None # will be ignored if this source is used for an ApiDataset
    empty_values : frozenset[str|None] = frozenset({None})
    """When data is ingested, what forms of data should be concerned empty?
        Data matching these forms will be stored as None in the dataset.
        Any data received as None will be considered empty and stored as None 
        despite None's presence in the frozenset empty_values.
        **This is applied before data parsing."""

    def __post_init__(self):
        if self.path is not None:
            # ensure that downstream all can treat it as a Path object
            object.__setattr__(self, 'path', Path(self.path))

        if self.is_longitudinal:
            if self.event_field_name is None:
                raise ValueError('event_field_name must be set for longitudinal sources')
        else:
            if self.event_field_name is not None:
                raise ValueError('Longitudinal sources should not have an event field')






# per-field flags to decide what value to take from patient if there are many events with data
class VisitPolicy(Enum):
    """For patients that will have many events with many of those events having the same data for a given field, the visit policy of that field determines which event the data will be extracted from.
    Ordering of the events (i.e. what is first and what is last) is determined by ordering of the rows in the dataset."""
    # all raw_fields have REQUIRE_CONSISTENT as default.
    FIRST = "FIRST"
    LATEST = "LATEST"  # grab value from the latest visit that
    REQUIRE_CONSISTENT = "REQUIRE_CONSISTENT"  # across all expected_events, all non-empty values for a given field must agree


DEFAULT_VISIT_POLICY = VisitPolicy.REQUIRE_CONSISTENT
