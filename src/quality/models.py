from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    PASS = 'PASS'
    WARN = 'WARN'
    FAIL = 'FAIL'


@dataclass(frozen=True)
class Result:
    check_name: str
    layer: str
    status: Status
    observed_value: str
    expected_condition: str
    details: str = ''


class QualityError(ValueError):
    def __init__(self, results):
        self.quality_results = results
        super().__init__('Data quality gate failed; inspect persisted check results')
