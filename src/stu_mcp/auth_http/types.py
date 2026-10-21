"""Private in-memory authentication results; only proof metadata is public."""
from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class Candidate:
    state: dict
    proof: dict


@dataclass(frozen=True, repr=False)
class Credentials:
    username: str
    password: str
