-- Restrict the RLS helper so anonymous clients can't call it via RPC.
revoke execute on function public.auth_org_id() from public, anon;
grant execute on function public.auth_org_id() to authenticated;
