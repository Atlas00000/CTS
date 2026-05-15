"""API error types for consistent HTTP responses."""

from __future__ import annotations


class MissingFeaturesError(ValueError):
    def __init__(self, missing_keys: list[str]) -> None:
        self.missing_keys = missing_keys
        super().__init__(f"missing_keys:{','.join(missing_keys)}")
