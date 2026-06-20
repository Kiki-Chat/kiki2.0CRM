"""Per-employee data scoping for the employee portal.

Admins (``org_admin`` / ``super_admin``) represent the company and see the WHOLE
org — for them every ``filter_*`` helper is a no-op. A plain ``employee`` sees
only their OWN work: the cases they are on, the inquiries/appointments assigned
to them, and everything that hangs off those (calls, cost estimates, invoices,
customers).

The assignment graph is resolved ONCE per request (``resolve_scope``) and the id
sets are reused across the dashboard, cases and calls endpoints, so a request
never re-walks the graph. The resolution is intentionally generous toward a case
the employee is a member of: being on a Fall means you see that Fall's whole
record (its inquiries, calls, appointments, money), not just the rows literally
stamped with your name.

Data model (post-migration 0073):
  * ``employees.user_id``           → the login (users.id)
  * ``inquiries.assigned_employee_id`` / ``.case_id`` / ``.call_id`` / ``.customer_id``
  * ``appointments.assigned_employee_id`` / ``.case_id`` / ``.inquiry_id`` / ``.customer_id``
  * ``case_employees(case_id, employee_id)``   — case team membership
  * ``calls.inquiry_id``            — forward link from a call to its inquiry
  * ``cost_estimates.case_id`` / ``invoices.case_id``  — money rolls up to a Fall
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Sentinel that can never match a real uuid — used so an empty scope yields an
# empty result set instead of "no filter" (which would leak the whole org).
_NEVER = "00000000-0000-0000-0000-000000000000"

_ADMIN_ROLES = ("org_admin", "super_admin")


def _ids(values: set[str] | None) -> list[str]:
    return list(values) if values else [_NEVER]


@dataclass
class EmployeeScope:
    """Resolved scope for one request. ``restricted`` is True only for a plain
    employee; admins keep the full-org view."""

    is_admin: bool
    org_id: str
    employee_id: str | None = None
    case_ids: set[str] = field(default_factory=set)
    inquiry_ids: set[str] = field(default_factory=set)
    call_ids: set[str] = field(default_factory=set)
    appointment_ids: set[str] = field(default_factory=set)
    customer_ids: set[str] = field(default_factory=set)

    @property
    def restricted(self) -> bool:
        return not self.is_admin

    # ── query helpers: restrict a PostgREST query to this employee's ids ──────
    # Each is a no-op for admins, so callers can apply them unconditionally.
    def filter_cases(self, q, col: str = "id"):
        return q if self.is_admin else q.in_(col, _ids(self.case_ids))

    def filter_inquiries(self, q, col: str = "id"):
        return q if self.is_admin else q.in_(col, _ids(self.inquiry_ids))

    def filter_calls(self, q, col: str = "id"):
        return q if self.is_admin else q.in_(col, _ids(self.call_ids))

    def filter_appointments(self, q, col: str = "id"):
        return q if self.is_admin else q.in_(col, _ids(self.appointment_ids))

    def filter_customers(self, q, col: str = "id"):
        return q if self.is_admin else q.in_(col, _ids(self.customer_ids))


def resolve_scope(client, user) -> EmployeeScope:
    """Walk the assignment graph for ``user`` and return their EmployeeScope.

    Admins short-circuit (no DB walk). A non-admin with no matching employee row
    gets an empty scope (sees nothing) rather than the whole org.
    """
    is_admin = getattr(user, "role", None) in _ADMIN_ROLES
    org_id = user.org_id
    scope = EmployeeScope(is_admin=is_admin, org_id=org_id)
    if is_admin:
        return scope

    emp = (
        client.table("employees").select("id")
        .eq("org_id", org_id).eq("user_id", user.id).eq("deleted", False)
        .limit(1).execute().data
    )
    scope.employee_id = emp[0]["id"] if emp else None
    if not scope.employee_id:
        return scope  # logged-in non-admin with no staff record → empty scope
    eid = scope.employee_id

    # 1) Cases I'm a member of (team membership).
    for r in (
        client.table("case_employees").select("case_id")
        .eq("employee_id", eid).execute().data or []
    ):
        if r.get("case_id"):
            scope.case_ids.add(r["case_id"])

    # 2) Inquiries assigned to me (+ their case / call / customer links).
    for r in (
        client.table("inquiries").select("id, case_id, call_id, customer_id")
        .eq("org_id", org_id).eq("assigned_employee_id", eid).execute().data or []
    ):
        scope.inquiry_ids.add(r["id"])
        if r.get("case_id"):
            scope.case_ids.add(r["case_id"])
        if r.get("call_id"):
            scope.call_ids.add(r["call_id"])
        if r.get("customer_id"):
            scope.customer_ids.add(r["customer_id"])

    # 3) Appointments assigned to me (+ their case / inquiry / customer links).
    for r in (
        client.table("appointments").select("id, case_id, inquiry_id, customer_id")
        .eq("org_id", org_id).eq("assigned_employee_id", eid).execute().data or []
    ):
        scope.appointment_ids.add(r["id"])
        if r.get("case_id"):
            scope.case_ids.add(r["case_id"])
        if r.get("inquiry_id"):
            scope.inquiry_ids.add(r["inquiry_id"])
        if r.get("customer_id"):
            scope.customer_ids.add(r["customer_id"])

    # 4) Expand each case I touch to its whole record — being on a Fall means you
    #    see that Fall's inquiries, calls, appointments and customer.
    if scope.case_ids:
        case_id_list = list(scope.case_ids)
        for r in (
            client.table("inquiries").select("id, call_id, customer_id")
            .eq("org_id", org_id).in_("case_id", case_id_list).execute().data or []
        ):
            scope.inquiry_ids.add(r["id"])
            if r.get("call_id"):
                scope.call_ids.add(r["call_id"])
            if r.get("customer_id"):
                scope.customer_ids.add(r["customer_id"])
        for r in (
            client.table("cases").select("customer_id")
            .eq("org_id", org_id).in_("id", case_id_list).execute().data or []
        ):
            if r.get("customer_id"):
                scope.customer_ids.add(r["customer_id"])
        for r in (
            client.table("appointments").select("id")
            .eq("org_id", org_id).in_("case_id", case_id_list).execute().data or []
        ):
            scope.appointment_ids.add(r["id"])

    # 5) Calls forward-linked to any of my inquiries (in addition to the reverse
    #    inquiry.call_id links gathered above).
    if scope.inquiry_ids:
        for r in (
            client.table("calls").select("id")
            .eq("org_id", org_id).in_("inquiry_id", list(scope.inquiry_ids))
            .execute().data or []
        ):
            scope.call_ids.add(r["id"])

    return scope
