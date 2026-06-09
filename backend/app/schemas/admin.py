"""Schemas for the operator-facing (frontend) endpoints."""

from pydantic import BaseModel


class InquiryUpdate(BaseModel):
    status: str | None = None  # open | in_progress | completed | deleted
    assigned_employee_id: str | None = None
    title: str | None = None
    type: str | None = None  # appointment | offer | info | recall
    notes: str | None = None
    project_id: str | None = None

    # Distinguish "set to null" from "not provided" for assignment.
    model_config = {"extra": "ignore"}


class CustomerUpsert(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    phone2: str | None = None
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
    activity_area: str | None = None
    auto_assign: bool = False
    is_technician: bool = False  # tag: does the ground work (Zuweisung/Plantafel)


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
    is_technician: bool | None = None


class AbsenceCreate(BaseModel):
    type: str = "vacation"  # vacation | illness | training | home_office | other
    starts_at: str  # ISO datetime
    ends_at: str
    all_day: bool = True
    reason: str | None = None
    internal_note: str | None = None


class AbsenceApply(BaseModel):
    """Employee self-service absence REQUEST (lands as status='pending'). No
    internal_note — that's an admin field; the employee's own employee_id is
    resolved server-side, never taken from the request."""
    type: str = "vacation"
    starts_at: str
    ends_at: str
    all_day: bool = True
    reason: str | None = None


class AbsenceReview(BaseModel):
    """Admin approve/reject payload. Optional note stored as the absence's
    internal_note (e.g. a rejection reason)."""
    note: str | None = None


class VehicleUpsert(BaseModel):
    name: str | None = None
    model: str | None = None
    license_plate: str | None = None
    capacity_hours: int | None = None
    assigned_employee_id: str | None = None
    color: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    vehicle_type: str | None = None
    brand: str | None = None
    tuev_until: str | None = None
    insurance_until: str | None = None
    next_maintenance: str | None = None
    max_weight_kg: float | None = None
    cargo_space_m3: float | None = None
    status: str | None = None


class ToolUpsert(BaseModel):
    name: str | None = None
    category: str | None = None
    serial_number: str | None = None
    assigned_employee_id: str | None = None
    storage_location: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    condition: str | None = None
    next_maintenance: str | None = None
    purchase_date: str | None = None
    purchase_price: float | None = None


class CatalogItemUpsert(BaseModel):
    article_number: str | None = None
    name: str | None = None
    description: str | None = None
    category: str | None = None
    unit: str | None = None
    vat_rate: float | None = None
    is_wage: bool | None = None
    unit_price: float | None = None  # selling price (net)
    purchase_price: float | None = None
    supplier_id: str | None = None
    is_active: bool | None = None


class TextModuleUpsert(BaseModel):
    name: str | None = None
    category: str | None = None
    content: str | None = None
    sort_order: int | None = None
    is_default: bool | None = None


class AppointmentPatch(BaseModel):
    # Only provided fields are updated; explicit null clears the field.
    vehicle_id: str | None = None
    tool_id: str | None = None
    assigned_employee_id: str | None = None
    status: str | None = None
    title: str | None = None
    scheduled_at: str | None = None
    duration_minutes: int | None = None
    category: str | None = None
    notes: str | None = None

    model_config = {"extra": "ignore"}


class CostEstimatePosition(BaseModel):
    kind: str = "item"  # item | optional | subtotal | text
    description: str | None = None
    quantity: float = 1
    unit: str | None = "Stk"
    price: float = 0
    vat: float = 19
    discount_pct: float = 0
    is_labor: bool = False


class CostEstimateUpsert(BaseModel):
    customer_id: str | None = None
    inquiry_id: str | None = None
    project_id: str | None = None
    type: str = "kva"  # kva | offer | invoice
    subject: str | None = None
    reference_number: str | None = None
    is_binding: bool = False
    tolerance_pct: int = 20
    validity_days: int = 30
    positions: list[CostEstimatePosition] = []
    intro_text: str | None = None
    closing_text: str | None = None
    payment_terms: str | None = None
    surcharge: float = 0
    surcharge_description: str | None = None
    total_discount_pct: float = 0


class CostEstimateStatus(BaseModel):
    status: str  # accepted | rejected | invoiced | draft | sent


class CostEstimateSend(BaseModel):
    to: str | None = None
    subject: str | None = None
    message: str | None = None
    copy_to_me: bool = False


class InvoiceUpsert(BaseModel):
    customer_id: str | None = None
    kva_id: str | None = None  # source cost estimate (stored in cost_estimate_id)
    project_id: str | None = None
    subject: str | None = None
    reference_number: str | None = None
    invoice_date: str | None = None  # ISO date; defaults to today
    performance_date: str | None = None  # Leistungsdatum
    payment_terms_days: int = 14
    discount_pct: float | None = None  # Skonto %
    discount_days: int | None = None  # Skonto Tage
    positions: list[CostEstimatePosition] = []
    intro_text: str | None = None
    closing_text: str | None = None
    payment_terms_text: str | None = None
    surcharge: float = 0
    surcharge_description: str | None = None
    total_discount_pct: float = 0


class InvoiceStatus(BaseModel):
    status: str  # draft | sent | paid | cancelled


class InvoiceSend(BaseModel):
    to: str | None = None
    subject: str | None = None
    message: str | None = None
    copy_to_me: bool = False


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
    project_id: str | None = None


class ProjectUpsert(BaseModel):
    customer_id: str | None = None
    title: str
    description: str | None = None
    status: str | None = None  # planning | active | completed | archived
    start_date: str | None = None
    end_date: str | None = None
    planned_budget: float | None = None
    project_address: dict | None = None  # {street, postcode, city}
    internal_notes: str | None = None


class ProjectPatch(BaseModel):
    customer_id: str | None = None
    title: str | None = None
    description: str | None = None
    status: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    planned_budget: float | None = None
    project_address: dict | None = None
    internal_notes: str | None = None

    model_config = {"extra": "ignore"}


class ProjectEmployeeAdd(BaseModel):
    employee_id: str
