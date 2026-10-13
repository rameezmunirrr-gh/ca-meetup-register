# Ehsaas'26 Registration App: Project Notes

Last updated: 14 Oct 2026

This repo is public. Never put passwords, the Supabase service role key, UPI IDs, phone numbers or email addresses in this file or anywhere in the repo (the publishable key in the HTML pages is fine).

---

## 0. For Claude: read this first

- The owner is a **beginner building this alone**. Explain everything **step by step in plain language**. When you want a code change, say exactly which file to open, which text to search for, and what to replace it with. Avoid jargon, or explain it in one line.
- Editing is done in the **GitHub web editor** (open file, pencil icon, Ctrl+F to find text, Commit changes). GitHub Pages redeploys in about a minute. Database changes are done in the **Supabase SQL editor**. Installing software on the owner's computer is fine if really needed.
- Before suggesting database or code changes, **read the current files** in this repo (HTML pages, `sql/` folder) rather than assuming. The live database can differ from the repo if the owner ran SQL directly, so ask for fresh exports when unsure (see `sql/README.md`).
- Every time SQL is run in Supabase, remind the owner to **save it in the `sql/` folder**, and at the end of a session offer to **update this file**.
- Respect the "Decisions not to undo" in section 8.

---

## 1. What this is

A custom registration, payment-verification and entry app for **Ehsaas'26**, a Malayalee CA meet-up in Bengaluru.

- **Organiser:** Mallu Articles Bengaluru. It began as a WhatsApp group that helps CA, CMA and ACCA students and trainees coming from Kerala to Bengaluru with articleship vacancies, application links and interview preparation. It has grown to 700+ members. The meet-up (party, food, enjoyment, relief) is the first one in a year.
- **Event:** Sunday 22 Nov 2026, 2 PM, Savoury Business Hotel, Madiwala.
- **Why not a Google Form:** custom look and feel, plus features a form can't do:
  - several people in one booking (up to 5)
  - automatic UPI QR and a pay button, with the amount calculated from group size
  - OCR scan of payment screenshots to help admins catch fake or reused proofs
  - automatic ticket generation (JPG/PDF with QR)
  - QR scanning at the gate, with live present/confirmed counts
  - admin controls (cap, price, deadline, open/close)
- **Payment:** there is **no payment gateway**. Participants pay directly to the organiser's UPI ID using the generated QR or the share button (which opens Google Pay, PhonePe etc. with the exact amount filled in). They then upload a screenshot, and organisers verify manually with OCR help.
- **Goal:** maximum simplicity for participants and coordinators, with as much automation as possible.

## 2. People and access

About 30 coordinators in four teams: Games and Activity, Stage Program Planning, Venue and Food, Operations and Coordination. The owner heads Operations and Coordination (6 members).

| Role | Who | What they use |
|---|---|---|
| Budgeting | 2 members | Work out the per-person price, which is then set in Admin, Settings |
| App building and Admin | The owner + 1 friend | Full admin dashboard |
| Gate scanning | 2 members | Gate scanner page only |

Intended rule: gate-scan access is requested by the person and must be approved by someone with admin access.

**Not built yet:** there is no request/approve screen. Currently an organiser account is created manually in Supabase (a user in Authentication plus a row in the `staff` table). Sign-ups are turned off. *(To confirm: which `role` value is used for gate staff, and how the owner currently adds a staff row.)*

## 3. Architecture

- **No server and no build step.** Three static HTML pages hosted on **GitHub Pages**, talking directly to **Supabase** (Postgres database, Auth, Storage).
- Libraries come from CDNs: supabase-js, qrcode-generator, jsQR (gate camera), Chart.js (admin charts), tesseract.js (in-browser OCR, loaded only when scanning screenshots).
- **All data changes go through database functions** (`SECURITY DEFINER`). Tables are readable only by logged-in staff (row-level security). The public pages never read or write tables directly.
- A GitHub Action (`.github/workflows/supabase-keepalive.yml`) pings the `keepalive` table every 3 days so the free Supabase project doesn't pause. It uses GitHub secrets `SUPABASE_URL` and `SUPABASE_ANON_KEY`.

## 4. Files in the repo

| Path | Purpose |
|---|---|
| `index.html` | Public page: home, register (form, summary, pay with UPI QR, screenshot upload), Tickets (search by Booking ID, view/download ticket as JPG/PDF). Has a `CONFIG` block at the top for event text, UPI ID, payee name, WhatsApp number and Supabase URL/key. |
| `admin/index.html` | Admin dashboard (admins only). Tabs: Overview (stats, charts), Bookings (mark Paid/Rejected/Pending, view screenshots, review flags), People (filters, CSV export, make/remove coordinator, Undo check-in), Scan screenshots (OCR), Settings (open/close, cap, price, deadline). |
| `gate/index.html` | Gate scanner (any staff). Camera QR scan, manual search, approve-and-admit for pending payments, live Present/Confirmed counts (total, veg, non-veg). |
| `.github/workflows/supabase-keepalive.yml` | Keep-alive ping. |
| `sql/` | Database scripts and exports (see `sql/README.md`). |

## 5. Database (Supabase, `public` schema)

**Tables**
- `settings` (one row, id = 1): `cap` (150), `price_per_head` (250, will change), `max_group` (5), `deadline` (31 Oct 2026, 23:59:59 IST), `is_open` (false by default), `next_ticket`, `next_coord` (number counters).
- `bookings`: one row per payment. `booking_code` (8 characters), `submission_id` (prevents double submits), `people_count`, `amount_expected`, `status` (`pending` / `paid` / `rejected`), `screenshot_path`, `reviewed_by/at/via` (`admin` or `gate`).
- `tickets`: one row per person. `ticket_no`, `coord_no`, `kind` (`guest` / `coordinator`), `secret` (goes in the QR), `orig_secret`, name, phone, location, attendance, food, `checked_in_at/by`, `marked_by/at`, `reg_seq` (registration order).
- `screenshot_scans`: OCR results per booking: transaction IDs, image hash, read_ok, amounts.
- `staff`: `user_id`, `name`, `role` (`admin` or other).
- `keepalive`: tiny table for the ping.

**View:** `report` (joins tickets and bookings, for manual exports). Set to `security_invoker = true` so it follows staff-only access. No page uses it.

**Functions**
- Callable by the public: `get_public_status`, `lookup_booking`, `submit_booking`.
- Staff: `admit_ticket` (check-in and gate approval), `save_scan`.
- Admin only: `set_booking_status`, `set_coordinator`, `admin_update_settings`, `undo_checkin` (by ticket id, coordinator number or guest number).
- Internal helpers: `_assign_numbers`, `_booking_json` (execute rights revoked from public/anon/authenticated, *to confirm*), `_ticket_label`, `is_staff`, `is_admin`.
- Event trigger `rls_auto_enable`: turns on row-level security for any new table in `public`.

**Storage:** bucket `payment-proofs`. Anyone can upload (needed for the public form). Only staff can read, through short-lived signed links. Bucket has a file size limit and image-only types.

## 6. Core flows

**Registering:** home, Register, form (1 to 5 people), review, pay, upload screenshot, `submit_booking`. The server checks open/deadline/cap/field values and returns a Booking ID. The participant saves the ID (also remembered on their device). Status starts `pending`.

**Verification:** an admin opens Bookings, checks the screenshot and the OCR flags (same transaction ID on two bookings, near-identical image, unreadable ID, expected amount not found), then marks **Paid** or **Rejected**.

**Tickets:** once a booking is `paid`, the participant opens Tickets, searches the Booking ID, and downloads each ticket (JPG/PDF) with its QR (`E26-007|secret`).

**Gate:** scan the QR or search by name/phone/number. Results: admitted, already scanned (shows when and by whom), payment pending (staff can view the screenshot and approve the whole booking), rejected, cancelled (coordinator conversion), invalid.

## 7. Ticket numbering (in detail, for the review task)

- Format: guests `E26-007`, coordinators `E26-001C`.
- **Numbers are given only when a booking becomes `paid`**, either by an admin or by gate approval. Within one booking, people are numbered in registration order. Across bookings, numbers follow the order bookings were marked Paid, not the order they were submitted.
- `_assign_numbers` only fills tickets that have no number yet, so marking paid, then pending, then paid again does not change numbers.
- **Coordinators** have their own counter (`next_coord`). Making a guest a coordinator: the guest number (if any) is cancelled but stays on record, a coordinator number is given, and the QR secret changes (the old one is kept as `orig_secret`). Nothing else is renumbered.
- **Removing** a coordinator: the coordinator number is retired and never reused, the original secret is restored, and a guest number is restored or newly given if the booking is paid.
- Numbers are never reused or renumbered. Gaps are expected (rejected bookings that were numbered, cancelled guest numbers).
- An old downloaded ticket for a converted coordinator shows as "cancelled" at the gate and tells staff the new number. The participant sees the new ticket after refreshing Tickets.

**Things to review in this task:** gaps in numbering and whether they matter, numbering order (paid order versus registration order), what happens to a numbered ticket whose booking is later rejected, and whether the unique constraints on `ticket_no` and `coord_no` exist (see `sql/README.md`).

## 8. Decisions not to undo

- Numbers are never reused or renumbered.
- Any staff member (not only admins) can approve a pending payment at the gate. This marks the whole booking paid.
- Everything that writes data goes through database functions, and the public never touches tables.
- Participants see no fraud or OCR information, only status.
- OCR runs in the admin's browser. No screenshot is sent to any outside service.
- No payment gateway (payments are direct UPI with manual verification).

## 9. Before registration opens (20 Oct 2026)

- Replace test values in the `CONFIG` block of `index.html`: UPI ID, payee name, WhatsApp number (currently test values).
- Budgeting team sets the final price in Admin, Settings. Confirm the cap and deadline.
- Do a small real test payment and scan it in two UPI apps.
- Delete all test bookings and empty the `payment-proofs` bucket.
- Make sure "Allow new users to sign up" is off in Supabase Auth.
- Create the organiser logins (admins and the two gate members).
- Turn **Registration open** on in Settings (it is off by default).

## 10. Status

**Done:** the three pages, the database and functions, OCR scanning, coordinator handling, keep-alive, security hardening (report view, helper functions, bucket limits, new `undo_checkin`), Undo button in the People tab (committed 14 Oct, still to be tested).

**Immediate tasks:**
1. Restyle the whole web application.
2. Review the ticket numbering system (section 7).

**Ideas and known gaps:**
- In-app request/approve flow for gate staff access (currently manual).
- Saving settings with an empty deadline field throws an error in the browser.
- Cap can be set below the number already registered (harmless, new bookings just stop).
- Booking codes are short and lookups are not rate-limited (fine for this size of event).

## 11. Never share

Supabase **service role key**, database password, staff passwords, or anything from the Supabase dashboard's secret key section. The publishable key in the pages is safe by design.
