-- =============================================================================
-- 0030_freeze_product_code.sql
-- Stop a product_code changing once QR labels have been printed for it.
--
-- freeze_product_code() was a BEFORE UPDATE trigger whose whole body was
-- `new.updated_at := now()`. Despite the name it froze nothing, and
-- products_owner_update lets an owner update the entire row.
--
-- WHY NOT AN OUTRIGHT FREEZE
-- --------------------------
-- The owner product form supports a custom code on purpose:
-- SupabaseProductRepository.create and .update both put draft.customCode into
-- the payload as product_code. Making the column immutable would break that
-- feature, so the guard applies only from the point where a change does real
-- damage -- once allocate_product_qr_labels has printed labels.
--
-- WHAT ACTUALLY BREAKS ON A LATE CHANGE
-- -------------------------------------
-- Not QR scanning: product_qr_labels keys on product_id, so step 1 of
-- lookup_product_by_barcode keeps resolving. What breaks is
--   * the human-readable code printed on stickers already in the field, and
--   * step 2 of lookup_product_by_barcode, which matches a scanned value
--     against products.product_code directly.
--
-- updated_at stamping is unchanged.
-- =============================================================================

create or replace function public.freeze_product_code()
returns trigger language plpgsql as $$
begin
  if new.product_code is distinct from old.product_code
     and exists (select 1 from public.product_qr_labels q
                  where q.product_id = old.id)
  then
    raise exception
      'product_code cannot change once QR labels are allocated (% -> %)',
      old.product_code, new.product_code using errcode = '23514';
  end if;

  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists freeze_product_code on public.products;
create trigger freeze_product_code
  before update on public.products
  for each row execute function public.freeze_product_code();

revoke all on function public.freeze_product_code() from public, anon, authenticated;
