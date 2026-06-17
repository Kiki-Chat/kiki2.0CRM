-- 0074_batch3_rls_policies_and_fn_hardening.sql
-- Batch 3 security hardening (ADDITIVE, non-breaking).
-- Verified safe: the browser Supabase client is used ONLY for auth.* — there are ZERO
-- .from()/.rpc()/.storage() data calls in frontend/src, so all CRM data flows through the
-- backend service-role key (which bypasses RLS). Adding policies/locking functions cannot
-- break any running client. These 16 tables are currently RLS-enabled with 0 policies
-- (deny-all to PostgREST anon/authenticated roles); adding an org policy only loosens that
-- for those roles, with no behavioral change to the app.
--
-- 1) org-scoped RLS policies (mirror the 0001 <table>_org_all pattern via auth_org_id()).
--    INTENTIONALLY EXCLUDED:
--      * org_secrets, oauth_connections  -> secret/token-bearing; kept strictly deny-all
--        (least-exposure; backend service-role only).
--      * billing_security_events, billing_webhook_events -> no org_id column (system tables,
--        keyed by Stripe event id); kept deny-all, backend-only.
-- 2) pin search_path on kz_begin_agent_sync (resolves the "mutable search_path" advisor).
-- 3) revoke EXECUTE on rls_auto_enable() from anon/authenticated (it runs via the ensure_rls
--    event trigger, never as a PostgREST RPC — the grant is gratuitous attack surface).
--
-- auth_org_id() is intentionally LEFT UNCHANGED: every <table>_org_all policy calls it, and
-- it must remain SECURITY DEFINER + executable by `authenticated` or all org-scoped RLS breaks.
--
-- Reversible: drop policy <t>_org_all on public.<t>;  alter function kz_begin_agent_sync(uuid,text) reset search_path;
--             grant execute on function rls_auto_enable() to anon, authenticated;

do $$
declare t text;
begin
  foreach t in array array[
    'action_tasks','billing_checkout_sessions','billing_events','billing_migration_log',
    'billing_notifications','billing_usage_reports','case_links','employee_absences',
    'maintenance_plans','missed_calls','oauth_purpose_links','outbound_calls',
    'technician_job_links','text_modules','tools','vehicles'
  ]
  loop
    if not exists (
      select 1 from pg_policies
      where schemaname='public' and tablename=t and policyname=t||'_org_all'
    ) then
      execute format(
        'create policy %I_org_all on public.%I for all using (org_id = auth_org_id()) with check (org_id = auth_org_id())',
        t, t);
    end if;
  end loop;
end $$;

alter function public.kz_begin_agent_sync(uuid, text) set search_path = public;

-- Revoke from PUBLIC (the default grant anon/authenticated inherit) — the event trigger
-- ensure_rls still fires regardless of EXECUTE grants, so this removes only the RPC surface.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
