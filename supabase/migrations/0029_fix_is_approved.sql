-- =============================================================================
-- 0029_fix_is_approved.sql
-- Make is_approved() actually check account status.
--
-- It was defined as `select true`, so it returned true for every caller. Every
-- RLS policy that gates on it therefore admitted any signed-in account --
-- catalog_view, catalog_images_view, business_settings_select,
-- scan_events_insert_approved, the unit_registrations / unit_services /
-- warranty_claims policies, and the product-images read policy. A wholesaler
-- sitting at status 'pending' could read and write all of it. The approval
-- queue was a screen, not a gate.
--
-- Migration 0028 auto-approves retailers, so the only accounts that ever hold
-- 'pending' are wholesalers -- exactly the ones meant to be waiting.
--
-- OPERATIONAL NOTE: on a database with existing users, any wholesaler still at
-- 'pending' loses access the moment this runs. That is the point, but it is a
-- visible change for them. Check who is affected before running on production:
--
--   select id, firm_name, status from public.profiles
--    where role = 'wholesaler' and status <> 'approved';
--
-- Anonymous callers now get false rather than true. Policies that must keep
-- serving the public catalogue already spell that out themselves as
-- (auth.uid() is null or public.is_approved()), so they are unaffected.
-- =============================================================================

create or replace function public.is_approved()
returns boolean
language sql stable security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid()
      and p.status = 'approved'
  );
$$;

comment on function public.is_approved() is
  'True only for a signed-in account whose status is approved. Returns false '
  'for anonymous callers, so every policy that must still serve the public '
  'catalogue spells that out as (auth.uid() is null or public.is_approved()).';

-- create or replace preserves grants, but restate them so a fresh run is complete.
grant execute on function public.is_approved() to anon, authenticated;
