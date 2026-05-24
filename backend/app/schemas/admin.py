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


class EmployeeCreate(BaseModel):
    display_name: str
    email: str | None = None
    login_access: bool = True
    access_role: str = "employee"  # admin | employee
    is_active: bool = True
    calendar_color: str | None = None


class EmployeeUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    access_role: str | None = None
    is_active: bool | None = None
    calendar_color: str | None = None
    vacation_days_per_year: int | None = None
    remaining_vacation_days: int | None = None
    hourly_rate: float | None = None
    activity_area: str | None = None
    auto_assign: bool | None = None


class AbsenceCreate(BaseModel):
    type: str = "vacation"  # vacation | illness | training | home_office | other
    starts_at: str  # ISO datetime
    ends_at: str
    all_day: bool = True
    reason: str | None = None
    internal_note: str | None = None


class VehicleUpsert(BaseModel):
    name: str | None = None
    model: str | None = None
    license_plate: str | None = None
    capacity_hours: int | None = None
    assigned_employee_id: str | None = None
    color: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class ToolUpsert(BaseModel):
    name: str | None = None
    category: str | None = None
    serial_number: str | None = None
    assigned_employee_id: str | None = None
    storage_location: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class AppointmentPatch(BaseModel):
    # Only provided fields are updated; explicit null clears the field.
    vehicle_id: str | None = None
    tool_id: str | None = None
    assigned_employee_id: str | None = None
    status: str | None = None
    title: str | None = None
    scheduled_at: str | None = None
    duration_minutes: int | None = None
    notes: str | None = None

    model_config = {"extra": "ignore"}


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
