import re
out=["""-- ============================================================================
-- Release 2, piece 8: coordinators can transfer their ticket like anyone else
-- Written 26 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01 to r2_06. Safe to run twice. Changes no data.
-- Also: an admin can no longer change the coordinator status of a ticket that was already transferred away.
-- What changes: the seller checks no longer refuse a coordinator ticket, and the admin's
-- final check accepts a coordinator ticket. The buyer always becomes a normal GUEST (the
-- coordinator role is only ever given by an admin). The coordinator's own numbers (guest and
-- coordinator) are retired for good, as for any transferred ticket.
-- ============================================================================
"""]
for n in ['private_sell','public_sell','admin_transfer_approve','set_coordinator']:
    d=open(f'/tmp/fn_{n}.sql').read().rstrip()
    if n=='set_coordinator':
        a="  if not found then raise exception 'INVALID_TICKET'; end if;\n"
        b=a+"  if t.transferred_out_at is not null then raise exception 'ALREADY_TRANSFERRED'; end if;   -- a retired ticket can never become (or stop being) a coordinator\n"
        assert d.count(a)==1; d=d.replace(a,b)
    elif n=='admin_transfer_approve':
        a="if sb.status <> 'paid' or t.kind <> 'guest' or t.ticket_no is null then raise exception 'SELLER_TICKET_INVALID'; end if;"
        b="if sb.status <> 'paid' or (t.ticket_no is null and t.coord_no is null) then raise exception 'SELLER_TICKET_INVALID'; end if;"
        assert d.count(a)==1; d=d.replace(a,b)
    else:
        a="  if b.status <> 'paid' or t.ticket_no is null then return jsonb_build_object('ok', false, 'error', 'NOT_CONFIRMED'); end if;\n  if t.kind <> 'guest' then return jsonb_build_object('ok', false, 'error', 'COORDINATOR'); end if;\n"
        b="  if b.status <> 'paid' or (t.ticket_no is null and t.coord_no is null) then return jsonb_build_object('ok', false, 'error', 'NOT_CONFIRMED'); end if;\n"
        assert d.count(a)==1; d=d.replace(a,b)
    out.append(f"-- {n}\n"+d+";\n")
open('/home/claude/ca-meetup-register/sql/r2_08_coordinator_transfer.sql','w').write("\n".join(out))
