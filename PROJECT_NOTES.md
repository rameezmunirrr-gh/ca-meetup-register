# Ehsaas'26 Registration App: Project Notes

> **NEW SESSION? READ `HANDOVER_NEXT_SESSION.md` FIRST** (state of each environment, safe rollout order, the transfer case scenario by scenario, page-by-page change list, gaps found in the final review, how to rebuild the test setup). This file is the decision log and database design record.

Last updated: 25 Oct 2026 late evening (**Release 2 is LIVE and rehearsed on the real site; test data cleaned; see the LIVE STATUS block at the top of `HANDOVER_NEXT_SESSION.md`**). Earlier the same day: (Release 2 was fully BUILT and TESTED on the scratch database and in a mocked browser: piece 6, private emails, and all three pages. NOTHING of it is applied to Supabase or live yet; see the 25 Oct entry in section 13 and `HANDOVER_NEXT_SESSION.md` top block**). Earlier: 17 Oct 2026 (final review and handover written; final transfer design: ONE code flow for private and public transfers; Release 1 done; Release 2 (transfers, new ticket lookup, email, +91) designed with the owner and written down in section 12; not built yet; order: build, test and risk-proof, then restyle)

**This repo is public.** Never put passwords, the Supabase service role key, database connection strings, UPI IDs, phone numbers or email addresses in this file or anywhere else in the repo. (The Supabase URL and the *publishable* key inside the HTML pages are safe by design.)

---

## 0. For Claude: read this first

**About the owner**
- The owner is a **beginner building this alone** (a friend will later get the admin dashboard). Explain everything **step by step in plain language**. Avoid jargon, or explain it in one line.
- Installing software on the owner's computer is fine if really needed, but so far everything is done in the browser.
- Times are India time (Asia/Calcutta, UTC+05:30).

**How work is done**
- **Code changes:** in the **GitHub web editor** (open the file, pencil icon, Ctrl+F to find text, Commit changes). GitHub Pages redeploys in about a minute, then the page needs a hard reload (Ctrl+Shift+R).
- **For any code change, say exactly which file to open, which text to search for, and what to replace it with.** For anything longer than a few lines, prefer giving a **complete file** (sent as a file) so the owner pastes one thing. Warn the owner that the trash-can icon on a GitHub file page *deletes the file* (this already happened once on 14 Oct 2026; it was restored from a saved copy).
- **Database changes:** in the **Supabase SQL editor**. Send SQL as a file when it is long.
- **Check your work before handing it over.** For page changes, run the page in a headless browser with a mocked Supabase and check the rendered numbers (done on 14 Oct 2026 for the Overview). For database logic, read the real function source in `sql/schema_snapshot.txt` first.
- **Work order set by the owner (16 Oct 2026): structure and safety first, looks last.** Build the remaining features, then test in every way, think deeply about risks and close all of them, and only when the app is completely foolproof and error-proof start the redesign. **Do not spend time on styling until then.** The owner said there is no deadline pressure for Claude: focus on building, accuracy and risks in the code. (Dates: registration was planned to open on 20 Oct; the owner later said the due date may be about 25 Oct or another date. It is not fixed, so ask before relying on any date.)
- **Ask before changing behaviour.** When the owner says "don't change anything yet, just note it", only record it (in section 12) and do not edit code.

**Staying accurate**
- **Read the current files** before suggesting changes: the HTML pages and the `sql/` folder. The live database can differ from the repo if SQL was run directly. `sql/schema_snapshot.txt` is the up-to-date copy of the database structure (tables, columns, constraints, functions with their execute rights, policies, bucket limits), refreshed every night.
- The repo is public, so live files can be read from `https://raw.githubusercontent.com/rameezmunirrr-gh/ca-meetup-register/main/<path>`. Raw GitHub caches for a few minutes, and the WebFetch tool only returns a *summary* of long files. If a shell with internet is available, `curl` the raw URL with a `?nocache=<number>` suffix to get the exact text.
- **Source of truth:** `sql/schema_snapshot.txt` (the actual database, nightly) beats `sql/changes.sql` (a hand-kept history that may have gaps). If they disagree, trust the snapshot and say so.
- Every time SQL is run in Supabase, remind the owner to **paste it into `sql/changes.sql`** (only statements that change something, with a date comment). At the end of a session, offer to **update this file**.
- Respect the "Decisions not to undo" in section 9.

---

## 1. What this is

A custom registration, payment-verification and entry app for **Ehsaas'26**, a Malayalee CA meet-up in Bengaluru.

- **Organiser:** Mallu Articles Bengaluru. It began as a WhatsApp group started by 3 people who struggled with articleship, interviews and preparation. It guides CA, CMA and ACCA students and trainees coming to Bengaluru from Kerala with articleship vacancies, application links and interview preparation. It has grown to 700+ members, and the meet-up (party, food, enjoyment, relief) is the first in a year.
- **Event:** Sunday 22 Nov 2026, 2 PM, Savoury Business Hotel, Madiwala, Bengaluru.
- **Why not a Google Form:** custom look and feel, plus features a form can't do:
  - several people in one booking (up to 5)
  - automatic UPI QR (scan-only) with the amount calculated from group size
  - OCR scan of payment screenshots to help admins catch fake or reused proofs
  - automatic ticket generation (JPG/PDF with QR)
  - QR scanning at the gate, with live present/confirmed counts
  - admin controls (cap, price, deadline, open/close)
- **Payment:** there is **no payment gateway** (no business account is involved). The UPI QR on the Pay screen is generated for the exact total (number of people times the price), and the participant can scan it, use **Share/Download QR** (then upload the screenshot of the QR inside their UPI app), or copy the UPI ID and pay to it. **Tapping the QR to open a UPI app was removed on 16 Oct 2026** (the apps refuse it, see section 13). The participant enters the UPI PIN in their own app, then uploads a payment screenshot. The UPI ID, payee name and WhatsApp number are read from the database, not the page code. Organisers verify manually, helped by OCR.
- **Goal:** maximum simplicity for participants and coordinators, with as much automation as possible.

**Key numbers (current settings, adjustable in Admin, Settings):**

| Item | Value |
|---|---|
| Cap (people, confirmed + pending) | 150 (checked 14 Oct 2026, after testing) |
| Price per person | ₹250 (checked 14 Oct 2026); the final price is set by the budgeting team |
| Max group per booking | 5 |
| Registration deadline | 31 Oct 2026, 23:59:59 IST |
| Registration opens | **20 Oct 2026** (planned; the owner said on 16 Oct it may move to about 25 Oct or another date, so confirm) |
| Registration open flag | Off by default, and currently **off** (checked 14 Oct 2026, 3 PM). Switch it on in Admin, Settings only when testing needs it; only the owner has the link. No real person registers until the owner says the project is complete. |

---

## 2. People and access

About 30 coordinators in four teams: Games and Activity, Stage Program Planning, Venue and Food, Operations and Coordination. The owner heads Operations and Coordination (6 members).

| Role | Who | What they use |
|---|---|---|
| Budgeting | 2 members | Work out the per-person price, which is set in Admin, Settings |
| App building and Admin | The owner + 1 friend | Full admin dashboard |
| Gate scanning | 2 members | Gate scanner page only |

Intended rule: gate-scan access is requested by the person and must be approved by someone with admin access. **There is no request/approve screen yet** (see section 12).

**Adding staff:** The owner and **one friend (app building and admin)** get logins **now**, so the friend can work on the dashboard. **Everyone else** (gate members, any other admins, the other coordinators) is added manually **at the end**, once everything is ready and tested. The steps are the same for everyone:
1. Supabase, Authentication, Users, Add user (email and password, auto-confirm).
2. Copy the new user's **User UID**.
3. In the SQL editor: `insert into staff (user_id, name, role) values ('<UID>', '<Name>', '<role>');`

The database only accepts the role values **`admin`** and **`gate`**. **Always write the role explicitly: since 16 Oct 2026 the column has no default**, so an insert without a role is refused. To remove someone's access, **delete their row from `staff`** (do not delete their Supabase login: that fails if they have ever reviewed or scanned anything). As of 14 Oct 2026 only the owner (admin) is in the table; the friend (admin) is to be added next, so expect **two** rows (both `admin`) from then on until the end-of-project additions. Sign-ups in Supabase Auth are **off** (confirmed 14 Oct 2026; manual linking and anonymous sign-ins are off too, and email confirmation is on).

Gate staff sign in on `/gate/`. If a gate user opens the admin page, they see "This page is for admins". Admins can use both pages.

---

## 3. Architecture

- **No server and no build step.** Three static HTML pages hosted on **GitHub Pages** (public repo, free plan), talking directly to **Supabase** (free plan: Postgres database, Auth, Storage). Supabase project: `CA-meetup-2026`.
- Libraries from CDNs: supabase-js (pinned version), qrcode-generator, jsQR (gate camera), Chart.js (admin charts), tesseract.js (in-browser OCR, loaded only when scanning screenshots).
- **All data changes go through database functions** (`SECURITY DEFINER`). Tables are readable only by logged-in staff (row-level security). The public pages never read or write tables directly (they only call the public functions and upload to the storage bucket).
- **GitHub Actions** (both in `.github/workflows/`):
  - `supabase-keepalive.yml`: pings the `keepalive` table every 3 days so the free Supabase project doesn't pause. It uses GitHub secrets `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
  - `schema-snapshot.yml`: runs **every night at 2:00 AM India time** (and on demand from the Actions tab) and writes the database structure to `sql/schema_snapshot.txt`, committing only when something changed. It connects with a **read-only database user `snapshot_reader`** through the GitHub secret `SNAPSHOT_DB_URL` (session-pooler connection string). It does **not** capture data, the contents of the `staff` table, or dashboard settings. The commit history of that file works as a change log of the database. The snapshot is public because the repo is public (it shows structure and function code, never data or keys).
- Browser sessions: the admin and gate pages use persistent Supabase logins. **Signing out in one window signs the account out everywhere.** Requests made while logged out run as an anonymous visitor, which has no table access, so the dashboard shows **"Could not load data: permission denied for table bookings"**. The fix is a hard reload and signing in again (this appeared once on 14 Oct 2026 after a second private window was used; signing in again cleared it, and the most likely cause was the login ending). If it ever returns after a fresh sign-in, compare the table permissions with the `TABLE AND VIEW PERMISSIONS` section of `sql/schema_snapshot.txt` (each table should show `authenticated=r/postgres`).

---

## 4. Files in the repo

| Path | Purpose |
|---|---|
| `index.html` | Public page: home, register (form, summary, pay with UPI QR, screenshot upload), Tickets (search by Booking ID, view and download tickets as JPG/PDF). A `CONFIG` block at the top holds event text, ticket text and the Supabase URL and key. The UPI ID, payee name and organiser WhatsApp number are **not** in the code: they come from the database (`get_payment_info`), set in Admin > Settings > Payment details. |
| `admin/index.html` | Admin dashboard (admins only), see section 6. |
| `gate/index.html` | Gate scanner (any staff), see section 6. |
| `.github/workflows/supabase-keepalive.yml` | Keep-alive ping. |
| `.github/workflows/schema-snapshot.yml` | Nightly database structure snapshot. |
| `PROJECT_NOTES.md` | This file. |
| `sql/README.md` | Guide to the sql folder, including manual export queries (now optional because of the snapshot). |
| `sql/changes.sql` | A history of SQL that changed the database, with date comments (the *why* behind each change). **Not guaranteed complete or fully reliable:** the owner pastes into it by hand, and some early changes may be missing (for example the 14 Oct numbering update and the `snapshot_reader` setup were not in it on 14 Oct 2026). Never treat it as the current state of the database. The source of truth is the live database as recorded in `sql/schema_snapshot.txt`. |
| `sql/schema_snapshot.txt` | Automatic nightly export. Never edit by hand. |

---

## 5. Database (Supabase, `public` schema)

### Tables
- **`settings`** (one row, `id = 1`): `cap`, `price_per_head`, `max_group` (1 to 5), `deadline`, `is_open`, `closed_at` (when registration was last switched off by hand), `pause_enabled`, `pause_close_time`, `pause_open_time` (daily pause, India time), `grace_minutes` (10, fixed), `next_ticket`, `next_coord` (the counters for the next guest and coordinator number).
- **`settings` Release 1 columns (added 16 Oct 2026):** `event_at` and `venue` (edited with `admin_set_event`), `upi_id`, `payee_name`, `whatsapp_number` (null until the admin enters them; checked for format; edited with `admin_set_payment_info`), plus `transfers_open` and `max_resale_price` (see the transfer tables below).
- **`settings_log`**: one row per setting or staff change (`at`, `changed_by`, `who`, `area` = `settings` or `staff`, `field`, `old_value`, `new_value`). Admin read only. Changes made directly in Supabase are logged as "database".
- **`bookings`**: one row per payment. `booking_code` (8 hex characters, unique), `submission_id` (unique, prevents double submits), `people_count` (1 to 5), `amount_expected`, `status` (`pending` / `paid` / `rejected`), `screenshot_path`, `reviewed_by`, `reviewed_at`, `reviewed_via` (`admin` or `gate`), `created_at`.
- **`tickets`**: one row per person (no email: see `ticket_emails`). `booking_id`, `ticket_no` (unique, the guest number), `coord_no` (the current coordinator number), `kind` (`guest` / `coordinator`), `secret` (12 hex characters, goes in the QR), `orig_secret` (the guest QR secret kept while someone is a coordinator), **`prev_coord_no`** and **`prev_coord_secret`** (a retired coordinator number and its QR secret, kept on the same person), `name`, `phone` (exactly 10 digits), `location`, `attendance`, `food`, `checked_in_at`, `checked_in_by`, `marked_by`, `marked_at`, `reg_seq` (registration order), `created_at`.
- **`screenshot_scans`**: one row per booking (primary key `booking_id`): `txn_ids`, `image_hash`, `read_ok`, `amounts`, `scanned_by`, `scanned_at`. Deleted with its booking.
- **`staff`**: `user_id` (primary key, linked to the login), `name`, `role` (`admin` or `gate` only).
- **`keepalive`**: tiny table for the ping (readable by anon).
- **OLD transfer tables (to be DROPPED and replaced in R2-1, see section 12; exist in the database, deployed but unused; `settings.transfers_open` is false and the pages have no transfer screens):**
  * **`ticket_listings`**: a seller's offer on the board. `ticket_id`, `price` (0 up to `max_resale_price`), `contact_phone`, `status` (`active` / `withdrawn` / `sold` / `closed` / `removed` / `edited`), `mode` (`private` or `public`), `comment` (up to 140 characters).
  * **`ticket_interests`**: people interested in a listing. `listing_id`, `name`, `phone`, `choice` (`talk` / `agree`), `price_seen`. Unique per (listing, phone); at most 50 per listing.
  * **`ticket_transfers`**: one row per transfer. `code` (10 characters), `status` (`awaiting_buyer` / `pending_admin` / `done` / `declined` / `withdrawn`), `mode`, `price`, `agreed_amount`, the buyer's details (`new_*`), the seller's old details (`from_*`, `from_kind`, `from_coord_no`), `to_ticket_no`, `payout` (the seller's UPI ID or phone, public mode), and the money steps (`amount_confirmed_at`, `buyer_paid_at`, `buyer_screenshot_path`, `payment_received_at`, `seller_paid_at`, `refunded_at`). Admin read only.
  * `settings` also has `transfers_open` (false) and `max_resale_price` (250).
  * Functions: `get_transfer_status`, `list_board`, `post_listing`, `edit_listing`, `close_listing`, `express_interest`, `check_request`, `manage_ticket`, `start_transfer`, `apply_receive`, `lookup_transfer`, `submit_transfer_payment`, `withdraw_transfer`, and for admins `approve_transfer`, `decline_transfer`, `admin_confirm_amount`, `admin_mark_payment_received`, `admin_mark_seller_paid`, `admin_mark_refunded`, `admin_remove_listing`, `admin_clear_comment`, `admin_set_transfer_settings`. Read their real source in `sql/schema_snapshot.txt`. **Do not turn `transfers_open` on until the audit items in section 12 are fixed and tested.**
- **`reg_sessions`**: one row per registration attempt in progress (`id` = the page's submission ID, `started_at`, `last_seen`). No personal data. Written only by `registration_heartbeat`; nobody can read it directly. Rows older than a day are deleted automatically.

### Rules enforced by the database itself
- Unique: `bookings.booking_code`, `bookings.submission_id`, `tickets.ticket_no`, `tickets.coord_no` (where not null), `tickets.prev_coord_no` (where not null).
- Check rules on phone (10 digits), food (`Veg` / `Non-veg`), location (`In Bengaluru` / `Outside Bengaluru`), attendance (`Surely` / `Most probably`), booking status, group size 1 to 5, amount above 0, `reviewed_via`, staff role, and: a coordinator must have a `coord_no` and a guest must not.
- **A ticket cannot outlive its booking:** deleting a booking that still has tickets is blocked. Cleanup order is tickets first, then bookings (section 11).
- Several columns (`reviewed_by`, `checked_in_by`, `marked_by`, `scanned_by`) point to the login in `auth.users`; deleting a login that has acted fails.
- The group-size limit of 5 is fixed in two places (`settings.max_group` and the `bookings.people_count` check). A bigger group size needs both changed.

### View
`report` (joins tickets and bookings, for manual exports). Set to `security_invoker = true` so it follows the staff-only rules. No page uses it. (`service_role` has no select on it.)

### Functions
All write paths are `SECURITY DEFINER` functions. Parameter names matter because the pages call them by name.

| Function | Who can call it | What it does |
|---|---|---|
| `get_public_status(p_session default null)` | public | Returns `accepting`, `closed_reason` (`not_open` / `deadline` / `full` / `paused`), `spots_left`, `price_per_head`, `max_group` (the smaller of the setting and the spots left, at least 1), `deadline`, `server_now`, `grace_until` (set only if this session may still finish), `reopen_at` (end of today's pause), `next_close_at` (next daily pause), `pause_enabled`. Spots used = all people in non-rejected bookings (confirmed + pending). |
| `registration_heartbeat(p_session)` | public | The form page calls it on arrival and every 30 seconds. While registration is open it records the session; while closed it only refreshes a session that is still inside its grace minutes, and never starts a new one. Returns the same JSON as `get_public_status`. |
| `lookup_booking(p_code)` | public | Finds a booking by its code (case, spaces, dashes ignored; letter O treated as zero) and returns its tickets. QR secrets are only included when the booking is `paid`. |
| `submit_booking(p_submission_id, p_people, p_screenshot_path)` | public | Creates one booking and one ticket per person. Safe to retry (same submission ID returns the original). Locks the settings row, checks deadline, open/pause (a closed registration still accepts a session with valid grace, plus 30 seconds for the upload), group size and cap (`NOT_ENOUGH_SPOTS`), validates every field, checks the screenshot exists in storage, creates a code. `p_people` items use the keys `name`, `phone`, `loc`, `att`, `food`. |
| `set_booking_status(p_booking, p_status)` | admin | Sets pending/paid/rejected. When set to paid, gives numbers to guest tickets that have none. |
| `set_coordinator(p_ticket_id, p_make)` | admin | Makes or removes a coordinator (section 7). |
| `admit_ticket(p_ticket_no, p_secret, p_approve, p_coord, p_id)` | staff | Gate check-in. Finds a ticket by guest number, coordinator number (`p_coord = true`) or ticket id (`p_id`, used for manual search, skips the QR secret check). Returns `invalid`, `cancelled`, `pending`, `rejected`, `already_scanned` or `ok`. With `p_approve = true` it first marks the whole booking paid (`reviewed_via = 'gate'`) and numbers it. |
| `undo_checkin(p_ticket_no, p_coord, p_id)` | admin | Clears a check-in. Works by ticket id, coordinator number or guest number. Raises `INVALID_TICKET` if nothing matches. |
| `save_scan(p_booking, p_ids, p_hash, p_ok, p_amounts)` | staff | Stores an OCR result. |
| `admin_update_settings(p_cap, p_price, p_deadline, p_is_open, p_pause_enabled, p_pause_close, p_pause_open)` | admin | Updates settings (null means keep). Remembers `closed_at` when `is_open` goes from on to off, clears it when switched on. Raises `INVALID_PAUSE_TIMES` if close and reopen are the same. |
| `admin_registration_status()` | staff | Live status for the dashboard banner: closed reason, reopen time, next pause, and how many people are still inside their grace minutes (`grace_count`, `grace_until`). |
| `_pause_info(settings)`, `_grace_until(settings, session, slack)`, `_public_state(settings, session)` | internal only | The pause-window maths (India time), the grace check, and the shared status JSON. Execute rights revoked from everyone. |
| `get_payment_info()` | public | Returns the UPI ID, payee name and WhatsApp number for the Pay screen (null parts mean "not set up yet"). The page calls it each time Pay opens and every 30 seconds. |
| `admin_set_payment_info(p_upi, p_payee, p_whatsapp)` | admin | Saves the payment details (format-checked) and writes the change to `settings_log`. |
| `admin_payment_alert()` | admin | Returns who last changed the payment details in the last 7 days, for the banner shown to the other admin. |
| `get_event_info()` | public | Returns `event_at` and `venue`. |
| `admin_set_event(p_event_at, p_venue)` | admin | Updates the event date and venue. |
| `is_staff()`, `is_admin()`, `_ticket_label(kind, ticket_no, coord_no)` | internal | Helpers for rules and labels (`E26-007`, `E26-001C`). |
| `_assign_numbers(p_booking)`, `_booking_json(p_booking)` | internal only | Execute rights were revoked from public, anon and authenticated (done 13 Oct 2026; confirmed 14 Oct 2026: the rights list shows only `postgres`; the `execute rights` line in `sql/schema_snapshot.txt` shows the same). |
| `rls_auto_enable()` | event trigger | Turns on row-level security for any new table in `public`. |

### Security rules (row-level security)
- Staff can select from `bookings`, `tickets`, `screenshot_scans`, `settings` (any staff). `staff` rows are readable by the person themselves or by admins. `keepalive` is readable by anon. Nobody can write to tables directly.
- The logged-in role `authenticated` has table-level select; `anon` has none (except `keepalive`).

### Storage
Bucket `payment-proofs`. Anyone can upload (needed for the public form), but only staff can read, through short-lived signed links. The bucket has a **file size limit and image-only types** (set 13 Oct 2026). Screenshots are named `<submission_id>.<jpg|png|webp>`. The public page compresses screenshots in the browser before uploading.

---

## 6. Core flows and pages

### Public page (`index.html`)
Home has two buttons: Register and Tickets.
1. **Register:** the page asks `get_public_status`. If closed it shows why. The form takes 1 to 5 people (a "Include friends" switch reveals 2 to `max_group`, and `max_group` shrinks as spots run out). Each person: name, 10-digit phone, location, attendance, food.
   - **Daily pause and grace:** when the form opens, the page starts a session (its submission ID) and sends a heartbeat every 30 seconds. If registration closes (daily pause or switched off by hand) while someone is filling the form, a yellow bar shows a 10:00 countdown and they can finish and submit. If they run out of time, they see "Your 10 minutes are over" with a WhatsApp button (they should not pay again). New visitors during a pause see "Registrations are paused for a short while" with the reopen time. Within 2 hours before a pause the form shows a heads-up note.
2. **Review** the details, then **Pay**: shows the exact total, a UPI QR drawn in the page, copy-UPI-ID, share/download QR, and the screenshot upload. The page compresses the image and uploads it, then calls `submit_booking`.
3. **Done:** shows the **Booking ID**, saved on the device (also usable from any device). Status is `pending`. A WhatsApp contact button opens a chat with the organisers with the Booking ID pre-filled.
4. If spots run out while someone is filling the form, they get a message and a smaller group limit, and no half-made booking is created (tested).
5. **Tickets:** search by Booking ID (typed in any case, with or without dashes, letter O for zero), plus "On this device" for saved bookings. States: Pending verification, Not verified (rejected, with a contact button), Confirmed (paid), which opens **View Ticket**.
6. **Ticket:** each person gets a ticket drawn on a canvas (event details, name, food mark, **ticket number**, QR with `E26-007|secret`; the Booking ID is **not** drawn on the ticket since 16 Oct 2026). Download as JPG or PDF per person, or all tickets as one PDF. Coordinator tickets use a different colour and the word COORDINATOR.

### Admin dashboard (`admin/index.html`)
Login with email and password. Tabs:
- **Overview:** six cards and three doughnut charts.
  - **Active tickets:** confirmed (paid) people only, split as guests and coordinators, with the amount received.
  - **Spots used:** every non-rejected person (active + pending) against the cap, with spots left. This is the number that closes registration when it reaches the cap.
  - **Pending:** people in pending bookings and their amount.
  - **Expected total:** paid + pending amount, "compare with your bank".
  - **Present at event:** checked-in people from **paid** bookings only (matches the gate counter). The small "rejected: N" is the number of people in rejected bookings.
  - **Coordinators:** non-rejected coordinators, and how many are confirmed.
  - Charts (Food, Location, Attendance) have a switch between **Confirmed + Pending** and **Confirmed only**. Use "Confirmed only" for final food and hall numbers.
- **Bookings:** every booking with its people (with ticket numbers), amount, status, the OCR-read transaction ID, review flags, and buttons Screenshot / Paid / Reject / Pending. Review flags: same transaction ID on two bookings, near-identical image (only as a backup when an ID couldn't be read), unreadable ID, expected amount not found on the screenshot.
- **People:** one row per person. Filters (search, payment, food, location, attendance, type), **Download Excel (CSV)**, **Make coordinator / Remove coordinator** buttons, notes such as "guest E26-004 cancelled" and "coordinator E26-001C cancelled", and **Present** with an **Undo** button (admin only, calls `undo_checkin` by ticket id).
- **Scan screenshots:** runs OCR in the admin's browser (nothing leaves the computer), saves transaction IDs, an image hash and amounts through `save_scan`.
- **Settings:** registration open switch; when it is on, a **daily pause** box (switch + close time + reopen time, India time, same every day until the deadline); cap, price, deadline, and a reminder checklist. A live status banner (open / paused / closed, and "A user is currently updating even though the registration is closed, using the 10 minutes grace time.") appears at the top of Overview and Settings and refreshes every 15 seconds. Empty deadline no longer causes an error. **Payment details** (UPI ID, payee name, WhatsApp number) are locked until **Change** is pressed, and a **Settings log** lists every setting and staff change. The other admin sees a banner for 7 days after the payment details change. The event date and venue are also edited here.

### Gate scanner (`gate/index.html`)
- Login. Live counters: **Present / Confirmed**, **Veg present / Veg confirmed**, **Non-veg present / Non-veg confirmed** (only people in paid bookings), refreshed every 30 seconds.
- **Camera scan** of the ticket QR (`E26-007|<12 hex>` or `E26-001C|<12 hex>`). Anything else shows NOT A TICKET.
- **Find a person** (at least 2 characters): by name, phone, current ticket label or Booking ID, or by a plain guest number. Searching and tapping Admit skips the QR checks (so it never shows "cancelled").
- **Results:** green ADMITTED (auto-closes); red ALREADY SCANNED (time and who); amber PAYMENT PENDING (view screenshot, then **Approve and admit** which marks the **whole booking** paid and numbers everyone, or Don't admit); red PAYMENT REJECTED; red TICKET CANCELLED (shows the person's current ticket number); red INVALID TICKET; grey COULDN'T CHECK (network problem, scan again, and ALREADY SCANNED means they were admitted).

### Verification workflow
Participant submits, an admin opens Bookings, checks the screenshot and flags, then marks **Paid** (numbers are assigned, participant can download tickets) or **Rejected** (participant sees "Not verified" with a contact button).

---

## 7. Ticket numbering (final rules, tested 14 Oct 2026)

**Core rule from the owner: a number touched by a person is never given to another person.** Each person keeps their guest number and their coordinator number for good. This protects entry control: a cancelled ticket can never be mistaken for a live one.

- Format: guests `E26-007`, coordinators `E26-001C`.
- **Numbers are given only when a booking becomes `paid`**, either by an admin or by gate approval. Within one booking, people are numbered in the order they were listed on the form. Across bookings, numbers follow the **order bookings were marked Paid**, not the order they registered.
- Only **guest tickets** get a guest number at payment. A coordinator who has no guest number yet does not get one when their booking is paid.
- Marking paid, then pending, then paid again does not change numbers. A rejected booking keeps its numbers on record (the gate shows PAYMENT REJECTED), and marking it paid again gives the same numbers back.
- **Making a guest a coordinator:**
  - First time: they get the next coordinator number (`next_coord`, then it increases) and a **new QR secret**. Their guest number (if any) stays on the row but is cancelled while they are a coordinator, and the guest QR secret is kept in `orig_secret`. Nobody else is renumbered.
  - If they were a coordinator before: they get **their own old coordinator number and QR back** (`prev_coord_no`, `prev_coord_secret`), not a new number.
- **Removing a coordinator:** their coordinator number is kept on them as `prev_coord_no` (cancelled, never given to anyone else), their guest number and original QR come back, or if they never had a guest number and the booking is paid, they get the next free guest number.
- **Gate behaviour:** scanning the old guest QR of a coordinator shows TICKET CANCELLED with the new number. Scanning a retired coordinator QR of someone who is a guest again shows TICKET CANCELLED with their current number. The person sees the new ticket after refreshing Tickets (the ticket page shows the tickets the database returns).
- **Gaps are expected** (rejected numbered bookings, cancelled guest numbers, retired coordinator numbers), and the highest number can exceed the cap. That is fine: **counts use active people, not numbers** (section 6, Overview).
- Two admins clicking Paid at the same moment is safe (the settings row is locked, and unique indexes refuse duplicate numbers).
- Counters (`next_ticket`, `next_coord`) are reset to 1 only during the pre-launch cleanup.

---

## 8. Cap and counting rules


- The cap counts **every person in a non-rejected booking**, confirmed or pending. Registration closes when this reaches the cap. Rejecting a booking frees its spots.
- Coordinators count toward the cap like everyone else. Making someone a coordinator does not change the total.
- The public page shows "Only N spots left" when 20 or fewer remain, and "All spots are taken" at the cap.
- The dashboard separates the two groups: **Active tickets** (confirmed) and **Pending**, so that active + pending = spots used. No waiting list exists or is needed.

### Daily pause and grace rules (added 14 Oct 2026)
- The master **Registration open** switch overrides everything. The daily pause only applies while it is on. The cap never gets grace. The **deadline gets the same 10-minute grace** (people mid-registration at the deadline can finish; nobody new can start).
- The pause is enforced in the database (`submit_booking`), not only on the page. Times are India time, the same every day until the deadline. Close and reopen cannot be equal. Overnight windows (23:00 to 00:30) and same-day windows (13:00 to 14:00) both work.
- **Grace:** 10 minutes (`grace_minutes`, fixed). A person counts as "mid-registration" if their form session started before the closing moment and was last seen within 10 minutes before it (so someone who left to pay in a UPI app still qualifies). People who open the form after closing time get nothing. Applies to the daily pause and to switching registration off by hand (`closed_at`).
- The cap still applies during grace (`NOT_ENOUGH_SPOTS`).
- If the reopen time after a pause would fall past the deadline, the page shows "deadline passed". The closing moment used for grace is the earliest of: switched off by hand (`closed_at`), pause start, deadline (`_close_moment`).
- The dashboard banner tells the admin when no one is mid-registration, i.e. when it is safe to check the bank balance.

---

## 9. Decisions not to undo

- A number touched by a person is never given to another person (guest and coordinator numbers both).
- Numbers are given when a booking is paid, never at registration, and are never renumbered.
- Any staff member (not only admins) can approve a pending payment at the gate. This marks the whole booking paid.
- Everything that writes data goes through database functions, and the public never touches tables.
- Participants see no fraud or OCR information, only status.
- OCR runs in the admin's browser. No screenshot is sent to any outside service.
- No payment gateway (direct UPI with manual verification).
- Pending people hold spots (otherwise registrations could exceed the number of seats).
- Registration stays closed to real people until the owner says the project is complete.
- **Do not bring back the tap-to-pay (`upi://`) link** on the Pay screen. It was tried twice and the UPI apps refuse it (16 Oct 2026).
- The **Booking ID is not shown on the ticket image, the ticket page heading or the PDF file name** (16 Oct 2026).
- **Transfers (owner, 17 Oct 2026):** private transfers move no money through the organisers; public transfers do (buyer pays the organisers, the organisers pay the seller's UPI after the transfer). The admin's phone call to the seller's registered number is the final identity check for every transfer (before Transfer in private ones, before listing in public ones). Registration itself is still direct UPI with manual verification.
- **Ticket status lookup is Booking ID + phone** (owner, 17 Oct 2026); a Booking ID alone shows nothing.
- **Transfers stay off (`transfers_open` false) until the Release 2 audit items are fixed and tested.**
- Build order (owner, 16 Oct 2026): features first, then deep testing and risk-proofing, then restyle.

---

## 10. Testing

A full numbering, check-in and counting test was completed on 14 Oct 2026 and **all steps passed**. It used five test bookings (single, pair, single, pair, and a group of 5) and covered:
1. Registration and the group-size limit.
2. Numbers following the order of Paid, and paid, pending, paid again.
3. Gate approval of a pending booking, double scans, live counters, a non-ticket QR.
4. Coordinators: guest to coordinator and back, flip-flopping, coordinator before payment, retired numbers never reused, cancelled QR messages, no wasted numbers.
5. Rejecting and re-approving bookings (including ones containing coordinators and already checked-in people).
6. Undo check-in for a guest and a coordinator.
7. The cap: spots left, a full event, a registration race (a second window taking the last spot, correctly refused), and a price change.
8. Counts agreeing across Overview, People, CSV export and gate.

Two things found by the test were fixed in `admin/index.html`: "Present at event" now matches the gate, and "Active tickets" counts confirmed people only (with a separate "Spots used" card).

**Test lessons:** the cancelled-ticket messages only appear when a QR is scanned with the camera (not when a person is picked from search). Download each ticket *before* changing it if it will be scanned later. Confirm the cap and price are what the test expects before starting. The test plan was a Markdown checklist kept outside the repo; ask Claude to recreate it from this section if needed.

**Release 2 test plan (to do, after the hardening SQL is built).** Run on a scratch Postgres with a fake clock first, then in the browser with a mocked server, then on the real site with test data:
1. Every audit item in section 12 as a deliberate attack (wrong or missing second check, guessing codes, repeated tries and lockout, fake interests, overwriting an application, re-selling a transferred ticket, the old holder still seeing the new ticket).
2. Both modes (private and public) end to end, including price rules, the money checklist, decline and refund.
3. Races: two buyers applying together, two admins approving together, the seller withdrawing while the buyer pays, a transfer while the person is being checked in at the gate.
4. Gate after a transfer: the old QR never admits and shows the right message (also for a seat transferred twice); the new QR admits once; counts and numbering rules (section 7) stay correct; cap and live counts are unchanged.
5. Everything is switched off cleanly when `transfers_open` is false, and the registration flow is unaffected.

**Scratch database for testing SQL (set up 17 Oct 2026).** Claude's container resets between chats, so the tools are saved in the repo in the `scratch-db/` folder at the top of the repo (`build.py`, `lib.py`, `baseline.py`; add them if missing). `build.py` rebuilds an empty copy of the real database (tables, constraints, indexes, all functions with their execute rights, triggers) from `sql/schema_snapshot.txt` into a local Postgres 16 (`apt-get install postgresql`, a private server on port 5544), with stand-ins for Supabase's `auth.users`, `auth.uid()`, roles `anon`/`authenticated`/`service_role` and a `storage.objects` table. Known differences from production, patched in `lib.py`: `settings_log.id` and `tickets.reg_seq` are identity columns in production but the snapshot does not show that. `lib.py` has `seed()` (an open event, one admin, booking A with two people, booking B with one) and `call(role, sql)` to run a function as anon or as an admin. `baseline.py` reproduces the old transfer holes (8 of 10 checks failed). `gen_r2_01.py` builds `sql/r2_01_prep.sql` from the real snapshot and `test_r2_01.py` tests it; each later piece gets the same pair. Replica detail: `report` is a view in production, so `build.py` creates it as a view. **Always run new SQL here first**, then keep the real snapshot as the truth: run `sql/schema_snapshot.txt` again after applying changes to Supabase and compare.

**Deliberate-mistake check (17 Oct 2026).** A green test run proves little unless the tests can fail. Before trusting a suite for money or security rules, copy the SQL, break one rule on purpose (remove a check, forget a flag), run the suite on the copy and confirm it fails; for piece 4 this found two real gaps. `lib.py` also counts a script that crashes halfway as a failure and still prints what ran.

---

## 11. Before registration opens (planned 20 Oct 2026; the owner said it may move, so confirm the real date)

1. **Finish Release 2 (section 12), test and risk-proof it**, with `transfers_open` off until R2-5 passes. Restyling (gate scanner, admin dashboard, ticket image) comes only after the app is risk-proof; then re-test the pages. Note: Release 2 also changes the Tickets lookup (Booking ID + phone), adds email and +91, so the registration page must be re-tested end to end before opening.
2. In **Admin > Settings > Payment details**, press Change and type the real UPI ID, payee name and organiser WhatsApp number (with country code). (Do not copy them into this file.) Check the Settings log shows the change.
3. Budgeting team sets the **final price** in Admin, Settings. Confirm the cap (150) and deadline (31 Oct 2026, 23:59:59 IST).
4. Do a small real test payment (for example ₹1) and scan it in two UPI apps.
5. **Delete all test data** (do this once, right before launch, after all testing). In the Supabase SQL editor, in this order:
   ```sql
   -- check first: this only counts, it changes nothing
   select (select count(*) from tickets) as tickets, (select count(*) from bookings) as bookings,
          (select count(*) from screenshot_scans) as scans, (select count(*) from staff) as staff;

   -- delete (tickets first, then bookings; scans go with their bookings)
   delete from tickets;
   delete from bookings;
   update settings set next_ticket = 1, next_coord = 1 where id = 1;
   ```
   (Transfer rows go with their tickets automatically; `settings_log` is not cleared, which is fine.) Then **empty the `payment-proofs` bucket** in the Storage section of the dashboard (SQL cannot delete stored files). Check again: all counts 0 and staff 2 (the owner and the friend admin; use the real number of people added so far), and `select next_ticket, next_coord from settings;` shows `1, 1`. Do not delete `staff`.
6. The cap reads 150 and the deadline is correct (confirmed 14 Oct 2026). Make sure the **price is final** (currently ₹250) and the cap is still 150 after any further testing.
7. In Supabase Authentication, **"Allow new users to sign up" is off** (confirmed 14 Oct 2026). Re-check it before launch in case it was changed.
8. **Create the remaining organiser logins** (the two gate members and anyone else; the owner and the friend admin already exist) as in section 2, then test each login, and check that gate users cannot open the admin page.
9. Check that the keepalive and snapshot workflows show green ticks in the Actions tab.
10. Turn **Registration open** on in Settings, and only then share the link.

---

11. **After applying `r2_05` (IP flag):** make one registration from your phone on mobile data and one on WiFi, then in the Supabase SQL editor run `select ip, raw from booking_ips order by created_at desc limit 5;` to confirm the stored address is your real one and see which header (`cf=` or `xff=`) holds it; tell Claude if it looks wrong. After the event run `select admin_ip_flags();` once to review, then `select admin_clear_client_ips();` to delete every stored address.

## 12. Status and next steps

**Done (as of 16 Oct 2026):**
- The three pages, the database and all functions, OCR scanning, coordinator handling, keep-alive, nightly schema snapshot.
- Security hardening: `report` view follows staff-only access, internal helper functions locked down, bucket size and type limits, read-only `snapshot_reader` for the snapshot.
- `undo_checkin` supports coordinators (by ticket id) and the **Undo** button exists in the People tab.
- Numbering rule "a number stays with its person" (coordinator numbers are also kept), with the gate showing TICKET CANCELLED for retired coordinator numbers.
- Overview redesigned (Active tickets, Spots used, Present matching the gate).
- Full test passed (section 10).
- **Release 1 (16 Oct 2026):** payment details now live in Admin Settings (locked until Change is pressed), the Pay screen reads them fresh and re-checks every 30 seconds, a Settings log and a 7-day alert banner exist, the `staff.role` default was removed, the Booking ID was removed from the ticket image, page heading and PDF name, and the tap-to-pay link was removed (UPI apps refuse it). Details in section 13.
- Restyle: only the **public page** is done (ivory and green, light). The gate and admin pages still have the old colours.
- Daily pause with 10-minute grace: SQL tested on a scratch Postgres with a fake clock, and both pages tested in a headless browser with a mocked server. **Still to be tested by the owner on the real site** (see the test steps given with the update).

**Immediate task (owner's order, 17 Oct 2026): build Release 2 as designed below, then test and risk-proof it, then restyle.** The database part (pieces 1 to 4) is written and tested on the scratch database but **not applied to Supabase**, and no page has been changed yet. Work happens in small steps; the owner approves each step before the next.

### Release 2: build steps

1. **R2-0 Notes:** this section (done 17 Oct 2026).
2. **R2-1 Database (pieces 1 to 5 written and tested, NOT applied to Supabase).** Done so far: **piece 1** (17 Oct 2026), `sql/r2_01_prep.sql`, written and passing 39 scratch-database tests but **not yet applied to Supabase**. It adds `tickets.email` (required for new bookings, checked for format, stored lower-case), `tickets.transferred_out_at` and `tickets.transferred_from`, `bookings.kind` (`registration` or `transfer`), the settings `transfer_cutoff_at`, `transfer_food_locked` and `private_code_hours` (1 to 168, default 2; `price_per_head` is the amount asked from a public buyer; `max_resale_price` is an old column and no longer used), makes the two cap counters ignore transferred-out tickets, makes `submit_booking` require an email per person, and adds email, `transferred_out_at` and `booking_kind` to the end of the `report` view. Phones were already stored as exactly 10 digits, so +91 is display only. **Piece 2** (17 Oct 2026), 54 scratch tests passing, not applied: `sql/r2_02_lookup.sql` adds `lookup_tickets(booking_id, phone)` (returns only the tickets whose phone matches; every failure returns the identical `{found:false}`; a transferred-out ticket shows `transferred:true` with no QR secret; email is never returned; transfer-kind bookings are not served yet, a later piece adds them); `sql/r2_02b_cutover.sql` drops the old `lookup_booking` (Booking ID alone) and must go in **at the same moment as the new Tickets page**; `sql/r2_02c_close_old_transfer_doors.sql` revokes public access to the 13 old transfer functions (no page uses them) and is **safe to apply right now**. **Apply order:** 2c now if wanted; `r2_01`, `r2_02`, `r2_02b`, `r2_03` and `r2_04` together (in that order) only when the new registration and Tickets pages are live. **Piece 3: the code flow, private transfer** (17 Oct 2026, buyer-side and status functions renamed `transfer_*` and made to accept both modes after the final design), `sql/r2_03_private_transfer.sql`, 152 scratch tests passing (stable over repeated runs, including simultaneous-click tests), **not applied** (requires `r2_01` and `r2_02`). It adds: tables `transfers` and `transfer_buyers` (admin-read-only, no write access for anyone but the functions); `bookings` may now be `kind = 'transfer'` (no screenshot, amount 0); `settings_log.area` may be `transfer`; visitor functions `private_sell(booking_id, ticket, phone)` (6-character code from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, valid `private_code_hours`), `transfer_status(booking_id, phone)`, `transfer_cancel(...)`, `transfer_open(code)` (generic `INVALID_CODE` for wrong, expired, used, replaced or cancelled codes), `transfer_submit(code, submission_id, buyer json)` (creates the buyer's transfer booking, first valid submission wins, safe to retry with the same submission id); admin functions `admin_transfer_confirm_call`, `admin_transfer_approve` (the swap, one transaction, uses the normal `_assign_numbers` rule, needs the call tick, never fails because the cap is reached, leaves the cap, revenue and active counts unchanged) and `admin_transfer_reject`; `lookup_tickets` replaced by a version that also serves the buyer's transfer booking (Booking ID + the BUYER's phone: pending, rejected, or the new ticket once approved); `set_booking_status` refuses transfer bookings (`USE_TRANSFER_TOOLS`) and closes a booking's open transfers if an admin rejects or reopens it; `admit_ticket` shows a transferred-out ticket as CANCELLED with the current holder (follows a seat that moved twice); every step is written to `settings_log` (who, never phones, emails or QR secrets). Seller answers use `{ok:true|false, error}` instead of raising, because a raised error would undo any attempt counter and gives the page one simple shape; error codes: `MISMATCH` (never says which detail was wrong), `TRANSFERS_CLOSED`, `CUTOFF_PASSED`, `NOT_CONFIRMED`, `COORDINATOR`, `ALREADY_CHECKED_IN`, `ALREADY_TRANSFERRED`, `ALREADY_PENDING`, `TRY_AGAIN`, `NOTHING_TO_CANCEL`, `CONTACT_ADMIN`, `INVALID_CODE`, `NOT_AVAILABLE`, `INVALID_NAME/PHONE/EMAIL/LOCATION/ATTENDANCE/FOOD/CONSENT/DATA`. Not done yet: the admin and public pages (steps R2-2 to R2-4), the public transfer (piece 4: listings, reservations, payment verification, payout, returns, the Transfer money panel data) and a cleanup piece (piece 5: drop the old transfer tables and functions, the IP flag, the old `ticket_transfers` branches in `admit_ticket`). **Piece 4: public transfer via the same code** (17 Oct 2026, FINAL design), `sql/r2_04_public_via_code.sql`, 156 scratch tests passing (stable over repeated runs; the 39, 54 and 152 tests of pieces 1 to 3 also pass, the piece-3 suite also with piece 4 on top; 8 of 8 deliberate mistakes put into the SQL were caught by the tests), **not applied** (requires `r2_01` to `r2_03`; it replaces `transfer_status`, `lookup_tickets`, `admin_transfer_approve`, `admin_transfer_reject` and `_close_open_transfers` with extended versions). **The public transfer is the same code flow as the private one, with the money going through the organisers.** `transfers` gains `seller_upi`, `amount_due`, the payment fields (`payment_requested_*`, `payment_submission_id`, `payment_screenshot_path`, `payment_submitted_at`, `payment_verified_*`, `amount_received`), payout fields (`seller_paid_*`, `payout_reference`) and return fields (`return_due`, `returned_*`, `return_reference`). **Visitor functions:** `public_sell(booking_id, ticket, phone, payout_upi)` (a public code; no price), `transfer_pay(booking_id, phone, submission_id, screenshot_path)` (the buyer's screenshot, only after the admin asked for payment); `transfer_status` also tells the seller the mode and, once done, `to_be_paid` or `paid` and the amount they will receive; `lookup_tickets` tells a public buyer the state: `pending`, `payment_due` (with the amount), `payment_submitted`, `payment_verified`, `rejected`, `return_due`, `returned`. **Admin functions:** `admin_transfer_extend_code(transfer, hours 1 to 168)` (also revives an expired code), `admin_transfer_request_payment` (needs the seller call tick; asks the standard `price_per_head`, fixed at that moment), `admin_transfer_verify_payment(transfer, amount)` (the admin enters what actually arrived: any amount from 1 to 1,000,000, more or less than asked), `admin_transfer_approve` (private: call tick; public: call tick AND verified payment; same swap for both), `admin_transfer_reject` (marks the return as due if the buyer had uploaded a screenshot), `admin_transfer_mark_paid(transfer, reference)` (the seller is paid exactly the amount received), `admin_transfer_mark_returned(transfer, reference)`, `admin_transfer_money()` (the Transfer money panel: awaiting payment, awaiting verification, verified and waiting, to pay out, paid out, return due, returned, held now). A seller's booking being rejected closes an open transfer and marks the return as due if money was sent. Private transfers never touch any of this (tested). **The earlier public designs (board with reservations, then admin-matched waiting list) are NOT used; their SQL and tests are kept in `sql/archive/` and `scratch-db/archive/` and must never be applied.** **Piece 5: clean-up of the old backend and the IP flag** (17 Oct 2026), `sql/r2_05_cleanup_and_ip.sql`, 77 scratch tests passing (stable over repeated runs; every earlier suite still passes alone, and the piece-3 and piece-4 suites also pass with piece 5 on top; 7 of 7 deliberate mistakes put into the SQL were caught), **not applied** (requires `r2_01` to `r2_04`; apply when the new pages are live). **Clean-up:** drops the 22 old transfer functions (`apply_receive`, `check_request`, `close_listing`, `edit_listing`, `express_interest`, `get_transfer_status`, `list_board`, `lookup_transfer`, `manage_ticket`, `post_listing`, `start_transfer`, `submit_transfer_payment`, `withdraw_transfer`, `approve_transfer`, `decline_transfer`, `admin_confirm_amount`, `admin_mark_payment_received`, `admin_mark_seller_paid`, `admin_mark_refunded`, `admin_remove_listing`, `admin_clear_comment`, `admin_set_transfer_settings`), six helpers only they used (`_seller_ticket`, `_transfer_block_reason`, `_clean_comment`, `_clean_payout`, `_seller_kind`, `_norm_code`) and the tables `ticket_transfers`, `ticket_interests`, `ticket_listings`. Checked first that nothing else referred to them: no page calls them, and the gate function's two branches for old retired numbers were removed in piece 3. The settings column `max_resale_price` stays but is unused. **IP flag (flag only, never blocks):** `booking_ips` is an admin-only table (`ip`, `raw`) filled by `submit_booking` for every registration (not for transfers); gate staff cannot read it and `bookings` has no IP column. `_client_ip()` uses Cloudflare's `cf-connecting-ip`, otherwise the LAST address in `x-forwarded-for`, and accepts only characters valid in an address. The raw header text (cut to 300 characters) is stored too, so the owner can check on the real project which header is trustworthy (a client can fake `x-forwarded-for`). `admin_ip_flags()` returns the addresses with at least `ip_flag_threshold` registrations (setting, default 5, allowed 2 to 1000) with pending, paid and rejected counts, plus a map Booking ID to address for the dashboard; `admin_clear_client_ips()` deletes every stored address (to do after the event; logged without any address). Not done yet: the pages (R2-2 to R2-4) and the registration page changes. Still to write: **piece 6** (`admin_set_transfer_settings` and `get_transfer_info`, gaps G1 and G2 in `HANDOVER_NEXT_SESSION.md`). Every piece is written and tested on a scratch Postgres (rebuilt from `sql/schema_snapshot.txt`) before anything touches Supabase, then pasted into `sql/changes.sql`:
   - email column (per person, required, format-checked) and the phone rule (10 digits stored, "+91" only displayed);
   - the new **Booking ID + phone** ticket lookup, replacing `lookup_booking`;
   - the new transfer tables and functions below; the **old** transfer tables and functions are dropped (nothing uses them);
   - new `settings` columns, the `bookings.kind` column and the cap/revenue exclusion for transfer bookings;
   - an audit log trigger for every transfer step (extend `settings_log`, area `transfer`);
   - an admin-only IP table and the admin flag (flag only, see "Other agreed items"; built in piece 5).
3. **R2-2 Admin:** the **Transfers** tab: every active code (both modes) with seller, seat, created, expires, **Extend** and **Cancel**; transfers waiting for the admin with the original ticket beside the buyer's details, the **seller call tick**, **Ask buyer to pay** (public), the buyer's screenshot, an **amount received** box (public), **Transfer**, **Reject**; payouts to sellers and returns to buyers with a reference box; the Transfer money panel; the new settings. Transfer work is done by ONE admin (owner), but every admin has the authority.
4. **R2-3 Public pages:** Tickets page (new lookup, cached Booking IDs), Transfer tickets screens: **Sell** (private: Booking ID, ticket, phone; public: also the payout UPI ID) showing the code and when it expires; **Buy** (type the code, fill the Transfer Form); the status page by Booking ID + phone with **Pay ₹X** (UPI QR from Settings and a screenshot upload) when a public payment is due; Contact now buttons. No board and no interest form.
5. **R2-4 Registration changes:** email field, fixed +91 prefix, logo placeholders, About placeholder link.
6. **R2-5 Full test and risk review** (attack list below), fix everything found, re-test.
7. **R2-6 Restyle** (kept further down), then a final re-test.

### Release 2: agreed design (owner, 17 Oct 2026)

**A. Ticket status check (changed).** The person enters **Booking ID + phone** (phone is always typed; "+91" is fixed in front). The result is only the tickets in that booking whose phone matches (normally one; several if the same number was used for several people). A wrong combination gives one generic message ("No ticket found for these details") that never says which part was wrong. Booking IDs the device has used stay cached as a history list; tapping one fills in the Booking ID, the phone must still be typed. Booking ID alone shows nothing, not even the QR secret. A booker with several different phones does one lookup per phone (intended). No attempt counting is needed: Booking IDs are no longer shared with anyone, and guessing needs both the Booking ID and the phone.

**B. Rules for both kinds of transfer.**
- A ticket received through a transfer can be sold on again (open item 8). Only a **confirmed (paid)** ticket that is not checked in, not cancelled and has no other open transfer can be sold. One open transfer per ticket (database-enforced).
- The seller proves identity with **Booking ID + ticket number + the phone entered for that seat**; all three must match the same ticket. Any mismatch shows "Submission failed due to details mismatch" (never which part).
- The seller's details are never shown to the buyer except the seller's **name** (private form sub-heading, public listing). No ticket number, phone or Booking ID is ever shared between buyer and seller. A listing page has a short consent line that the name is shown publicly.
- The **admin's phone call to the number registered on the original ticket is the final identity check** (it works like a password: the caller is the person who booked). For a **private** transfer the admin must tick "Seller confirmed by phone" before **Transfer** is enabled. For a **public** transfer that call happens earlier, when the listing is approved (D2), and **Transfer** is enabled as soon as the buyer's payment is verified; the seller is not contacted again until the payout.
- The buyer gets a **new Booking ID** at submit, like a normal registration. That booking is `kind = transfer`: it holds **no seat and no ticket number**, is not counted in the cap, in Active/Pending counts or in revenue, and shows "Pending verification".
- **Approval (Transfer button) is one database transaction:** re-check the seller's ticket is still active and not checked in and the transfer is still valid; cancel the seller's ticket (its number is retired and never given to anyone else, section 7); issue the buyer a **new guest number and a new QR secret** (next `next_ticket`); the buyer's booking becomes paid. It is a seat swap, so it **must not fail because the cap is reached** (that is exactly when transfers happen) and it leaves the cap, Active and revenue totals unchanged.
- The old QR must show TICKET CANCELLED at the gate and the new QR must admit once (tested, also for a seat transferred twice).
- If an admin rejects or cancels the seller's booking or ticket while a transfer is open, the transfer closes automatically.
- Food: when the admin turns on `transfer_food_locked` (after the food order is placed), the buyer's food choice is fixed to the seller's original and the form says so.

**C. Private transfer (the two people already know each other; no money passes through the organisers).**
1. Seller: Tickets, Transfer tickets, Private transfer, **Sell**. Enters ticket number, Booking ID, phone. If all match, the system shows a random **6-character code** (uppercase letters and digits without look-alikes such as 0/O and 1/I), valid for **2 hours** (`private_code_hours`). A new code for the same ticket cancels the old one.
2. Seller checks later: Booking ID (from the device list) + phone shows the status: code and time left, buyer submitted (the buyer's name only, never the phone), approved, rejected, expired.
3. Buyer: Tickets, Transfer tickets, Private transfer, **Buy**. Types the code. Wrong: "Invalid code". Right: the **Transfer Form** opens (heading "Transfer Form", sub-heading "Buying <seller name>'s ticket"). The code stays valid until a buyer **submits** or the 2 hours end, so a buyer who closes the page can simply type it again and is not blocked. The first submission wins; anyone else sees "already used".
4. Form: name, email, phone (+91), attending, food (locked if the setting is on) and a consent tick that payment between the two people is their own business and the organisers are not responsible. No payment step.
5. Submit: the buyer sees the new Booking ID (cached), "Pending verification", the message "The organizers (admins) will be notified of this request, and will take necessary actions soon" and a **Contact now** button (WhatsApp to the number in Settings).
6. Admin sees a summary: **original ticket** (name, phone, ticket number, booking) beside the **seller's entered details** and the **buyer's details**. The admin calls the seller's registered phone: "Shall I transfer this ticket to Mr. B as per our records? We assume the payment is settled between you two, as you opted for a private transfer." After the tick, **Transfer** (or Reject with a reason).

**D. Public transfer (the seller has no buyer; money passes through the organisers).** FINAL design (owner, 17 Oct 2026): it uses the SAME code flow as a private transfer. There is no board, listing, interest form, matching or timer; the earlier marketplace and admin-matching designs are archived and unused.
1. **Seller:** Tickets, Transfer tickets, Public transfer, **Sell**: Booking ID, ticket number, phone and a **payout UPI ID** (or phone). No price: the organisers ask every buyer the same standard ticket price. The seller gets a **code**, valid `private_code_hours` (default 2, the admin can **extend** any code up to 168 hours, and a seller can make a new one at any time).
2. **Finding the buyer:** the admin sees every active code in the Transfers tab and gives the code to a buyer they found. The buyer opens Tickets, Transfer tickets, Public transfer, **Buy**, types the code and fills the **Transfer Form** (like registration, no payment yet). They get a new Booking ID with "Pending verification" and a Contact now button.
3. **Admin phones the seller** (is the ticket still theirs? reads back the payout UPI ID), ticks the call, then presses **Ask buyer to pay**. The buyer's status page shows **Pay the standard ticket price** with the UPI QR from Settings; the buyer uploads one screenshot.
4. **Admin checks the bank and enters the amount actually received** (more or less than asked is fine) and presses **Transfer** (needs the call tick and the verified payment). Swap as in section B.
5. **Admin pays the seller exactly the amount received** and marks it with a reference. If the transfer fails after the buyer paid (the seller entered the hall, the seller's booking was rejected, the admin rejects it), the amount received is **returned to the buyer** and marked returned with a reference.
6. **Private transfer is unchanged:** the money is between the two people and never passes through the organisers.

**E. Settings (new, all admin-editable, all logged):** `transfers_open` (off until R2-5 passes), `transfer_cutoff_at` (blocks new codes, buyer forms and payment uploads; admin actions on existing transfers continue), `transfer_food_locked` (the buyer gets the seller's food), `private_code_hours` (1 to 168, default 2). The existing `price_per_head` is the amount asked from a public buyer; `max_resale_price` is an old column and no longer used.

**F. Money.** A public buyer's payment never goes into `bookings.amount` or the revenue and Overview totals (a transfer booking has amount 0). The **Transfer money** panel (`admin_transfer_money()`) shows: awaiting payment, awaiting verification, verified and waiting for Transfer, to pay out to sellers, paid out, return due, returned, and **held now**. The amount asked is fixed when the admin requests payment. Every money step is logged with who and when, without phones, UPI IDs or emails.

**G. Data model (as built in `sql/r2_03` and `sql/r2_04_public_via_code.sql`).** `transfers` (one sale per seat: code, `kind` private or public, and for public the payout UPI and all money fields), `transfer_buyers` (the buyer's form), plus `bookings.kind`, `tickets.email`, `tickets.transferred_from`, `tickets.transferred_out_at` and the settings above. Both transfer tables are admin-read-only; visitors reach them only through `SECURITY DEFINER` functions that return generic failures. The old `ticket_transfers`, `ticket_listings`, `ticket_interests` are dropped in piece 5.

**H. Other agreed items.**
- **Email** is asked after name (and the other fields) at registration and in the Transfer Form: required, format-checked, stored per person, readable by admins only, with a line on why it is collected. Nothing sends email yet.
- **Phone:** a fixed, uneditable "+91" is shown at every phone field. The database stores only the 10 digits (keeps old data valid and WhatsApp links working).
- **Mallu Articles Bengaluru logo:** placeholders now at the places the owner wants; the owner will send the file (SVG or transparent PNG).
- **About Mallu Articles Bengaluru:** a new link beside Register for meetup and Tickets. Content (text, last year's reels as links with thumbnails, photos, permission for faces) is discussed later; a placeholder page for now.
- **Anti-spam (owner's decision on IP):** BUILT in piece 5 (`booking_ips`, `admin_ip_flags()`, `admin_clear_client_ips()`): the visitor's IP is recorded on each registration, **flag only, never blocks**; the admin sees a flag when one address has `ip_flag_threshold` (default 5) or more registrations; admin-only; deleted after the event. IP is not a device: shared WiFi and mobile networks can share one address. **To verify on the real project after applying:** which header holds the real address (checklist in section 11). Not yet decided: one open booking per phone, a limit on spots held by pending bookings, a minimum time on the form, a "reject all pending from this phone" button, and storage cleanup of rejected screenshots.

### Release 2: attack tests (must all pass in R2-5)

1. Wrong or partial seller details (wrong ticket, phone of another seat, another booking's ID): refused with the generic message, nothing created.
2. A booking ID alone returns nothing; a phone alone returns nothing; right ID with another seat's phone returns only that phone's tickets.
3. Private: wrong code, expired code, reused code, two buyers submitting at once (first wins), old code after a new one is made, the seller never sees the buyer's phone, the buyer never sees the seller's ticket number or phone.
4. Public (via code): wrong seller details and payout IDs; a code replaced across modes; the buyer's payment before it was requested; Transfer without the call tick or without a verified payment; any amount accepted at verification; the seller in the hall; the seller's booking rejected; returns; two admins pressing Transfer or Verify together; private transfers never touching money; buyer and seller never seeing each other's details (tests in `test_r2_04.py`).
5. Approval: seller checked in meanwhile; seller's ticket cancelled by admin meanwhile; two admins approving at once; cap full (swap must still work); counts, revenue and Overview unchanged; numbering rules of section 7 (old number never reused, buyer gets the next guest number); transfer booking holds no seat and has no ticket before approval.
6. Gate: old QR shows TICKET CANCELLED, new QR admits once, a seat transferred twice, no ticket secret ever returned for a pending transfer booking.
7. Cut-off: no new listing or private code after `transfer_cutoff_at`; pending ones can still be approved or rejected.
8. Transfers off (`transfers_open` false): every transfer function refuses, registration is unaffected.
9. Audit log has a row for every admin and money step; transfer tables are not readable by anon.
10. Food lock: buyer gets the seller's food, cannot change it through the API either.

### Release 2: open items (owner to confirm; recommended defaults are in use until then)

1. **Rare cases where a public buyer has paid and the transfer cannot complete** (the seller entered the hall, the seller's booking was rejected, the amount received is wrong, the admin revokes the listing). Built and recommended: the organizers **return the buyer's money for that ticket** (for every ticket of an "all together" buyer), recorded as a return with a reference; normal registrations stay no-refund. Owner to confirm.
2. **Coordinator and free tickets:** recommended that they **cannot be sold through the website** (message "contact the admin"), because numbering and cost rules differ.
3. **Resolved (owner, 17 Oct 2026):** no second phone call to the seller before a public Transfer. The seller is called when the listing is approved and again only for the payout.
4. **What the private seller sees after the buyer applies:** recommended the buyer's **name only**, so the seller can spot a stranger who got the code.
5. **Private code length:** 6 characters as asked. A stranger who guesses a live code is stopped by the admin's phone call to the seller, so this is accepted; if wrong-code guessing is ever seen in the log, lengthen to 8.
6. The anti-spam options listed under H that are still undecided.
7. Logo file and the About page content (owner will send later).
8. **Resolved (owner, 17 Oct 2026):** a ticket received through a transfer is treated like any regular ticket (the new holder has a Booking ID, a ticket number and a phone) and can be sold on again; every move still needs the admin's checks and retires the old ticket number.
9. **Resolved (17 Oct 2026):** no marketplace, listings, interest forms, matching or reservations exist any more; the public transfer is the same code flow as the private one.
10. **Code lifetime (assumed 17 Oct 2026, owner to confirm):** default 2 hours, the setting can be raised to 168, and the admin can **Extend** any active code (also an expired one), because finding a buyer can take days.
11. **Public buyer pays the standard ticket price** (`price_per_head`, fixed when the admin asks), the admin enters whatever amount actually arrived, and the seller is paid exactly that (owner: "unbothered" by resale price). Private transfers involve no organiser money.
12. **Who sees what:** the seller sees the buyer's NAME once they applied (never phone or email); the buyer sees the seller's NAME when the form opens (never phone, UPI, ticket number or Booking ID).

### Final review findings (17 Oct 2026; details and fixes in `HANDOVER_NEXT_SESSION.md` section 6)

1. **No function can change the new settings** (`transfers_open`, `transfer_cutoff_at`, `transfer_food_locked`, `private_code_hours`, `ip_flag_threshold`): the old `admin_set_transfer_settings` was dropped in piece 5. Needs **piece 6** (`admin_set_transfer_settings`).
2. **No visitor-readable "are transfers open"**: needs `get_transfer_info()` in piece 6.
3. **`tickets.email` is readable by every staff login** (gate volunteers can select all columns of `tickets`), although this file promises admin-only. Decide: accept, separate admin-only table (recommended while nothing is applied), or column privileges.
4. **Admin and gate pages double-count after a transfer** (they count tickets in the browser from `people()` and a fixed select list; the retired ticket's booking is still `paid`). Both pages must ignore `transferred_out_at` before the first transfer; the admin Bookings and OCR queues must ignore `kind = 'transfer'` bookings.
5. **The public Tickets page auto-refetches every saved Booking ID**, which conflicts with Booking ID + phone; saved IDs must become tap-to-fill chips.
6. **Rollout order matters** (page with email first, then `r2_01`/`r2_02`, admin/gate fixes, new Tickets page, then `r2_02b`, then `r2_03` to `r2_05`); see the handover section 2.2.
7. The scratch copy does not reproduce grants and row-level security of the OLD tables; after applying SQL, rebuild from the new snapshot and rerun all suites.

### Old transfer backend: security audit (16 Oct 2026, read from `sql/schema_snapshot.txt`). SUPERSEDED by the design above; kept because each hole is a test case

Status: the database has a first version of the transfer functions, but **no page uses them and `transfers_open` is false**. The planned hardening (buyer PIN with lockout, the seller's phone as a second check, one transfer per seat, the Booking ID no longer exposing a transferred ticket) is **not applied**. Holes found, all to be fixed and tested before transfers are switched on:

1. **Booking ID is the only seller credential.** `_seller_ticket` takes the 8-character Booking ID plus a ticket label. Anyone holding the ID can list, sell or withdraw any ticket in that booking. No second check, no rate limit.
2. **A sold ticket stays visible to the seller.** `lookup_booking` (via `_booking_json`) returns every ticket in the booking, including the buyer's new name and new QR secret, so the seller can keep the buyer's QR.
3. **The seller can re-sell the buyer's ticket.** After a transfer the ticket keeps the same `booking_id` and gets a new number, so the old Booking ID plus the new label passes `_seller_ticket` again.
4. **A phone number acts as a password.** `check_request(listing, phone)` returns the transfer code to anyone who types the phone number the seller chose as buyer (`intended_phone`), and `express_interest` overwrites the name for an existing (listing, phone) pair with no proof that the phone belongs to the person typing. So someone who knows or fakes a victim's number can get the code.
5. **A transfer code holder can overwrite the buyer's application.** While a transfer is `pending_admin`, `apply_receive` replaces the details until the payment is marked. In private mode there is no intended buyer.
6. **Spam and phone harvesting.** `list_board` is public, so listing ids are public; `express_interest` needs no proof, so 50 fake interests can fill a listing and block real buyers, and in private mode "talk" reveals the seller's phone to anyone.
7. **Weak audit trail.** `settings_log` covers settings and staff only. Transfer money steps (confirm amount, mark received, mark seller paid, refund, approve, decline) are not logged, and an admin can mark "payment received" without a screenshot.
8. **Still to test:** the gate's cancelled-ticket message when the same seat is transferred twice, and that an old QR never admits.

**Already in the database (verified in the snapshot):** only one active listing per ticket, only one open transfer per ticket, a ticket number or coordinator number can be transferred away only once (unique `from_ticket_no` and `from_coord_no`), and every transfer table is readable by admins only. **Correction (17 Oct 2026):** an earlier version of these notes said all transfer functions refuse to run while `transfers_open` is false. That was wrong: `close_listing`, `lookup_transfer`, `submit_transfer_payment`, `withdraw_transfer` and `check_request` do not check it (they are inert only because no listing or transfer can exist while it is off). `r2_02c` revokes public access to all of them. A seat can still change hands again after a transfer (the new ticket can be sold), which the planned "one transfer per seat" rule will limit.

**What replaced the planned fixes:** the old buyer-PIN and seller-second-check plan was dropped on 17 Oct 2026. The new design (Booking ID + ticket + phone for sellers, the admin's phone call, a new Booking ID for the buyer, no secret ever returned for a pending transfer) closes holes 1 to 6; hole 7 is closed by the audit trigger; hole 8 is test 6. The old tables (`ticket_listings`, `ticket_interests`, `ticket_transfers`) and about 20 functions are dropped in R2-1.

**Restyle (postponed until Release 2 is built and risk-proof; text kept from 14 Oct 2026):**
1. **Finish the restyle.** Decisions so far (14 Oct 2026): keep the **Kerala green and gold** look but refresh it; the **public registration page is already restyled** (light theme: ivory with green); next are the **gate scanner** and the **admin dashboard**, which will both be **dark themed with the same colour theme** (one shared set of dark colours, so the two staff pages look like a pair. **Chosen palette: "Midnight Emerald"**: page `#0a1612`, card `#11231c`, border `#21392f`, text `#efe9d8` (warm ivory, never pure white), soft text `#98a99e`, green accent `#3fb98d`, gold accent `#d4af5a`. Use gold sparingly, never pure black, and keep the paid/pending/rejected labels and the gate's green/red/amber result screens bright and clearly different on the dark background; today they follow the device's light/dark setting, and the plan is to make them dark always); the **ticket image** (drawn in JavaScript on a canvas, colours written in the code) should be restyled to **match the new look**. Keep the existing behaviour; only change look and feel. The look lives in each page's `<style>` block (colours are named values such as `--green` and `--gold` at the top), plus the colour values inside `drawTicket` in `index.html` for tickets. Keep the gate's big green/red/amber result screens clearly colour-coded. Test again afterwards.

**Ideas and known gaps (none are blockers):**
- In-app screen for gate staff to request access and for admins to approve (currently manual in Supabase).
- Saving settings with an empty deadline field throws an error in the browser.
- The cap can be set below the number already registered (harmless; new bookings just stop).
- The People table and the CSV still show "Present" for people from rejected bookings. Only the Overview card and the gate counters exclude them.
- Booking codes are 8 hex characters and lookups are not rate-limited. Today a Booking ID alone shows tickets; **Release 2 changes this** to Booking ID + phone, which makes guessing impractical, so no attempt counting is planned (owner's decision, 17 Oct 2026).
- ~~The `staff.role` column defaults to `admin`~~ Fixed on 16 Oct 2026: the default was removed, so an insert without a role is refused. Still write the role explicitly.
- Gate search finds a person by guest number digits, by name, phone, current label or Booking ID. A retired coordinator number is not searchable.
- `rejected: N` on the Present card counts people in rejected bookings, including test leftovers until the cleanup.

---

## 13. Change log

- **13 Oct 2026:** Database reviewed from exports and all three HTML pages. Security hardening done (report view, helper functions, bucket limits). `undo_checkin` rewritten to work by ticket id. Project notes and `sql/README.md` created.
- **14 Oct 2026:** Nightly schema snapshot added (`schema-snapshot.yml`, read-only `snapshot_reader`). Numbering rule extended so coordinator numbers also stay with their person (`prev_coord_no`, `prev_coord_secret`, updated `set_coordinator` and `admit_ticket`). Full test passed. Overview changed (Active tickets, Spots used, Present). Admin page accidentally deleted on GitHub and restored from a saved copy with the Overview edits applied. Afternoon checks: helper functions locked, sign-ups off, cap 150, price 250, deadline correct, registration currently closed.
- **14 Oct 2026 (later):** Daily pause + 10-minute grace added: new `settings` columns, `reg_sessions` table, `registration_heartbeat`, `admin_registration_status`, updated `get_public_status`, `submit_booking` and `admin_update_settings`; pause options and live banner in Admin; countdown, paused message and heartbeat on the public page. Run `daily-pause.sql` first, then upload both pages.
- **14 Oct 2026 (end of day):** Decided that the owner and one friend (admin) get logins now, and everyone else is added at the end (section 2). Restyle direction agreed (section 12): public page light (ivory and green), gate and admin dark with one shared colour theme, "Midnight Emerald" (details in section 12). Explained to the owner how an admin is added (create the Supabase login, copy the User UID, insert a `staff` row with the role written explicitly).

- **16 Oct 2026 (Release 1, Part 3a):** Payment details moved from the page code into Settings (`upi_id`, `payee_name`, `whatsapp_number`; `get_payment_info`, `admin_set_payment_info`). The Pay screen loads them fresh when opened, re-checks every 30 seconds, and shows a notice if they change, plus loading/failed/not-set-up states. The QR is scan-only (amount filled in). **Tapping the QR to open a UPI app was tried twice on 16 Oct 2026 (with and without the amount) and removed**: PhonePe, Google Pay and BHIM all refuse payments started from a `upi://` link to a personal UPI ID, while scanning, Share/Download QR and paying to a copied UPI ID work. Do not bring the tap link back. The caption now says: scan the QR, or on this phone take a screenshot and upload it in the UPI app, or pay to the UPI ID. The screenshot box shows "File uploaded · Tap to view · Change" once a file is chosen (the page used to show "No file chosen" next to "Selected"). New `settings_log` table (admin read only; logs settings and staff changes, including ones made directly in Supabase as "database"); Admin shows the Settings log and a 7-day banner to the other admin when payment details change (`admin_payment_alert`). `staff.role` default removed. The Booking ID is no longer drawn on the ticket image, the ticket page heading or the PDF file name. Event date/venue SQL recorded in `sql/changes.sql`. Tests: 151 earlier checks + 49 new database checks, and browser tests of both pages passed. **Transfers stay OFF** (`transfers_open` false); the transfer screens and the hardening SQL (Part 3b) are Release 2. **Decision reversed:** the organisers now handle money for transfers (Public mode), so "never handles money" no longer applies to transfers.

- **16 Oct 2026 (review and audit):** Notes brought up to date with the repo: Release 1 added to Done, stale lines fixed. The transfer backend (tables and about 20 functions) was found already deployed but unused and switched off, and was audited from the schema snapshot: eight issues found, written up in section 12 (Release 2 audit). The owner set the work order: build Release 2, then test and risk-proof, then restyle only afterwards; no deadline pressure on Claude. The restyle of the gate, admin and ticket image is therefore postponed. Stale lines corrected in the same pass: the Pay description (no tap-to-pay, no Share-QR-opens-an-app), the ticket description (no Booking ID on the ticket), the missing Release 1 tables, columns and functions in section 5 and the Admin Settings description, and the known gap about unlimited Booking ID lookups. Decisions, a Release 2 test plan and the verified list of protections already in the database were added. Nothing was changed in code or in the database in this step.

- **17 Oct 2026 (Release 2 design):** The owner replaced the earlier transfer plan with a simpler one: ticket status by Booking ID + phone; private transfer with a 6-character code valid 2 hours and a Transfer Form; public transfer with admin-approved listings, 30-minute reservations and a separate Transfer money panel; a new Booking ID for every buyer; the admin's phone call to the seller as the final check; plus email, a fixed +91, logo placeholders, an About page (later) and IP flagging only. Written into section 12 with build steps, attack tests and open items. Clarified the same day: in a public transfer the seller is called when the listing is approved, the Transfer happens when the buyer's payment is verified, and the seller is contacted again only to be paid. A scratch Postgres rebuilt from the snapshot was set up and the 16 Oct holes were reproduced against the current code (8 of 10 checks failed, which is why the old backend is being replaced). Nothing was changed in the real code or database.

- **17 Oct 2026 (R2-1 piece 1):** `sql/r2_01_prep.sql` written (email, transfer markers, booking kind, new settings, cap counters ignore transferred-out tickets, email required in `submit_booking`, report view extended). 43 tests pass on the scratch database, including running it twice and real-world email formats. Not applied to Supabase yet; the registration page must send an `email` for every person before this is applied, otherwise every booking will be refused with INVALID_EMAIL.

- **17 Oct 2026 (R2-1 piece 2):** `lookup_tickets(booking_id, phone)` written, with a cut-over file that removes the old Booking-ID-only lookup and a file that closes public access to the 13 old transfer functions. 54 scratch tests pass (including identical failure answers, injection-style inputs, group bookings sharing a phone, transferred-out tickets and re-running the files). Found and fixed a wrong statement in these notes about which old transfer functions check `transfers_open`. Not applied to Supabase; see the apply order in section 12.

- **17 Oct 2026 (R2-1 piece 3):** `sql/r2_03_private_transfer.sql` written: the whole private transfer in the database (tables, seller and buyer functions, admin confirm/approve/reject, lookup for transfer bookings, gate and booking-status changes, audit log). 152 scratch tests pass, including the swap with counts before and after (identical), a full hall, two admins pressing Transfer together, eight buyers using one code together, a seat transferred twice, the gate for old and new QRs, row security and re-running the file. Testing found a design gap (a buyer could not sell a received ticket on), now allowed and listed as open item 8; two failing checks turned out to be mistakes in the tests, not in the SQL. Not applied to Supabase.

- **17 Oct 2026 (R2-1 piece 4, FIRST VERSION, SUPERSEDED the same day by the entry below):** `sql/r2_04_public_transfer.sql` written: the whole public transfer in the database (listing request and approval, edits, withdrawal, reservations, payment submission, payment verification, the swap, seller payout, money return, the Transfer money panel data). 228 scratch tests pass, including the swap and counts, a full hall, simultaneous reservations and approvals, late and taken reservations, return paths, automatic closing when the seller's booking is rejected, and a scan that public answers never contain private details. Found and recorded the limit in open item 9. A test that looked like a leak was a mistake in the test (a ticket holder looking up their own booking). The owner confirmed that a transferred ticket is treated like any regular ticket. Not applied to Supabase.

- **17 Oct 2026 (Release 2 public transfer redesigned, piece 4 rewritten; SUPERSEDED the same day by the final entry below):** The owner replaced the public board and 30-minute reservation with a fully admin-handled design: listings and interest forms are visible only to admins and to the person who filled them; buyers fill an interest form for up to 5 people (optionally "all together" and with a maximum price) and pay nothing until the admin phones them; the admin matches by hand, confirms after a phone call, verifies one payment, and presses Transfer. Piece 1's settings changed (`reservation_minutes` replaced by `held_alert_hours` and `interest_max_price_enabled`), piece 4 was rewritten from scratch (new tables `transfer_interests`, `transfer_interest_people`, `transfer_matches`, `transfer_payments`) and its test suite too: 253 tests pass, stable over three runs, with the earlier 43, 54 and 152 still passing. Six first-run failures were all mistakes in the tests (an already-listed seat used as an unapproved one, a buyer already admitted at the gate, a seller left checked in, phone numbers one digit short), not in the SQL. Nothing applied to Supabase.

- **17 Oct 2026 (FINAL transfer design, piece 4 rewritten again):** The owner dropped the marketplace and the waiting list: a public transfer now uses the same code flow as a private one (the admin sees every code and hands it to a buyer), with the money going through the organisers (standard price asked, any received amount accepted, seller paid exactly that, returns when it fails). The earlier piece-4 SQL and tests were moved to `sql/archive/` and `scratch-db/archive/` and are NOT used. Piece 1's settings were reduced (`resale_min_price`, `held_alert_hours`, `interest_max_price_enabled` removed; `private_code_hours` now 1 to 168); piece 3's buyer-side functions were renamed `transfer_open`, `transfer_submit`, `transfer_status`, `transfer_cancel` and accept both modes. 156 tests pass for the new piece 4, with the earlier suites still passing (39, 54, 152). The test harness now counts a crashed script as a failure, and eight deliberate mistakes put into the SQL (for example skipping the payment check, the call tick, or the return flag) were all caught after two real gaps in the tests were closed. Nothing applied to Supabase.

- **17 Oct 2026 (R2-1 piece 5):** `sql/r2_05_cleanup_and_ip.sql` written: the old transfer backend (22 functions, 6 helpers, 3 tables) is dropped and the IP flag is added (admin-only `booking_ips`, `admin_ip_flags`, `admin_clear_client_ips`, setting `ip_flag_threshold`). 77 tests pass; seven deliberate mistakes were caught (one only after strengthening a test that could not tell the difference). The gate function lost its two branches that read the old tables (done in piece 3). The database part of Release 2 (pieces 1 to 5) is now complete on the scratch database and nothing is applied to Supabase. Next: the admin page (R2-2).

- **17 Oct 2026 (final review and handover):** `HANDOVER_NEXT_SESSION.md` written (environment state, rollout order, the transfer case by scenario, page-by-page change list, API reference with real examples, how to rebuild the test setup, task list). The review of the pages and functions found seven items, listed under "Final review findings" in section 12: missing settings function and visitor info function (piece 6), email visible to staff, double counting on the admin and gate pages, the Tickets page auto-refetch, rollout order, and the unreproduced old-table permissions. No SQL or page was changed in this step.

- **24-25 Oct 2026 (Release 2 completed; nothing applied live):** (1) **Emails moved to their own admin-only table `ticket_emails`** (decision G3, owner: "admins only"): `tickets` has NO email column any more; `submit_booking` and the Transfer function write the email there; gate staff see zero rows (tested), the `report` view shows emails to admins only. Pieces 1, 3, 4, 5 and their generators/tests were updated; `tickets.email` described in section 5 is replaced by this table. (2) **Piece 6** `sql/r2_06_transfer_settings.sql`: `admin_set_transfer_settings(p_open, p_cutoff, p_clear_cutoff, p_food_locked, p_code_hours, p_ip_threshold)` (admin only, validated, logged; refuses to switch transfers ON while the UPI ID, payee name or WhatsApp number is missing) and `get_transfer_info()` for visitors (no secrets). Apply it AFTER `r2_05` (that file drops any function of the same name). (3) The scratch copy now **reproduces the real row-level security, policies and table grants** from the snapshot (closes gap G8): `build.py`. (4) **Pages (all three changed):** `gate/index.html` ignores and greys out retired (transferred) tickets and works before and after the database update; `admin/index.html` no longer double-counts retired tickets, hides transfer bookings from Bookings and the OCR queue, adds an Email column (admins) and CSV column, a **Transfers tab** (money panel, waiting transfers with call tick / ask to pay / verify amount / Transfer / Reject, active codes with Extend and Cancel, seller payouts, buyer returns, history), Settings cards for transfers and the repeat-registration flag, an IP banner and a per-booking flag; it also still loads on a database that has NOT been updated. `index.html`: **Email field and a fixed +91 box** on the registration form (a pasted "+91 98765-43210" is cleaned to 10 digits; found and fixed a bug where `maxlength` cut a pasted number before cleaning), the **Tickets page now needs Booking ID + phone every time** (saved IDs are tap-to-fill chips, the phone is never stored, no automatic fetching), the seller screens (private and public), the buyer code and Transfer Form, the buyer payment screen and every buyer state. (5) **Tests:** database suites 62 + 55 + 153 + 157 + 77 + 68 = 572 checks pass; browser tests (headless Chromium with a mocked Supabase, `scratch-db/browser/`) 33 admin + 7 gate + 68 public = 108 checks pass. Deliberate-mistake checks: 4 of 4 (email privacy), 10 of 10 (piece 6), 11 of 11 (public page) caught. Still NOT verified: nothing has run against the real Supabase or the real GitHub Pages site, no real phone/UPI app was used, the real IP header is unchecked (G10), and the transfer screens have not been looked at on a real phone. **The new Tickets page needs `lookup_tickets` in the database, so the pages must not be published before the SQL in the rollout order (handover section 2.2).** `scratch-db/baseline.py` (obsolete) deleted.

---

## 14. Never share

Supabase **service role key**, database password, the `snapshot_reader` password or connection string, staff passwords, or anything from the Supabase dashboard's secret key section. The publishable key in the pages is safe by design.
