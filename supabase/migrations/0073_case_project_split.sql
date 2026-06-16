-- 0073 — Case ↔ Project split: restore the Project layer ABOVE the Case.
--
-- Reverses the "cases replace projects" merge (0067/3e5f144). The hierarchy becomes:
--     Call → Inquiry (ANF-) → Case (FL-) → Project (PR-, restored top container)
--
-- Mechanics = RENAME, ZERO DATA COPY (Amber's ruling 2026-06-16):
--   * `projects` IS the de-facto Case today (44 rows, FL- numbers, full schema, every
--     billing/action FK points to it) → simply RENAME it to `cases`. All 6 inbound FKs
--     follow the rename by OID; not a single row is copied.
--   * The lean `cases` table (14 stale, 0-referenced rows from the abandoned K-numbering
--     experiment) is DROPPED to free the name; `inquiries.case_id` (100% NULL) goes with it.
--   * The grouping pointer + 5 action FK columns are renamed project_id → case_id so the
--     vocabulary is clean (handover: "re-point the 5 action FKs from project_id → case_id;
--     employees → case-level").
--   * A FRESH, EMPTY top-layer `projects` table is created (restored original full form:
--     budget/dates/address/notes) with its OWN number scheme PR-{token}-NNNN.
--   * `cases.project_id` links a Case up into a Project (nullable — small matters stay
--     just a Case; only big/multi-offer matters join a Project).
--
-- DB-object audit (live, 2026-06-16): 0 views, 0 triggers, 0 functions, 0 sequences touch
-- these tables; only 2 RLS policies — `projects_org_all` (follows the rename) and
-- `project_employees_org_all` (hardcodes `from projects p` → rewritten below).
--
-- NOT TOUCHED (naming trap): `case_links.case_id` is a FK to INQUIRIES (inquiry-threading,
-- 0055), unrelated to this split. Left alone.
--
-- ROLLBACK (manual, if ever needed): rename cases→projects, reverse the column renames,
-- drop the new projects table + cases.project_id, recreate the lean cases table. No data
-- copy to unwind.

-- 1) Free the names: drop the empty grouping pointer + the stale lean `cases` table.
--    inquiries.case_id is 100% NULL and is the ONLY FK into the stale `cases` table.
alter table inquiries drop column if exists case_id;          -- drops inquiries_case_id_fkey + idx_inquiries_case
drop table if exists cases cascade;                           -- 14 stale unreferenced rows + its own indexes
-- keep inquiries.case_confidence / case_reason / case_source — grouping audit, reused below.

-- 2) Promote the de-facto case table: projects → cases (44 rows stay put; all FKs follow).
alter table projects rename to cases;
alter index if exists idx_projects_org           rename to idx_cases_org;
alter index if exists idx_projects_org_number    rename to idx_cases_org_number;   -- UNIQUE(org_id,number): FL- uniqueness
alter index if exists idx_projects_customer_id   rename to idx_cases_customer_id;
alter index if exists idx_projects_created_by    rename to idx_cases_created_by;
alter policy projects_org_all on cases rename to cases_org_all;                     -- org check still valid post-rename

-- 3) Rename the grouping pointer + action FK columns project_id → case_id (metadata only).
alter table inquiries      rename column project_id to case_id;
alter table inquiries      rename constraint inquiries_project_id_fkey to inquiries_case_id_fkey;
alter index if exists idx_inquiries_project rename to idx_inquiries_case;

alter table appointments   rename column project_id to case_id;
alter table appointments   rename constraint appointments_project_id_fkey to appointments_case_id_fkey;
alter index if exists idx_appointments_project rename to idx_appointments_case;

alter table cost_estimates rename column project_id to case_id;
alter table cost_estimates rename constraint cost_estimates_project_id_fkey to cost_estimates_case_id_fkey;
alter index if exists idx_cost_estimates_project rename to idx_cost_estimates_case;

alter table invoices       rename column project_id to case_id;
alter table invoices       rename constraint invoices_project_id_fkey to invoices_case_id_fkey;
alter index if exists idx_invoices_project rename to idx_invoices_case;

alter table documents      rename column project_id to case_id;
alter table documents      rename constraint documents_project_id_fkey to documents_case_id_fkey;
alter index if exists idx_documents_project rename to idx_documents_case;

-- 4) project_employees → case_employees (team lives at case level per handover).
alter table project_employees rename to case_employees;
alter table case_employees rename column project_id to case_id;
alter table case_employees rename constraint project_employees_project_id_fkey to case_employees_case_id_fkey;
alter index if exists idx_project_employees_project rename to idx_case_employees_case;
-- the old policy hardcoded `from projects p` — rewrite against the renamed cases table.
drop policy if exists project_employees_org_all on case_employees;
create policy case_employees_org_all on case_employees
  for all using (
    exists (select 1 from cases c where c.id = case_employees.case_id and c.org_id = auth_org_id())
  ) with check (
    exists (select 1 from cases c where c.id = case_employees.case_id and c.org_id = auth_org_id())
  );

-- 5) Restore the top-layer `projects` table (fresh + empty; PR-{token}-NNNN numbers).
create table projects (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references organizations on delete cascade,
  customer_id uuid references customers on delete set null,
  number text,                                   -- PR-{TOKEN}-NNNN (own scheme; no FL- collision)
  title text not null,
  description text,
  status text default 'planning'
    check (status in ('planning', 'active', 'completed', 'archived')),
  start_date date,
  end_date date,
  planned_budget numeric,
  project_address jsonb,                          -- {street, postcode, city}
  internal_notes text,
  notes_updated_at timestamptz,
  created_by uuid references users on delete set null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index idx_projects_org on projects (org_id);
create unique index idx_projects_org_number on projects (org_id, number);
create index idx_projects_customer_id on projects (customer_id);
alter table projects enable row level security;
create policy projects_org_all on projects
  for all using (org_id = auth_org_id()) with check (org_id = auth_org_id());

-- 6) Link Case → Project (a case may belong to one top-layer project; small matters stay NULL).
alter table cases add column if not exists project_id uuid references projects on delete set null;
create index if not exists idx_cases_project on cases (project_id);
