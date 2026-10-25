# HANDOVER FOR THE NEXT CLAUDE SESSION

> ## LIVE STATUS, 25 Oct 2026 evening: READ THIS FIRST (it overrides anything below that disagrees)
> - **Release 2 is LIVE.** Rollout steps 1 to 6 are done with the owner: snapshot, `r2_01` + `r2_02` (file `sql/rollout_A_part1_APPLIED.sql`), the three pages published (PR #1, then PR for the Transfers-history "New Booking ID" line), `r2_02b` to `r2_06` (file `sql/rollout_A_part2_APPLIED.sql`), snapshot comparison, rehearsal.
> - **Snapshot comparison (tested vs live):** columns, constraints, indexes, views, view options, RLS on/off, every function with its execute rights and triggers are IDENTICAL between the scratch copy (old snapshot + r2 files) and the real database. Only Supabase's own items differ (storage policies, its event triggers, `rls_auto_enable`), which the scratch copy does not model. Table grants for the four new tables are staff-read-only. All six suites still pass (572).
> - **Rehearsal on the real site (owner, phone):** registration with email and +91; Tickets lookup by Booking ID + phone; private transfer; public transfer with payment screenshot, verify, transfer, payout; reject path; gate refuses the old QR (TICKET CANCELLED) and shows retired tickets as Transferred; all worked. Real visitor IP: `booking_ips.raw` shows `cf=` and `xff=` both filled with the visitor's address, so G10 is closed (the function prefers `cf-connecting-ip`).
> - **Found in the rehearsal:** the buyer's new Booking ID was not visible in Admin (transfer bookings are hidden from Bookings by design; it is in People). Fixed: the Transfers history now shows "New Booking ID".
> - **Test data cleaned:** `sql/r2_07_cleanup_test_data.sql` (refuses to run while registration is open; keeps staff, settings and log; restarts numbering at 1; turns transfers OFF) was run by the owner, and the `payment-proofs` bucket was emptied. Registration is closed. Transfers are OFF.
> - **Owner decisions made 25-26 Oct 2026 (these replace the defaults in section 8):** (1) money is returned to a public buyer who paid when the transfer fails; (2) transfer codes last 24 hours (set in Admin → Settings → Transfers); (3) no extra spam protection for now (the address flag only); (4) no automatic expiry of waiting transfers (admin sees the age); (5) **coordinators CAN transfer their ticket like anyone else**: built as `sql/r2_08_coordinator_transfer.sql` (buyer always becomes a normal guest; the coordinator's guest and coordinator numbers are retired; an admin can no longer change the coordinator status of a retired ticket; tests `scratch-db/test_r2_08.py`, 36 checks, 5 of 5 deliberate mistakes caught); (6) **there are no free passes**: guests of honour enter without registration or gate checks, so they are outside this app; (7) seller and buyer see only each other's name (kept); (8) the text now says the organisers "may call" (not "will call"); (9) the two "I want to buy" buttons were merged into ONE, because the code itself decides private or public (a private code typed in the public flow works by design: one code flow).
> - **Left to do (in the owner's order):** (1) owner decisions in section 8 are still on defaults; (2) minor changes: logo placeholders, About link/page (needs the owner's content); (3) the restyle ("Midnight Emerald" admin/gate, ivory/green public) then re-run all browser suites; (4) before opening registration: confirm Admin → Settings (price, cap, deadline, UPI, payee, WhatsApp), transfers cut-off, and that editing is closed. Screens were checked on the owner's phone but not in a real UPI app with a real payment.

> ## UPDATE 25 Oct 2026: READ THIS BLOCK FIRST (it overrides anything below that disagrees)
> - **Everything on the master list (section 4) is now BUILT and tested except the rollout itself, the rehearsal, the restyle and the About page.** Piece 6 is written (`sql/r2_06_transfer_settings.sql`); emails are in the admin-only table `ticket_emails` (G3 resolved); the admin, gate and public pages are rewritten (G4, G5, G6 resolved); G8 is closed (the scratch copy now reproduces real permissions); G11 done (`baseline.py` deleted). See the 24-25 Oct entry in `PROJECT_NOTES.md` section 13 for details.
> - **Tests:** database suites 62, 55, 153, 157, 77, 68 (`scratch-db/test_r2_01..06.py`, 572 checks); browser suites in `scratch-db/browser/` (`run_admin.py` 33, `run_gate.py` 7, `run_public.py` 68; they use Playwright with a mocked Supabase, see `mock_supabase.js`; run from that folder). Rebuild recipe in section 9 still applies; add piece 6 to the file list used by `test_r2_06.py`.
> - **The live site and database are UNCHANGED.** The owner has real state to confirm first (section 1: is registration still closed with no real bookings? the owner said so on 24 Oct 2026).
> - **Rollout order (use this instead of section 2.2 while registration is CLOSED and there are NO real bookings; the pages are written to cope with the database being a step behind):**
>   1. Run the nightly snapshot workflow by hand (a before-picture).
>   2. In the Supabase SQL editor run, in this order: `r2_01_prep.sql`, `r2_02_lookup.sql`. (From this moment the OLD pages cannot register, because registration now needs an email, so do step 3 straight away.)
>   3. Publish the new `index.html`, `admin/index.html` and `gate/index.html` together.
>   4. Run `r2_02b_cutover.sql`, `r2_03_private_transfer.sql`, `r2_04_public_via_code.sql`, `r2_05_cleanup_and_ip.sql`, `r2_06_transfer_settings.sql` in that order. (`r2_02c` is already applied.) Transfers stay OFF.
>   5. Run the snapshot workflow, rebuild the scratch copy from the NEW snapshot and rerun all six suites: any difference between what was tested and what is live shows here.
>   6. Rehearse on the real site with test data (section 5.4): turn transfers on, run the cases, turn them off; then delete the test data and empty the `payment-proofs` bucket (notes section 11). 7. Restyle last.
>   If real bookings exist or registration is open, do NOT use this order: use the staged order in section 2.2 (registration page first) and pick a quiet moment. Paste every SQL run into `sql/changes.sql`.
> - **Still to do:** the rollout and rehearsal with the owner; check which header carries the real visitor IP (G10, section 3.5 item 1); look at all new screens on a real phone; the restyle ("Midnight Emerald" for admin and gate, ivory/green for public); the About page and logo when the owner sends them; owner decisions in section 8 (defaults in use).
> - **What was NOT verified:** nothing has run on the real Supabase or GitHub Pages; the mocked-browser tests prove the pages call the right functions with the right values and show the right text, not that the real database answers as the scratch copy does (that is what the post-apply snapshot comparison in step (c) is for).


**Project:** Ehsaas'26 meetup registration app (repo `rameezmunirrr-gh/ca-meetup-register`, public, GitHub Pages + Supabase).
**Written:** at the end of one very long session. The notes label that work 16 to 17 Oct 2026; the chat's clock said Friday 23 Oct 2026 when this was written. **Ask the owner today's real situation first (see section 1).**
**Read order:** (1) this file, (2) `PROJECT_NOTES.md` (decisions, database design, change log), (3) the SQL pieces in `sql/` and the tests in `scratch-db/` only when you work on them.

> **What this file is for:** `PROJECT_NOTES.md` is a very good record of decisions and the database design, but it is long (88 KB, 495 lines), organised by history, and it does not contain: the state of each environment, a rollout order, page-by-page change lists, real response examples, how to rebuild the test environment, or the gaps found in the final review. This file adds exactly those. Where the two disagree, trust the **SQL files + tests** first, then this file, then the notes, and tell the owner.

---

## 0. The 60-second summary

- **Done and working on a private test copy of the database (NOT applied to the real Supabase):** the whole backend of "Release 2": ticket lookup by **Booking ID + phone**, **email** per person, **private transfer** (code, money between the two people), **public transfer** (same code flow, money through the organisers), an **IP flag** (flag only), and the clean-up of the old transfer backend. SQL pieces 1 to 5 (7 files counting 2b and 2c), 5 test suites, **478 automated checks** (39 + 54 + 152 + 156 + 77), all passing; the money and security rules were also proven by **deliberately breaking them** (15 of 15 mistakes put into the SQL were caught: 8 for piece 4, 7 for piece 5).
- **Not done at all:** every page. `index.html`, `admin/index.html` and `gate/index.html` are unchanged since Release 1. Nothing in the real database has changed since Release 1 except SQL file `r2_02c` (closes public access to the old transfer functions), which the owner ran and the nightly snapshot confirms.
- **Next job:** (a) a small "piece 6" of SQL (two missing functions, section 6), (b) decide the email-privacy question, (c) update the three pages, (d) apply the SQL in the safe order (section 2), (e) rehearse on the real site, (f) only then the restyle.
- **Owner:** a beginner working alone, in the browser only (GitHub web editor + Supabase SQL editor). Plain language, step by step, complete files, never "just edit line 40".
- **Owner's standing order:** structure and safety first, looks last. No styling until the app is "foolproof and error-proof".

---

## 1. FIRST QUESTIONS TO ASK THE OWNER (before touching anything)

1. **What is today's real situation?** The plan was to open registration on 20 Oct 2026; the owner later said it might be about 25 Oct or another date. Has registration opened to real people? Are there **real bookings** in the database?
   - If **no real bookings and registration is still closed:** follow the rollout plan in section 2.
   - If **real bookings exist or registration is open:** do NOT apply `r2_01_prep.sql` casually. It makes every new registration fail unless the page sends an email (`INVALID_EMAIL`). Use the staged order in section 2 (page first, then SQL) and pick a quiet moment.
2. Has the owner done the Release 1 launch checklist items in notes section 11 (real UPI details entered, ₹1 test payment, test data deleted, gate logins created)?
3. Is the owner fine with the **open decisions** in section 8? Several defaults are in use until answered.
4. Ask which is wanted first: **(A)** pages for the transfer feature, or **(B)** just the registration changes (email, +91, logo placeholder, About link). They can be shipped separately (section 2).

---

## 2. STATE OF EACH ENVIRONMENT, AND THE SAFE ROLLOUT ORDER

### 2.1 State matrix (as of this handover)

| Place | What is there |
|---|---|
| **Live Supabase** | Release 1 applied (payment details in Settings, settings log, staff role fix, etc.) plus `r2_02c`. The **old** transfer backend (3 tables, 22 functions) is still there but closed to the public; `settings.transfers_open` is false. **None of `r2_01`, `r2_02`, `r2_02b`, `r2_03`, `r2_04`, `r2_05` is applied.** The nightly workflow refreshes `sql/schema_snapshot.txt` (the real structure). |
| **Repo `sql/`** | `r2_01_prep.sql`, `r2_02_lookup.sql`, `r2_02b_cutover.sql`, `r2_02c_close_old_transfer_doors.sql` (applied), `r2_03_private_transfer.sql`, `r2_04_public_via_code.sql`, `r2_05_cleanup_and_ip.sql`, `archive/r2_04_admin_matched_NOT_USED.sql` (never apply), plus the owner's `README.md`, `changes.sql`, `schema_snapshot.txt`. |
| **Repo pages** | `index.html` (48 KB), `admin/index.html` (40 KB), `gate/index.html` (18 KB): **unchanged since Release 1.** They still call `lookup_booking` (removed by `r2_02b`) and do not send an email. |
| **Repo `scratch-db/`** | `build.py` (rebuilds a copy of the real database from the snapshot), `lib.py` (test helpers), `gen_r2_01.py`, `gen_r2_03.py`, `gen_r2_05.py` (generate SQL from the real snapshot), `test_r2_01.py` to `test_r2_05.py`, `baseline.py` (obsolete: tested the old backend, now unusable, may be deleted), `archive/` (old test of an abandoned design). |
| **Scratch Postgres (Claude's container, gone after the chat)** | All 7 SQL files applied; tests pass. Rebuild it from the repo (section 9). |

### 2.2 The rollout order (do not change without re-reading this)

The old pages and the new SQL are incompatible in specific ways, so order matters:

| Step | Action | Why it is safe or necessary |
|---|---|---|
| 0 | Run the nightly "schema snapshot" workflow by hand and keep the file (a before-picture). Remind the owner of `sql/changes.sql` (paste every SQL run). | Rollback reference. |
| 1 | **Deploy the registration page** with the email field and fixed +91 (works with the OLD database: the old `submit_booking` ignores the extra `email` key). | Removes the only thing that would break registration when `r2_01` is applied. |
| 2 | Apply **`r2_01`** then **`r2_02`** (adds `lookup_tickets`; does NOT remove `lookup_booking`). | Old pages keep working. Adds the new columns the admin/gate fixes need. |
| 3 | Deploy the **admin and gate fixes** (section 5.2 and 5.3: stop double-counting transferred tickets, ignore transfer bookings in verification and OCR, show email). | Harmless before any transfer exists, required before the first one. |
| 4 | Deploy the **new Tickets page** (Booking ID + phone). Then apply **`r2_02b`** (drops `lookup_booking`). | The old Tickets page dies at step 4's second half; the new one must already be live. |
| 5 | Apply **piece 6** (settings function, info function), **`r2_03`**, **`r2_04`**, **`r2_05`** (this one drops the old transfer backend and adds the IP flag). | Backend complete. `transfers_open` stays **false**. |
| 6 | Deploy the **Transfers tab (admin)** and the **transfer screens (public)**. | Features exist but are off. |
| 7 | Run the rehearsal (section 5.4 and the attack list in the notes, section 12) **on the real site with test data** (transfers on, then off again). Delete all test data (notes section 11). | Proof on the real thing. |
| 8 | Turn `transfers_open` on; only then, and only after everything is risk-proof, **restyle**. | Owner's order. |

After every SQL run: run the snapshot workflow, then rebuild the scratch copy **from the new snapshot** and rerun all suites (the final proof that the real database equals what was tested).

---

## 3. THE TRANSFER CASE, EXPLAINED IN FULL

### 3.1 The idea in plain words

The meetup is limited to a hall of 150. People cannot get refunds, only **transfers**: a ticket holder who cannot come hands the seat to someone else. The organisers handle this by **phone**; the app records it and makes it safe. There are two kinds, but one single flow of screens:

- **Private transfer:** the two people already know each other. Money is settled **between them**; the organisers are never involved in money.
- **Public transfer:** the seller has no buyer. The organisers find one, collect the money, and pay the seller. They are intermediaries.

**The same code flow serves both.** The seller fills a form and gets a short **code**. Someone gives that code to a buyer (the seller themself in a private case; an admin in a public case). The buyer types the code, fills a Transfer Form, and gets a **new Booking ID**. An admin phones the **seller's registered number** (this call is the real identity check), ticks a box, and presses **Transfer**. In one database step the seller's ticket is cancelled and a new ticket is issued to the buyer. The number of people in the hall never changes.

### 3.2 The objects involved

| Thing | Meaning |
|---|---|
| `transfers` | One sale of one seat. Columns: `kind` (`private`/`public`), `status`, `code`, `code_expires_at`, seller snapshot (`seller_name`, `seller_phone`), call tick (`seller_call_confirmed_at/by`), and for **public**: `seller_upi`, `amount_due`, `payment_requested_*`, `payment_screenshot_path`, `payment_submitted_at`, `payment_verified_*`, `amount_received`, `seller_paid_*`, `payout_reference`, `return_due`, `returned_*`, `return_reference`. Admin-read-only. |
| `transfer_buyers` | The buyer's form (name, phone, email, location, attendance, food, consent, `booking_id`). Admin-read-only. |
| `bookings.kind` | `registration` (normal) or `transfer` (a buyer's booking: **amount 0, no screenshot, no ticket until approved**, never counts as a seat or as income). |
| `tickets.transferred_out_at` | Set on the seller's ticket when it is transferred away. The row **stays**, with its number retired forever. **Every count of people must ignore rows where this is set.** |
| `tickets.transferred_from` | On the buyer's new ticket: points to the seller's old ticket. Used by the gate to follow a seat that moved more than once. |
| `tickets.email` | New, required for new registrations. |
| `booking_ips` | Admin-only IP per registration (flag only). |
| `settings_log` | Every transfer step is written here (`area = 'transfer'`), with who did it, never with phones, emails, UPI IDs or QR secrets. |

**`transfers.status` values in use:** `code_active` (seller made a code, no buyer yet), `pending_admin` (buyer applied, waiting for the admin), `done`, `rejected`, `withdrawn` (closed automatically, e.g. the seller's booking was rejected), `replaced` (a newer code for the same seat). Only one of `code_active`/`pending_admin` can exist per seat (database-enforced).

**`transfer_buyers.status`:** `active` (applied) → `done` / `rejected` / `released`.

### 3.3 Who can do what (permissions)

- **Visitors (no login):** only the functions in section 7.1. They can never read any table.
- **Gate staff:** can read `tickets`/`bookings` (existing rule) and use `admit_ticket`. They see **zero rows** of the new transfer tables and of `booking_ips`.
- **Admins:** read all transfer tables and call the `admin_*` functions. **One admin will do the transfer work in practice; every admin has the authority.** Every admin function checks `is_admin()` itself.

### 3.4 Scenarios (each lists what happens, what changes, what the screens must show)

**S1. Private transfer, normal case** (money between seller and buyer)
1. *Seller* (Asha, ticket E26-001, Booking ID `A`, phone P1) opens Tickets, Transfer tickets, Private, **Sell**, enters Booking ID + ticket number + phone. `private_sell` creates a `transfers` row (`private`, `code_active`, code valid `private_code_hours`, default 2 h). Screen: the 6-character code and when it expires (alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`: no 0, O, 1, I).
2. Asha tells the buyer the code by herself (WhatsApp, etc.).
3. *Buyer* opens Private, **Buy**, types the code: `transfer_open` returns `{ok, mode:'private', seller_name, expires_at, food_locked, food}`. The buyer fills the Transfer Form (name, phone, email, location, attendance, food, consent tick that money is between the two people) and sends `transfer_submit`. Result: a **new Booking ID** (kind `transfer`, pending), the transfer becomes `pending_admin`. Screen: "The organizers will be notified…", the Booking ID (saved on the device), a Contact now button. **No ticket, no seat, no change to any count yet.**
4. *Admin* sees the pending transfer: the original ticket beside the buyer's details. Phones the **seller's registered number** (not the number typed in any form): "Shall I transfer this ticket to Mr. B? We assume the payment is settled between you." Ticks the box (`admin_transfer_confirm_call`).
5. *Admin* presses **Transfer** (`admin_transfer_approve`). One transaction: re-checks the seller's ticket is still valid and **not checked in**; creates the buyer's ticket with the **next guest number** and a new QR secret in the buyer's booking; sets the seller's ticket `transferred_out_at`; marks the buyer's booking paid and numbers it with the normal rule; transfer becomes `done`; writes the log.
6. Result: seller's lookup shows the ticket as transferred (no QR); buyer's lookup shows the new ticket; the gate shows the old QR as CANCELLED (naming the current holder); all counts unchanged.

**S2. Public transfer, normal case** (money through the organisers)
1. *Seller* chooses Public, **Sell**: Booking ID, ticket, phone **and payout UPI ID** (or 10-digit phone). **No price.** `public_sell` makes a `public` code (same lifetime rules).
2. *Admin* sees every active code in the Transfers tab (both kinds). The seller usually contacts the admin; the admin finds a buyer and gives them the code. If finding a buyer takes days the admin **extends** the code (`admin_transfer_extend_code`, 1 to 168 hours; also revives an expired code).
3. *Buyer* types the code and fills the Transfer Form (no payment yet). Gets a new Booking ID; the buyer's status page shows "pending".
4. *Admin* phones the seller (is the ticket still theirs? reads back the payout UPI ID), ticks the call, presses **Ask buyer to pay** (`admin_transfer_request_payment`). `amount_due` is fixed to the standard `price_per_head` at that moment.
5. *Buyer's* status page (Booking ID + phone) now shows **Pay ₹X** with the UPI QR (from `get_payment_info`) and a screenshot upload. The page uploads the image to the `payment-proofs` bucket as `<submission_id>.jpg` and calls `transfer_pay`.
6. *Admin* checks the bank and enters the amount **actually received** (any amount from 1 to 1,000,000; more or less than asked is fine): `admin_transfer_verify_payment`.
7. *Admin* presses **Transfer**: needs **both** the call tick **and** the verified payment. Same swap as S1.
8. *Admin* pays the seller **exactly the amount received** and marks it with a reference (`admin_transfer_mark_paid`).
9. The **Transfer money panel** (`admin_transfer_money`) shows: awaiting payment, awaiting verification, verified and waiting for Transfer, to pay out, paid out, return due, returned, **held now**. The buyer's money never enters the registration revenue (their booking has amount 0).

**S3. Public transfer fails after the buyer paid** (the money must go back)
- *Cases:* the seller walked into the hall (Transfer refused: `SELLER_CHECKED_IN`), the seller's booking was rejected by an admin (the transfer closes **automatically**), the admin rejects it (wrong person, seller unreachable), the amount is wrong.
- *What happens:* `admin_transfer_reject` (or the automatic close) sets `return_due = true` **if a screenshot was uploaded**. The panel shows it under "return due". The admin sends the money back and records it with `admin_transfer_mark_returned(transfer, reference)` (a reference like "no money received" is acceptable). The buyer's page shows `return_due` then `returned`. The seller's seat is untouched and they can start a new transfer.
- *If the buyer never uploaded a screenshot:* no return is created.

**S4. The hall is full** (the normal reason transfers exist)
- Registrations are refused (`NOT_ENOUGH_SPOTS`), but a transfer is a **swap**, not a new seat, so it must always work. Tested: with the cap reached, Transfer works and the hall stays exactly as full; a normal registration is still refused afterwards.

**S5. A seat moves twice or more.** The buyer has a Booking ID, ticket number and phone, so they can sell on like any ticket (owner's decision). The old tickets keep their retired numbers; the gate follows `transferred_from` links to name the **current** holder.

**S6. Code problems.** A second request for the same seat **replaces** the old code (the old one stops working, even across private/public). The seller can cancel an active code (`transfer_cancel`); once a buyer applied only an admin can end it (`CONTACT_ADMIN`). Wrong, expired, used, replaced or cancelled codes all answer exactly `INVALID_CODE`. Two buyers racing for one code: the first valid submission wins (tested with 8 at once). The same form sent twice returns the same Booking ID.

**S7. Rules that block a transfer** (shown to the seller only after the three details matched): `NOT_CONFIRMED` (booking not paid), `ALREADY_CHECKED_IN`, `ALREADY_TRANSFERRED`, `COORDINATOR` (coordinator tickets cannot be sold through the website; the admin handles them; **open decision**), `TRANSFERS_CLOSED`, `CUTOFF_PASSED` (after `transfer_cutoff_at` no new code, buyer form or payment upload; admin actions on existing transfers continue). A seller with wrong details always gets exactly `MISMATCH` and learns nothing.

**S8. Food lock.** Once the food order is placed the admin turns on `transfer_food_locked`: the form hides the food choice and the buyer gets the **seller's** food.

**S9. Gate day.** `admit_ticket` on a transferred-out ticket returns `cancelled` with the **current holder's name and ticket label** and the old label. The new ticket admits once, then `already_scanned`. Gate staff searching by name can still find retired tickets (see 5.3).

**S10. Abuse and mistakes.** Seller and buyer never see each other's phone, email, Booking ID or ticket number (the seller sees the buyer's **name** after they applied; the buyer sees the seller's **name** when the form opens). Guessing: Booking ID (8 hex) + phone, or a 6-character code (about a billion combinations), is not throttled by owner's decision because the admin's phone call to the seller stops a wrong taker. IP flag: registrations record the visitor's address; admin sees addresses with 5 or more registrations; **never blocks**.

**S11. Cleaning test data before launch.** Transfer rows are removed with their tickets/bookings by foreign keys; `settings_log` is not cleared (fine); also empty the `payment-proofs` bucket. `admin_clear_client_ips()` deletes all stored IPs after the event.

### 3.5 What exactly the next session must INVESTIGATE (on the real system, not assumed)

1. **Which header holds the real visitor IP** on Supabase (`cf=` vs `xff=` in `booking_ips.raw`): one registration from mobile data, one from WiFi, read `select ip, raw from booking_ips order by created_at desc limit 5;`. A client can fake `x-forwarded-for`; the code prefers `cf-connecting-ip` and otherwise the **last** address. Adjust `_client_ip()` if the real data says otherwise.
2. **The real permissions of the existing tables** (`settings`, `bookings`, `tickets`): the scratch copy rebuilds tables, functions and triggers from the snapshot but **does not reproduce table grants or row-level-security policies of the OLD tables** (it sets them explicitly only for the NEW tables). Read the policies in `sql/schema_snapshot.txt` before trusting any statement about who can read what (this matters for the email question, section 6).
3. **After applying the SQL:** run the snapshot workflow, rebuild the scratch copy from the **new** snapshot, rerun all five suites. Any difference between "what I tested" and "what is live" shows up here.
4. **Screenshot upload for `transfer_pay`:** confirm on the real site that a visitor can upload the file (the bucket allows anonymous upload) and that an admin can open it with the usual signed link (the admin page's existing screenshot viewer reads `bookings.screenshot_path`; the transfer screenshot lives in `transfers.payment_screenshot_path`, so the viewer needs a second source).
5. **Real browsers:** the QR scanner, PDF/JPG downloads and the UPI QR were built and tested in Release 1; re-test the Tickets page after the rewrite on a phone (Android and iPhone Safari if possible).
6. **Headless-browser test tooling:** the notes say page changes were checked "in a headless browser with a mocked Supabase" (Overview numbers and the daily-pause feature, 14 Oct 2026). The tool was not recorded. Check what exists (`pip list`, `npm ls -g`, `playwright`, `puppeteer`, `jsdom`); if nothing, install (pypi/npm are allowed in the container) and **record the method in the notes** this time.

---

## 4. MASTER LIST: WHAT STILL HAS TO BE BUILT OR CHANGED

| # | Item | Where | Size | Blocks |
|---|---|---|---|---|
| 1 | **Piece 6 SQL**: `admin_set_transfer_settings(...)` and `get_transfer_info()` (gaps G1 and G2) plus tests | `sql/r2_06_*.sql`, `gen`/test files | small | admin Settings tab, public menu |
| 2 | Decide the **email privacy** approach (gap G3), then adjust pieces 1, 3, 4 and tests if a separate table is chosen | `r2_01`, `r2_03`, `r2_04` | small to medium | applying `r2_01` |
| 3 | **Registration page**: email, fixed +91, logo placeholders, About link | `index.html` | medium | step 1 of rollout |
| 4 | **Admin page**: fix double counting, exclude transfer bookings from verification/OCR, email column, Settings section, new **Transfers tab**, money panel, IP flags | `admin/index.html` | large | steps 3 and 6 |
| 5 | **Gate page**: counters and search ignore retired tickets | `gate/index.html` | small | step 3 |
| 6 | **Tickets page rewrite** (Booking ID + phone, saved IDs as chips) and **transfer screens** (Sell private/public, status, Buy, Transfer Form, Pay) | `index.html` | large | steps 4 and 6 |
| 7 | **Rollout** in the order of section 2.2 with the owner (Supabase SQL editor + GitHub uploads) | owner + Claude | small | |
| 8 | **Rehearsal** on the real site with test data, then clean up | owner + Claude | medium | opening transfers |
| 9 | Update `PROJECT_NOTES.md` (state, changelog) after every step; refresh `sql/changes.sql` | repo | small | |
| 10 | **Restyle** (palette decided in notes section 12) only after 8 | all pages | medium | owner's order |
| 11 | **About page** content (owner will send text, reel links, photos) | `index.html` | medium | later |

---

## 5. PAGE-BY-PAGE CHANGE SPECIFICATION

All three pages are single HTML files with inline JavaScript and the Supabase client `db`. They draw their views by building HTML strings (`vHome`, `vForm`, `vSummary`, `vPay`, `vDone`, `vTickets`, `vTicket` in `index.html`; `view()`, `vOverview()` and friends in admin). Keep that style. Never put secrets in them (only the public `anon` key is there by design).

### 5.1 `index.html` (public page)

**Registration form**
- Add an **Email** field per person (asked after the name and the other personal details, as the owner wants). Required, trimmed, lower-cased, basic format check; send it as `email` in every object of `p_people` (the database refuses a booking without it once `r2_01` is applied: `INVALID_EMAIL`). Add one line saying why it is collected (event updates and ticket recovery).
- **Phone:** at *every* phone field show a fixed, uneditable **"+91"**; the user types 10 digits; send 10 digits only. The database stores exactly 10 digits and refuses anything else.
- **Logo:** put placeholders where the owner wants the Mallu Articles Bengaluru logo (header, maybe the ticket); the owner will send the file (SVG or transparent PNG). Do not invent a logo.
- **"About Mallu Articles Bengaluru":** a new link beside "Register for meetup" and "Tickets" on the home view; a placeholder page for now. Content (text, last year's reels as plain links with thumbnails rather than embeds, photos; ask permission for photos with faces) will be discussed later.

**Tickets page (rewrite)**: today `fetchBooking(code)` (about line 350) calls `lookup_booking(p_code)` and the page **automatically refetches every saved Booking ID** when it opens. localStorage holds `mm_mine` (bookings made on this device, up to 20, saved at about line 500), `mm_hist` (codes searched, up to 10, about line 362) and `mm_last` (the latest). The Tickets view (about line 338) keeps `S.tk.search = {code, nf}` for a not-found state. That conflicts with the new rule. New behaviour (owner's words: "the booking ID registered in that phone stays as history; but you have to type the phone number always"):
- Saved Booking IDs are shown as **tappable chips** (history). Tapping one fills the Booking ID box.
- A **phone** box with fixed "+91" is always typed. Never store the phone in localStorage.
- Button "Check" calls `lookup_tickets(p_code, p_phone)`.
- `{found:false}` → one generic message ("No ticket found for these details"); never say which part was wrong.
- Success → the same booking card as today (status, people, amount, the matching person's tickets with QR/PDF/JPG), now with: tickets whose phone matches only; a ticket with `transferred:true` shown as "Transferred" with no QR; a booking with `kind:'transfer'` shows the transfer state (section 3.4, S1/S2).
- Keep: no Booking ID drawn on the ticket image, heading or PDF name (Release 1 decision).

**New transfer screens** (only when `get_transfer_info().open`, gap G2): Tickets, **Transfer tickets**, then Private or Public, then Sell or Buy.
- *Sell (private):* Booking ID (chips), ticket number, phone → `private_sell` → show the code, the expiry time, a copy button, and "Check my transfer"/"Cancel code" (`transfer_status`, `transfer_cancel`).
- *Sell (public):* same plus the payout UPI ID (or 10-digit phone) → `public_sell`.
- *Buy:* a code box → `transfer_open` → show "Buying <seller_name>'s ticket" and the **Transfer Form** for ONE person (name, phone with +91, email, location, attendance, food (hidden when `food_locked`), consent tick; private text: payment is between the two of you; public text: the organisers will ask you to pay the standard price after confirming) → `transfer_submit(code, submission_id, buyer)`. Keep one `submission_id` per form so a retry returns the same Booking ID. Save the new Booking ID into `mm_mine`. Show "The organizers (admins) will be notified of this request, and will take necessary actions soon" and a **Contact now** button (WhatsApp, number from `get_payment_info`).
- *Status for a transfer booking* (via Tickets, Booking ID + the buyer's phone): states `pending`, `payment_due` (show amount, UPI QR from `get_payment_info`, screenshot upload; compress and upload to the `payment-proofs` bucket named `<submission_id>.jpg`, then `transfer_pay`), `payment_submitted`, `payment_verified`, `rejected`, `return_due`, `returned`, or the finished ticket.
- Map **every error code** in Appendix A to a plain sentence. Never show raw codes.
- Transfers are **not** tied to the daily registration pause (ask the owner if they should be).

### 5.2 `admin/index.html`

`load()` reads `bookings`, `tickets`, `screenshot_scans`, `settings` and `settings_log` with direct selects (allowed by row-level security). Counts and lists are computed **in the browser** from `people()` (about line 85) and `S.bookings`, which is why these fixes are mandatory **before the first transfer**:

1. **Stop double counting.** After a transfer both the seller's retired ticket (booking still `paid`) and the buyer's new ticket exist. Everything computed from `people()` (Overview: confirmed, pending, spots used and left, food and location splits, charts) must **ignore rows with `transferred_out_at`**. Verify the Overview "spots" equals `get_public_status().spots_left`.
2. **Bookings tab / verification / OCR:** transfer bookings (`kind = 'transfer'`) have no screenshot and cannot be verified here (`set_booking_status` refuses them with `USE_TRANSFER_TOOLS`). Exclude them from the pending list, the Paid/Reject buttons and the "Scan screenshots" queue; they live in the Transfers tab.
3. **People tab:** add an **Email** column and put it in the CSV export; show retired tickets greyed as "Transferred" (or hide behind a toggle).
4. **Settings tab:** a new "Transfers" section: `transfers_open` (with a warning "keep off until tested"), `transfer_cutoff_at`, `transfer_food_locked`, `private_code_hours` (1 to 168), `ip_flag_threshold` (2 to 1000). Needs piece 6's `admin_set_transfer_settings` (gap G1). The settings log view already shows changes.
5. **New Transfers tab** (read `transfers`, `transfer_buyers`; call `admin_transfer_money()`):
   - *Active codes:* table of codes of both kinds: seller name and ticket label, mode, created, expires (flag EXPIRED), buttons **Extend** (hours) and **Cancel** (`admin_transfer_reject`).
   - *Waiting for the admin:* one card per `pending_admin` transfer: the original ticket (name, phone, ticket label, booking) beside the buyer (name, phone, email, location, attendance, food); for public also the seller's payout UPI (to read back on the call), `amount_due`, and the payment screenshot (signed link built from `transfers.payment_screenshot_path`, same helper as booking screenshots). Buttons in order: **tick "I phoned the seller's registered number"** → (public) **Ask buyer to pay** → (public) **Amount received [ ] Verify** → **Transfer** → **Reject** with a note. Disable buttons to mirror the rules, but the database is the real guard: show its error text.
   - *After Transfer (public):* "To pay out" list with a **Mark seller paid** box (reference 3 to 80 characters); "Return due" list with **Mark returned** (reference).
   - *Money panel:* the seven numbers and "held now" from `admin_transfer_money()`.
   - *Flags:* show the age of each pending item; highlight transfers waiting a long time (nothing expires automatically).
   - Include the phone-call wording for the admin on screen (S1/S2).
6. **IP flags:** a banner from `admin_ip_flags()` and a small mark on bookings listed in `by_booking`; a "delete stored addresses" button (`admin_clear_client_ips`) with a confirmation, for after the event.

### 5.3 `gate/index.html`

Counts are computed in the browser from a **fixed column list** (about line 73: `ticket_no, coord_no, kind, name, phone, food, booking_id, checked_in_at, reg_seq`):
1. Add `transferred_out_at` to the select and to the filters: `P = tickets.filter(booking paid and not transferred_out_at)` (about line 78). Otherwise "Present / Confirmed" and the Veg / Non-veg numbers count both the seller and the buyer.
2. **Search results** (about line 102): hide retired tickets or show them with a grey "Transferred" pill and no Admit button (scanning one already returns CANCELLED).
3. Confirm the **cancelled** result screen shows `name`, `label` and `old_label`; the database now returns exactly those keys for a retired ticket (also for a seat that moved twice).
4. The gate keeps working with no change to how it scans.

### 5.4 The rehearsal (what to prove on the real site, with test data)

Run the notes' section 12 attack list **on the real site** and also: private and public happy paths; hall full (set the cap to the current count, then Transfer); the seller admitted at the gate between application and Transfer; the seller's booking rejected while a transfer is pending; payment wrong amount; return and payout recorded; counts on admin and gate unchanged by every Transfer; old QR scanned = cancelled, new QR = admitted once; `transfers_open` off blocks everything; cut-off date blocks new codes only; then **delete all test data and empty the bucket**.

---

## 6. GAPS AND RISKS FOUND IN THE FINAL REVIEW

| ID | Finding | Why it matters | Proposed action |
|---|---|---|---|
| **G1** | **No function can change the new settings.** The old `admin_set_transfer_settings` was dropped in `r2_05`; `admin_update_settings` has only cap, price, deadline, open flag and the pause fields; nobody can write tables directly (**confirmed in the snapshot:** logged-in users have SELECT only on every table). | The admin cannot turn transfers on, set the cut-off, lock the food or change the code lifetime from the app. | **Piece 6:** `admin_set_transfer_settings(p_open boolean default null, p_cutoff timestamptz default null, p_clear_cutoff boolean default false, p_food_locked boolean default null, p_code_hours integer default null, p_ip_threshold integer default null)`, admin-only, validated; the existing settings-log trigger logs it. Test: non-admin refused, bad values refused, each setting changes, log row written. |
| **G2** | **No visitor-readable "are transfers open".** | The public page cannot hide the Transfer menu or the food field, or show the standard price. | **Piece 6:** `get_transfer_info()` for visitors returning `{open, cutoff_at, cutoff_passed, food_locked, code_hours, ask_price}` (no secrets). |
| **G3** | **`tickets.email` is readable by every staff login.** Existing rule: any staff (including gate volunteers) can `select` from `tickets` (**confirmed in the snapshot:** policy `staff_read_tickets` is `using is_staff()`, so any logged-in staff can read every column). The notes promise "readable by admins only". The gate page itself does not request email, but a volunteer could query it. | Privacy promise vs reality. | Ask the owner. Options: (a) accept and tell them; (b) **recommended**: keep emails in a separate admin-only table `ticket_emails(ticket_id, email)` written by `submit_booking` and the Transfer function, read by admins only (changes pieces 1, 3, 4, the `report` view, the People tab and the tests; cheap now because nothing is applied yet); (c) column-level privileges (fragile when columns are added). |
| **G4** | Admin and gate pages double-count after a transfer (5.2 and 5.3). | Wrong live numbers at the event. | Fix in steps 3 of the rollout. |
| **G5** | Admin Bookings/OCR will list transfer bookings (no screenshot; verification buttons fail). | Confusing errors for the admin. | 5.2 point 2. |
| **G6** | The Tickets page auto-fetches every saved Booking ID. | Incompatible with Booking ID + phone. | 5.1. |
| **G7** | Wrong rollout order breaks things (`r2_01` before the email page; `r2_02b` before the new Tickets page; transfer SQL before the admin/gate count fixes). | Live outage or wrong counts. | Section 2.2. |
| **G8** | The scratch copy does not reproduce grants and RLS of the **old** tables. | Tests alone do not prove "who can read what" for existing tables. | **The snapshot does list them** (sections ROW LEVEL SECURITY, POLICIES, TABLE AND VIEW PERMISSIONS). Read in this review: logged-in users have only SELECT on all tables; `bookings`, `tickets`, `settings`, `screenshot_scans` are readable by any staff (`is_staff()`); `settings_log`, the old transfer tables and `staff` (own row, or admin) are admin-limited; storage: staff read and anyone uploads to `payment-proofs`. Re-read the policies in the snapshot; after applying SQL rebuild the copy from the new snapshot. |
| **G9** | `_ticket_label` is callable by anyone (inherited grant). | Pure formatting function: harmless. | Optionally revoke. |
| **G10** | Which header carries the real IP is unverified. | The IP flag could point at a proxy address. | 3.5 item 1. |
| **G11** | `scratch-db/baseline.py` tests the removed old backend and no longer runs. | Clutter. | Delete. |
| **G12** | Pending transfers never expire by themselves (owner prefers manual). | Forgotten items. | Show age and highlight in the Transfers tab. |
| **G13** | Coordinator and free tickets cannot be sold through the website. | A coordinator who cannot come needs another path. | Owner decision; the admin can use the existing coordinator tools manually. |
| **G14** | A "before" picture and a rollback path are not written down for the owner. | A mistaken SQL run is hard to undo. | Section 2.2 step 0; ask the owner to keep copies of the SQL they run in `sql/changes.sql`. |

---

## 7. API REFERENCE (built from the final SQL; real response examples in Appendix B)

### 7.1 Visitor functions (anyone with the public key)

Seller/buyer functions never raise for user mistakes; they **return** `{ok:false, error:'CODE'}` (so the page has one shape). Lookups return `{found:false}` for every kind of wrong input.

| Function | Parameters | Success |
|---|---|---|
| `get_public_status(p_session)` | session uuid or null | registration state, spots left (unchanged) |
| `get_payment_info()` | | UPI id, payee name, WhatsApp number (null parts = not set up) |
| `get_event_info()` | | `event_at`, `venue` |
| `registration_heartbeat(p_session)` | | unchanged (daily pause logic) |
| `submit_booking(p_submission_id, p_people jsonb, p_screenshot_path)` | people: 1 to 5 objects with `name, phone(10 digits), email, loc, att, food` | the booking (code, status, tickets); **raises** on invalid input (Appendix A) |
| `lookup_tickets(p_code, p_phone)` | Booking ID + 10-digit phone | `{found:true, kind, booking_code, status, people_count, amount_expected, tickets:[...]}`; for a transfer booking also `transfer:{type, state, amount_due}` |
| `private_sell(p_booking_code, p_ticket, p_phone)` | ticket like `E26-001` | `{ok, code, expires_at, hours, ticket_label}` |
| `public_sell(p_booking_code, p_ticket, p_phone, p_upi)` | + payout UPI/phone | `{ok, mode:'public', code, expires_at, hours, ticket_label}` |
| `transfer_status(p_booking_code, p_phone)` | the seller | `{found, transfers:[{ticket_label, mode, status, code?, expires_at?, buyer_name?, payout?, amount_to_receive?}]}` |
| `transfer_cancel(p_booking_code, p_ticket, p_phone)` | the seller | `{ok}`; `CONTACT_ADMIN` once a buyer applied |
| `transfer_open(p_code)` | the buyer | `{ok, mode, seller_name, expires_at, food_locked, food?}` |
| `transfer_submit(p_code, p_submission_id, p_buyer jsonb)` | buyer: `name, phone, email, loc, att, food (ignored when locked), consent:'true'` | `{ok, mode, booking_code, status:'pending', seller_name, food}` |
| `transfer_pay(p_booking_code, p_phone, p_submission_id, p_screenshot_path)` | public buyer, after payment was requested | `{ok, amount_due}` |

### 7.2 Staff and admin functions (login required; each checks the role inside)

`admit_ticket`, `undo_checkin`, `set_booking_status`, `set_coordinator`, `save_scan` (existing); `admin_update_settings`, `admin_set_event`, `admin_set_payment_info`, `admin_payment_alert`, `admin_registration_status` (Release 1); **new:** `admin_transfer_confirm_call(id, bool)`, `admin_transfer_extend_code(id, hours)`, `admin_transfer_request_payment(id)`, `admin_transfer_verify_payment(id, amount)`, `admin_transfer_approve(id)`, `admin_transfer_reject(id, note)`, `admin_transfer_mark_paid(id, reference)`, `admin_transfer_mark_returned(id, reference)`, `admin_transfer_money()`, `admin_ip_flags()`, `admin_clear_client_ips()`. Admin functions **raise** an exception whose message is the error code (Appendix A).

### 7.3 Rules the database enforces that the page need not repeat (but should mirror)

One open transfer per seat; a code is unique among active codes; Transfer needs the call tick (and, for public, a verified payment); the seller's ticket must be paid, a guest ticket, not checked in and not already transferred; a transfer booking never counts as a seat or as income; the swap uses the normal numbering rule (`_assign_numbers`) and never reuses a number; the cap is never checked at Transfer (it is a swap).

---

## 8. OPEN DECISIONS (defaults in use until the owner answers)

1. **Money returned to the buyer when a public transfer fails after they paid** (built; normal registrations stay no-refund). Owner to confirm.
2. **Coordinator and free tickets** cannot be sold through the website (default).
3. **What each side sees:** seller sees the buyer's name after they applied; buyer sees the seller's name when the form opens (default).
4. **Code lifetime:** default 2 hours, setting up to 168, admin can extend (assumed by Claude; confirm).
5. **Email privacy** (G3): accept, separate table, or column privileges.
6. **Anti-spam options still undecided:** one open booking per phone, a limit on spots held by pending bookings, a minimum time on the form, a "reject all pending from this phone" button, cleanup of rejected screenshots. (The IP flag is built: flag only.)
7. **Registration opening date** and whether registration is already open.
8. **Daily registration pause** and transfers: should transfers pause too? (default: no)
9. **How long a pending transfer may wait** (default: no limit; show age).
10. **About page content and the logo file** (owner will send).
11. After the event: run `admin_clear_client_ips()` (owner to remember).

---

## 9. ENVIRONMENT: REBUILD THE TEST SETUP IN A NEW CHAT (about 10 minutes)

Claude's container is wiped between chats; everything needed is in the repo. Run with **bash** (the default `sh` does not support `<( )`). `github.com`, `codeload.github.com`, `raw.githubusercontent.com`, `api.github.com`, PyPI and npm are reachable; the GitHub API is rate-limited, so use the zip.

```bash
mkdir -p /home/claude && cd /home/claude
curl -sL -o repo.zip https://codeload.github.com/rameezmunirrr-gh/ca-meetup-register/zip/refs/heads/main && unzip -q -o repo.zip && rm -rf repo && mv ca-meetup-register-main repo
mkdir -p sql scratch
cp repo/sql/schema_snapshot.txt sql/                 # the TRUTH about the live database
cp repo/sql/r2_0*.sql scratch/                       # the pieces
cp repo/scratch-db/*.py scratch/                     # builder, helpers, generators, tests (paths are hardcoded to /home/claude/scratch and /home/claude/sql)
apt-get update -qq; apt-get install -y -qq postgresql   # the nodesource warning is harmless
pip install -q psycopg2-binary --break-system-packages
rm -rf /tmp/pgdata && mkdir /tmp/pgdata && chown postgres /tmp/pgdata
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /tmp/pgdata -A trust >/dev/null"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgdata -o '-p 5544 -k /tmp' -l /tmp/pg.log start"
cd scratch && python3 build.py          # rebuilds an empty copy of the live database from the snapshot (writes build.sql)
for n in 01 02 03 04 05; do python3 test_r2_$n.py | tail -1; done   # expect 39, 54, 152, 156, 77 passed
```

**How the harness works** (`lib.py`): `fresh([sql files])` rebuilds the database from `build.sql` and applies the given files; `seed()` makes an open event, one admin, booking A (Asha 9000000001 and Ben 9000000002) and booking B (Carl 9000000003), all paid; `call(role, sql, params, uid, headers)` runs one statement as `anon`, `authenticated` (with `uid` as the logged-in user) or `postgres`; `call_new` + `par` run statements at the same instant on separate connections (race tests); `sql()` runs as superuser; `T` collects PASS/FAIL, and **a script that crashes halfway counts as a failure**. `ensure_server()` restarts Postgres if it stopped (it stops between chat steps).

**Replica quirks (already patched in `lib.fresh`):** `settings_log.id` and `tickets.reg_seq` are identity columns in production but the snapshot does not show it; `report` is a view; `storage.objects` is a stub with `bucket_id, name`; roles `anon/authenticated/service_role` and `auth.uid()` are stand-ins (the user id comes from `request.jwt.claim.sub`); request headers come from `request.headers`. **Not reproduced:** grants and row-level-security of the old tables (G8).

**Gotchas that cost time before:** in `psycopg2`, a literal `%` in a statement that has parameters must be written `%%`; `ON_ERROR_STOP` makes a failing SQL file stop `fresh()`; the first pass of function creation may report an ordering error that the second pass fixes (expected); Python test values for uuid columns come back as strings; run two tests that change settings in the same scenario carefully (they share state).

**The pattern for new SQL:** generate it **from the real snapshot** (`gen_r2_0X.py` extract the real function text and patch only the needed lines, asserting each patch applies exactly once) so nothing else drifts; apply on the scratch copy; write the tests **first as attacks**; then run **deliberate-mistake checks**: copy the SQL, break one rule (delete a check, forget a flag), run the suite on the copy, and confirm it fails (this found two real test gaps; a green run alone proves little). Save outputs under `/mnt/user-data/outputs` and present them with `present_files`.

**After any SQL goes live:** run the snapshot workflow, then rebuild from the new snapshot and rerun all suites; append the SQL to `sql/changes.sql`.

---

## 10. HOW TO WORK WITH THIS OWNER (from the notes and this session)

- Plain language, short steps, no jargon; they are a beginner. Give **complete files to paste**, never partial edits.
- **Ask before changing behaviour** they decided. Record every decision in `PROJECT_NOTES.md` (decisions, changelog). State assumptions plainly.
- Safety over speed; no styling until the app is proven risk-proof; no deadline pressure on Claude.
- Never include secrets, keys, real phone numbers or UPI IDs in files.
- **GitHub web editor pitfalls seen:** upload files from inside the right folder and drag **files, not folders**; a dragged `archive` folder mixed files into the wrong folders last time; to move a file, edit it and delete one folder name from the path box. **Always verify** by downloading the repo zip and comparing with the delivered files (the check script is simple: walk both trees, compare bytes ignoring line endings).
- The owner only has the browser: SQL goes into the Supabase SQL editor; tell them exactly where to click and what "Success" looks like.
- Credits matter to the owner: batch tool calls, avoid re-reading big files, finish a step and record it.

---

## 11. THE NEXT SESSION'S TASK LIST (in order, with "done when")

1. **Ask the section-1 questions.** Done when the real state and opening date are known.
2. **Rebuild the test setup (section 9)** and confirm the five suites give 39/54/152/156/77. Done when all pass.
3. **Piece 6 SQL** (G1, G2) with tests and a deliberate-mistake check; add to the repo. Done when tests pass and the file is in `sql/`.
4. **Email privacy decision** (G3); implement the chosen option in pieces 1/3/4 if needed. Done when the suites pass again and notes are updated.
5. **Registration page** (5.1 first part) tested in a headless browser with a mocked Supabase, then deliver to the owner. Done when a registration with email and +91 works against the old and new database shapes.
6. **Admin and gate fixes** (5.2 points 1 to 3, 5.3). Done when counts stay equal to `get_public_status` after a simulated transfer.
7. **Tickets page rewrite** (5.1). Done when lookup by Booking ID + phone works and saved IDs are chips.
8. **Rollout steps 0 to 4** with the owner. Verify with a repo download and a fresh snapshot.
9. **Admin Settings section and the Transfers tab** (5.2), then **public transfer screens** (5.1), mocked-browser tests, then rollout steps 5 and 6.
10. **Rehearsal** (5.4), cleanup, then the owner turns transfers on.
11. **Restyle** (palette "Midnight Emerald" in the notes), re-test everything.
12. **About page** when the owner sends content.

After each task: update `PROJECT_NOTES.md` (changelog + status) and say plainly what was **not** verified.

---

## 12. GLOSSARY

- **Seller / transferor:** the ticket holder giving up the seat. **Buyer / transferee:** the person receiving it.
- **Code:** 6 characters the seller gets; whoever has it can open the Transfer Form.
- **Call tick:** the admin's confirmation that they phoned the number registered on the original ticket; the real identity check, required before Transfer.
- **Transfer (button):** `admin_transfer_approve`, the swap.
- **Retired ticket:** the seller's ticket after transfer (`transferred_out_at` set); its number is never reused.
- **Transfer booking:** the buyer's new Booking ID (`kind = 'transfer'`), no seat until approved.
- **Held now / return due / to pay out:** panel terms in `admin_transfer_money()`.
- **Snapshot:** the nightly dump of the real database structure in `sql/schema_snapshot.txt`; the truth for rebuilding the test copy.
- **Piece N:** one SQL file of Release 2 (`r2_0N_*.sql`).

---

## APPENDIX A. ERROR CODES PER FUNCTION (generated from the final SQL; "returns" = `{ok:false,error}`, "raises" = exception text)

| Function | File | Style | Codes |
|---|---|---|---|
| `admin_clear_client_ips` | r2_05_cleanup_and_ip | raises | NOT_ALLOWED |
| `admin_ip_flags` | r2_05_cleanup_and_ip | raises | NOT_ALLOWED |
| `admin_transfer_approve` | r2_04_public_via_code | raises | BUYER_BOOKING_INVALID, CALL_NOT_CONFIRMED, INVALID_TRANSFER, NOT_ALLOWED, NOT_PENDING, NO_BUYER, PAYMENT_NOT_VERIFIED, SELLER_ALREADY_TRANSFERRED, SELLER_CHECKED_IN, SELLER_TICKET_INVALID |
| `admin_transfer_confirm_call` | r2_03_private_transfer | raises | INVALID_TRANSFER, NOT_ALLOWED, NOT_PENDING |
| `admin_transfer_extend_code` | r2_04_public_via_code | raises | INVALID_HOURS, INVALID_TRANSFER, NOT_ACTIVE, NOT_ALLOWED |
| `admin_transfer_mark_paid` | r2_04_public_via_code | raises | ALREADY_PAID, INVALID_REFERENCE, INVALID_TRANSFER, NOT_ALLOWED, NOT_DONE |
| `admin_transfer_mark_returned` | r2_04_public_via_code | raises | ALREADY_RETURNED, INVALID_REFERENCE, INVALID_TRANSFER, NOT_ALLOWED, NO_RETURN_DUE |
| `admin_transfer_money` | r2_04_public_via_code | raises | NOT_ALLOWED |
| `admin_transfer_reject` | r2_04_public_via_code | raises | INVALID_NOTE, INVALID_TRANSFER, NOT_ALLOWED, NOT_PENDING |
| `admin_transfer_request_payment` | r2_04_public_via_code | raises | ALREADY_REQUESTED, CALL_NOT_CONFIRMED, INVALID_TRANSFER, NOT_ALLOWED, NOT_PENDING, NOT_PUBLIC |
| `admin_transfer_verify_payment` | r2_04_public_via_code | raises | ALREADY_VERIFIED, INVALID_AMOUNT, INVALID_TRANSFER, NOT_ALLOWED, NOT_PENDING, NOT_SUBMITTED |
| `admit_ticket` | r2_03_private_transfer | raises | NOT_ALLOWED |
| `lookup_tickets` | r2_04_public_via_code |  |  |
| `private_sell` | r2_03_private_transfer | returns {ok:false,error} | ALREADY_CHECKED_IN, ALREADY_PENDING, ALREADY_TRANSFERRED, COORDINATOR, CUTOFF_PASSED, MISMATCH, NOT_CONFIRMED, TRANSFERS_CLOSED, TRY_AGAIN |
| `public_sell` | r2_04_public_via_code | returns {ok:false,error} | ALREADY_CHECKED_IN, ALREADY_PENDING, ALREADY_TRANSFERRED, COORDINATOR, CUTOFF_PASSED, INVALID_UPI, MISMATCH, NOT_CONFIRMED, TRANSFERS_CLOSED, TRY_AGAIN |
| `set_booking_status` | r2_03_private_transfer | raises | INVALID_STATUS, NOT_ALLOWED, USE_TRANSFER_TOOLS |
| `submit_booking` | r2_01_prep | raises | INVALID_ATTENDANCE, INVALID_DATA, INVALID_EMAIL, INVALID_FOOD, INVALID_GROUP_SIZE, INVALID_LOCATION, INVALID_NAME, INVALID_PHONE, NOT_ENOUGH_SPOTS, REGISTRATION_CLOSED, SCREENSHOT_MISSING |
| `transfer_cancel` | r2_03_private_transfer | returns {ok:false,error} | CONTACT_ADMIN, MISMATCH, NOTHING_TO_CANCEL |
| `transfer_open` | r2_03_private_transfer | returns {ok:false,error} | CUTOFF_PASSED, INVALID_CODE, NOT_AVAILABLE, TRANSFERS_CLOSED |
| `transfer_pay` | r2_04_public_via_code | returns {ok:false,error} | ALREADY_SUBMITTED, MISMATCH, NOT_ACTIVE, PAYMENT_NOT_REQUESTED, SCREENSHOT_MISSING, TRANSFERS_CLOSED |
| `transfer_status` | r2_04_public_via_code |  |  |
| `transfer_submit` | r2_03_private_transfer | returns {ok:false,error} | CUTOFF_PASSED, INVALID_ATTENDANCE, INVALID_CODE, INVALID_CONSENT, INVALID_DATA, INVALID_EMAIL, INVALID_FOOD, INVALID_LOCATION, INVALID_NAME, INVALID_PHONE, NOT_AVAILABLE, TRANSFERS_CLOSED, TRY_AGAIN |

Codes with no obvious reading: `MISMATCH` (any wrong detail, never says which), `TRY_AGAIN` (two requests collided; retry), `CONTACT_ADMIN` (only an admin can end it now), `NOT_ACTIVE`/`NOT_PENDING` (wrong stage), `USE_TRANSFER_TOOLS` (do not verify a transfer booking in the Bookings tab), `PAYMENT_NOT_VERIFIED`, `CALL_NOT_CONFIRMED`, `SELLER_CHECKED_IN` (the seller already entered the hall).
`admit_ticket` answers with `{result: ok | already_scanned | invalid | cancelled | not_confirmed | ...}`; for `cancelled` it includes `name`, `label` and `old_label`.

---

## APPENDIX B. REAL RESPONSES CAPTURED FROM THE TEST DATABASE (fake data)

### lookup_tickets(booking_id, phone)  -- a registered person (paid)
{
 "kind": "registration",
 "found": true,
 "status": "paid",
 "tickets": [
  {
   "food": "Veg",
   "kind": "guest",
   "name": "Asha",
   "label": "E26-001",
   "secret": "d81f2d69d726",
   "coord_no": null,
   "location": "In Bengaluru",
   "ticket_no": 1,
   "attendance": "Surely",
   "transferred": false
  }
 ],
 "booking_code": "1140548D",
 "people_count": 2,
 "amount_expected": 500
}

### lookup_tickets  -- wrong details (every failure looks exactly like this)
{
 "found": false
}

### private_sell(booking_id, ticket, phone)
{
 "ok": true,
 "code": "67Y659",
 "hours": 2,
 "expires_at": "2026-10-23T13:22:05.44071+00:00",
 "ticket_label": "E26-001"
}

### private_sell -- wrong details
{
 "ok": false,
 "error": "MISMATCH"
}

### transfer_status(booking_id, phone)  -- seller, code active
{
 "found": true,
 "transfers": [
  {
   "code": "67Y659",
   "mode": "private",
   "payout": null,
   "status": "code_active",
   "buyer_name": null,
   "created_at": "2026-10-23T11:22:05.44071+00:00",
   "expires_at": "2026-10-23T13:22:05.44071+00:00",
   "ticket_label": "E26-001",
   "amount_to_receive": null
  }
 ]
}

### transfer_open(code)  -- buyer types the code
{
 "ok": true,
 "food": null,
 "mode": "private",
 "expires_at": "2026-10-23T13:22:05.44071+00:00",
 "food_locked": false,
 "seller_name": "Asha"
}

### transfer_open  -- wrong / expired / used code
{
 "ok": false,
 "error": "INVALID_CODE"
}

### transfer_submit(code, submission_id, buyer json)
{
 "ok": true,
 "food": "Veg",
 "mode": "private",
 "status": "pending",
 "seller_name": "Asha",
 "booking_code": "C6157147"
}

### lookup_tickets -- the buyer's NEW Booking ID, private transfer pending
{
 "kind": "transfer",
 "name": "Dan Buyer",
 "found": true,
 "status": "pending",
 "tickets": [],
 "transfer": {
  "type": "private",
  "state": "pending",
  "amount_due": null
 },
 "booking_code": "C6157147",
 "people_count": 1,
 "amount_expected": 0
}

### transfer_status -- seller after the buyer applied
{
 "found": true,
 "transfers": [
  {
   "code": null,
   "mode": "private",
   "payout": null,
   "status": "pending_admin",
   "buyer_name": "Dan Buyer",
   "created_at": "2026-10-23T11:22:05.44071+00:00",
   "expires_at": null,
   "ticket_label": "E26-001",
   "amount_to_receive": null
  }
 ]
}

### admin_transfer_approve(transfer_id)  -- THE Transfer button
{
 "new_label": "E26-004",
 "old_label": "E26-001",
 "booking_code": "C6157147"
}

### lookup_tickets -- the buyer after approval (has the ticket and QR secret)
{
 "kind": "transfer",
 "found": true,
 "status": "paid",
 "tickets": [
  {
   "food": "Veg",
   "kind": "guest",
   "name": "Dan Buyer",
   "label": "E26-004",
   "secret": "ebfebf318391",
   "coord_no": null,
   "location": "In Bengaluru",
   "ticket_no": 4,
   "attendance": "Surely",
   "transferred": false
  }
 ],
 "booking_code": "C6157147",
 "people_count": 1,
 "amount_expected": 0
}

### lookup_tickets -- the SELLER after the transfer (ticket shown as transferred, no secret)
{
 "kind": "registration",
 "found": true,
 "status": "paid",
 "tickets": [
  {
   "food": "Veg",
   "kind": "guest",
   "name": "Asha",
   "label": "E26-001",
   "secret": null,
   "coord_no": null,
   "location": "In Bengaluru",
   "ticket_no": 1,
   "attendance": "Surely",
   "transferred": true
  }
 ],
 "booking_code": "1140548D",
 "people_count": 2,
 "amount_expected": 500
}

### public_sell(booking_id, ticket, phone, payout_upi)
{
 "ok": true,
 "code": "H96NNF",
 "mode": "public",
 "hours": 2,
 "expires_at": "2026-10-23T13:22:05.462617+00:00",
 "ticket_label": "E26-002"
}

### admin_transfer_request_payment(transfer_id)
{
 "amount_due": 250
}

### lookup_tickets -- public buyer, payment due
{
 "kind": "transfer",
 "name": "Eve Buyer",
 "found": true,
 "status": "pending",
 "tickets": [],
 "transfer": {
  "type": "public",
  "state": "payment_due",
  "amount_due": 250
 },
 "booking_code": "43A1C79F",
 "people_count": 1,
 "amount_expected": 0
}

### transfer_pay(booking_id, phone, submission_id, screenshot_path)
{
 "ok": true,
 "amount_due": 250
}

### admin_transfer_money()  -- the money panel (230 verified, waiting for Transfer)
{
 "held_now": 230,
 "paid_out": {
  "count": 0,
  "amount": 0
 },
 "returned": {
  "count": 0,
  "amount": 0
 },
 "return_due": {
  "count": 0,
  "amount": 0
 },
 "to_pay_out": {
  "count": 0,
  "amount": 0
 },
 "awaiting_payment": {
  "count": 0,
  "amount": 0
 },
 "awaiting_verification": {
  "count": 0,
  "amount": 0
 },
 "verified_waiting_transfer": {
  "count": 1,
  "amount": 230
 }
}

### transfer_status -- public seller after Transfer (to be paid 230)
{
 "found": true,
 "transfers": [
  {
   "code": null,
   "mode": "public",
   "payout": "to_be_paid",
   "status": "done",
   "buyer_name": "Eve Buyer",
   "created_at": "2026-10-23T11:22:05.462617+00:00",
   "expires_at": null,
   "ticket_label": "E26-002",
   "amount_to_receive": 230
  }
 ]
}

### admin_ip_flags()  (threshold lowered to 2 for the example)
{
 "ips": [],
 "threshold": 2,
 "by_booking": {}
}

### admin function error shape (raised exception text, e.g. approving twice)
 ('err', 'NOT_PENDING')
