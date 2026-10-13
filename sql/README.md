# SQL folder guide

The live database sits in Supabase, so the repo only knows about it if we save it here. This folder is the repo's copy of the database setup.

## What to keep in this folder

| File | What goes in it |
|---|---|
| `schema.md` or `schema.csv` | Result of the columns query below (tables and columns) |
| `functions.sql` | Result of the functions query (full source of every function) |
| `policies.md` | Result of the policies queries (table and storage) |
| `changes.sql` | Every SQL statement you run later, newest at the bottom, with a date comment |

You don't have to format anything nicely. Pasting the query result into a file is enough for a future Claude session to read.

## How to refresh the exports

Run each query in the Supabase SQL editor, copy the result, and paste it into the matching file.

**Tables and columns**
```sql
select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
order by table_name, ordinal_position;
```

**Functions (full source)**
```sql
select p.proname, pg_get_function_arguments(p.oid) as args, pg_get_functiondef(p.oid) as definition
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public';
```

**Security policies (tables and storage)**
```sql
select tablename, policyname, cmd, roles, qual, with_check
from pg_policies where schemaname in ('public', 'storage');
```

**Indexes and unique rules** (not exported yet, please add)
```sql
select tablename, indexdef from pg_indexes where schemaname = 'public' order by tablename;
```

**Views**
```sql
select table_name, view_definition from information_schema.views where table_schema = 'public';
```

Before pasting, scan for passwords or keys and remove them. This repo is public.

## Changes already made (add to `changes.sql`)

```sql
-- 13 Oct 2026: make the report view follow the caller's permissions
alter view public.report set (security_invoker = true);

-- 13 Oct 2026: internal helpers must not be callable from outside
revoke execute on function public._assign_numbers(uuid), public._booking_json(uuid)
  from public, anon, authenticated;

-- 13 Oct 2026: undo_checkin now works for coordinators too (by ticket id or number)
drop function if exists public.undo_checkin(integer);

create or replace function public.undo_checkin(
  p_ticket_no integer default null,
  p_coord boolean default false,
  p_id uuid default null
) returns void
language plpgsql
security definer
set search_path to 'public'
as $function$
declare n int;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;

  if p_id is not null then
    update tickets set checked_in_at = null, checked_in_by = null where id = p_id;
  elsif p_coord then
    update tickets set checked_in_at = null, checked_in_by = null
    where coord_no = p_ticket_no and kind = 'coordinator';
  else
    update tickets set checked_in_at = null, checked_in_by = null where ticket_no = p_ticket_no;
  end if;

  get diagnostics n = row_count;
  if n = 0 then raise exception 'INVALID_TICKET'; end if;
end $function$;

revoke execute on function public.undo_checkin(integer, boolean, uuid) from public, anon;
grant execute on function public.undo_checkin(integer, boolean, uuid) to authenticated;
```

Also done in the Supabase dashboard (not SQL): file size and image-type limits on the `payment-proofs` bucket, and "Allow new users to sign up" turned off in Authentication.

## Rule of thumb

Whenever you run new SQL in Supabase, paste it into `changes.sql` the same day. If you ever forget, re-run the export queries above and replace the old files.
