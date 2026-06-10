-- 0056 — Case (Vorgang) grouping layer. Additive.
--
-- A "case" binds MANY inquiries (threads) into one real-world matter. The data showed
-- inquiries are minted per interaction (one booking → call inquiry + appointment inquiry
-- + each outbound call), so a matter is scattered across several inquiries with no shared
-- key but the customer. `cases` is the binder we manufacture; the LLM matchmaker proposes
-- the grouping, a human confirms, and inquiries.case_id carries it.
--
--  * cases            — the matter. label = short topic; status mirrors the inquiry
--    lifecycle. customer-scoped.
--  * inquiries.case_id — which case an inquiry belongs to (nullable: ungrouped = its own
--    standalone matter). ON DELETE SET NULL so dropping a case never deletes its threads.
--  * grouping audit on the inquiry so staff see WHY it was grouped (LLM confidence + reason),
--    matching the "show the customer why + one-click move" requirement.

create table if not exists cases (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references organizations(id) on delete cascade,
  customer_id uuid references customers(id) on delete set null,
  label       text,
  status      text not null default 'open' check (status in ('open','in_progress','completed','closed')),
  created_by  uuid references users(id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table inquiries add column if not exists case_id uuid references cases(id) on delete set null;
alter table inquiries add column if not exists case_confidence numeric;     -- LLM confidence 0-1 for this assignment
alter table inquiries add column if not exists case_reason text;            -- short human-readable why
alter table inquiries add column if not exists case_source text;            -- 'ai' | 'human' | 'ai_confirmed'

create index if not exists idx_cases_org on cases (org_id);
create index if not exists idx_cases_customer on cases (customer_id);
create index if not exists idx_inquiries_case on inquiries (case_id);
