"""Schemas for the operator-facing (frontend) endpoints."""

from pydantic import BaseModel


class InquiryUpdate(BaseModel):
    status: str | None = None  # open | in_progress | completed | deleted
    assigned_employee_id: str | None = None
    title: str | None = None
    type: str | None = None  # appointment | offer | info | recall
    notes: str | None = None

    # Distinguish "set to null" from "not provided" for assignment.
    model_config = {"extra": "ignore"}


class CustomerUpsert(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    vat_id: str | None = None
    customer_type: str | None = None  # new | regular | supplier | property_management
    notes: str | None = None
    customer_number: str | None = None


class AppointmentCreate(BaseModel):
    customer_id: str | None = None
    title: str | None = None
    scheduled_at: str  # ISO datetime
    duration_minutes: int = 60
    location: str | None = None
    category: str | None = None
    color: str | None = None
    assigned_employee_id: str | None = None
    notes: str | None = None
    inquiry_id: str | None = None
