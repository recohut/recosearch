from __future__ import annotations

from dataclasses import dataclass


class BoundaryError(ValueError):
    """Raised when a request crosses the declared source/semantic boundary."""


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class ContractIssue:
    """A single structured finding from contract/source validation.

    ``code`` is a stable, scenario-agnostic identifier (e.g. ``unknown_section``).
    ``severity`` is ``error`` (blocks governed execution / explicit gates) or
    ``warning`` (surfaced but non-blocking). ``location`` points at the declared
    input that produced it (e.g. ``semantic.md:metrics`` or
    ``source_config.yaml:<source_id>``).
    """

    code: str
    severity: str
    location: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "location": self.location,
            "message": self.message,
        }


class ContractValidationError(BoundaryError):
    """Raised at explicit entry points when error-severity issues are present.

    Never raised on the hot compile path; only at ``--validate``, strict boot,
    and other explicit gates. Carries the structured issues for reporting.
    """

    def __init__(self, issues: list[ContractIssue]):
        self.issues = list(issues)
        errors = [issue for issue in self.issues if issue.is_error]
        summary = "; ".join(f"{issue.code} ({issue.location})" for issue in errors)
        super().__init__(f"contract validation failed: {summary}" if summary else "contract validation failed")
