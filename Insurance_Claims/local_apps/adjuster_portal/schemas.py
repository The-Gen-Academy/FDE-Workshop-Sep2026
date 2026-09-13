"""Request/response models for the adjuster portal API."""

from typing import Literal

from pydantic import BaseModel


class DecisionRequest(BaseModel):
    action: Literal["approve", "deny"]
    amount: float | None = None
    reason: str = ""


class PolicyCreateRequest(BaseModel):
    policyholder_name: str
    vin: str
    listed_drivers: list[str]
    collision: bool
    comprehensive: bool
    deductible: float
    limits: float
    effective_date: str
    expiration_date: str
    exclusions: list[str]
