# Ehsaas'26 Registration App: Project Notes

Last updated: 14 Oct 2026 (after deciding who gets logins now, and the restyle direction)

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
  - automatic UPI QR and a pay button, with the amount calculated from group size
  - OCR scan of payment screenshots to help admins catch fake or reused proofs
  - automatic ticket generation (JPG/PDF with QR)
  - QR scanning at the gate, with live present/confirmed counts
  - admin controls (cap, price, deadline, open/close)
- **Payment:** there is **no payment gateway** (no business account is involved). The UPI QR on the Pay screen is generated for the exact total (number of people times the price), and there is a **Share QR** button that opens Google Pay, PhonePe or any UPI app with the amount pre-filled. The participant only confirms and enters their UPI PIN, then uploads a screenshot. Organisers verify manually, helped by OCR.
- **Goal:** maximum simplicity for participants and coordinators, with as much automation as possible.

**Key numbers (current settings, adjustable in Admin, Settings):**

| Item | Value |
|---|---|
| Cap (people, confirmed + pending) | 150 (checked 14 Oct 2026, after testing) |
| Price per person | ₹250 (checked 14 Oct 2026); the final price is set by the budgeting team |
| Max group per booking | 5 |
| Registration deadline | 31 Oct 2026, 23:59:59 IST |
| Registration opens | **20 Oct 2026** |
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

The database only accepts the role values **`admin`** and **`gate`**. **Always write the role explicitly: the column default is `admin`**, so leaving it out would give full admin access. To remove someone's access, **delete their row from `staff`** (do not delete their Supabase login: that fails if they have ever reviewed or scanned anything). As of 14 Oct 2026 only the owner (admin) is in the table; the friend (admin) is to be added next, so expect **two** rows (both `admin`) from then on until the end-of-project additions. Sign-ups in Supabase Auth are **off** (confirmed 14 Oct 2026; manual linking and anonymous sign-ins are off too, and email confirmation is on).

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
| `index.html` | Public page: home, register (form, summary, pay with UPI QR, screenshot upload), Tickets (search by Booking ID, view and download tickets as JPG/PDF). A `CONFIG` block at the top holds event text, ticket text, UPI ID, payee name, organiser WhatsApp number and the Supabase URL and key. |
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
- **`bookings`**: one row per payment. `booking_code` (8 hex characters, unique), `submission_id` (unique, prevents double submits), `people_count` (1 to 5), `amount_expected`, `status` (`pending` / `paid` / `rejected`), `screenshot_path`, `reviewed_by`, `reviewed_at`, `reviewed_via` (`admin` or `gate`), `created_at`.
- **`tickets`**: one row per person. `booking_id`, `ticket_no` (unique, the guest number), `coord_no` (the current coordinator number), `kind` (`guest` / `coordinator`), `secret` (12 hex characters, goes in the QR), `orig_secret` (the guest QR secret kept while someone is a coordinator), **`prev_coord_no`** and **`prev_coord_secret`** (a retired coordinator number and its QR secret, kept on the same person), `name`, `phone` (exactly 10 digits), `location`, `attendance`, `food`, `checked_in_at`, `checked_in_by`, `marked_by`, `marked_at`, `reg_seq` (registration order), `created_at`.
- **`screenshot_scans`**: one row per booking (primary key `booking_id`): `txn_ids`, `image_hash`, `read_ok`, `amounts`, `scanned_by`, `scanned_at`. Deleted with its booking.
- **`staff`**: `user_id` (primary key, linked to the login), `name`, `role` (`admin` or `gate` only).
- **`keepalive`**: tiny table for the ping (readable by anon).
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
6. **Ticket:** each person gets a ticket drawn on a canvas (event details, name, food mark, **ticket number**, **Booking ID**, QR with `E26-007|secret`). Download as JPG or PDF per person, or all tickets as one PDF. Coordinator tickets use a different colour and the word COORDINATOR.

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
- **Settings:** registration open switch; when it is on, a **daily pause** box (switch + close time + reopen time, India time, same every day until the deadline); cap, price, deadline, and a reminder checklist. A live status banner (open / paused / closed, and "A user is currently updating even though the registration is closed, using the 10 minutes grace time.") appears at the top of Overview and Settings and refreshes every 15 seconds. Empty deadline no longer causes an error.

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

---

## 11. Before registration opens (20 Oct 2026)

1. **Finish the restyle (gate scanner, admin dashboard, ticket image) and re-test the pages** (section 12).
2. In the `CONFIG` block of `index.html`, replace the **test** values with the real ones: UPI ID, payee name, organiser WhatsApp number. (Do not copy them into this file.)
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
   Then **empty the `payment-proofs` bucket** in the Storage section of the dashboard (SQL cannot delete stored files). Check again: all counts 0 and staff 2 (the owner and the friend admin; use the real number of people added so far), and `select next_ticket, next_coord from settings;` shows `1, 1`. Do not delete `staff`.
6. The cap reads 150 and the deadline is correct (confirmed 14 Oct 2026). Make sure the **price is final** (currently ₹250) and the cap is still 150 after any further testing.
7. In Supabase Authentication, **"Allow new users to sign up" is off** (confirmed 14 Oct 2026). Re-check it before launch in case it was changed.
8. **Create the remaining organiser logins** (the two gate members and anyone else; the owner and the friend admin already exist) as in section 2, then test each login, and check that gate users cannot open the admin page.
9. Check that the keepalive and snapshot workflows show green ticks in the Actions tab.
10. Turn **Registration open** on in Settings, and only then share the link.

---

## 12. Status and next steps

**Done (as of 14 Oct 2026):**
- The three pages, the database and all functions, OCR scanning, coordinator handling, keep-alive, nightly schema snapshot.
- Security hardening: `report` view follows staff-only access, internal helper functions locked down, bucket size and type limits, read-only `snapshot_reader` for the snapshot.
- `undo_checkin` supports coordinators (by ticket id) and the **Undo** button exists in the People tab.
- Numbering rule "a number stays with its person" (coordinator numbers are also kept), with the gate showing TICKET CANCELLED for retired coordinator numbers.
- Overview redesigned (Active tickets, Spots used, Present matching the gate).
- Full test passed (section 10).
- Daily pause with 10-minute grace: SQL tested on a scratch Postgres with a fake clock, and both pages tested in a headless browser with a mocked server. **Still to be tested by the owner on the real site** (see the test steps given with the update).

**Immediate task:**
1. **Finish the restyle.** Decisions so far (14 Oct 2026): keep the **Kerala green and gold** look but refresh it; the **public registration page is already restyled** (light theme: ivory with green); next are the **gate scanner** and the **admin dashboard**, which will both be **dark themed with the same colour theme** (one shared set of dark colours, so the two staff pages look like a pair; today they follow the device's light/dark setting, and the plan is to make them dark always); the **ticket image** (drawn in JavaScript on a canvas, colours written in the code) should be restyled to **match the new look**. Keep the existing behaviour; only change look and feel. The look lives in each page's `<style>` block (colours are named values such as `--green` and `--gold` at the top), plus the colour values inside `drawTicket` in `index.html` for tickets. Keep the gate's big green/red/amber result screens clearly colour-coded. Test again afterwards.

**Ideas and known gaps (none are blockers):**
- In-app screen for gate staff to request access and for admins to approve (currently manual in Supabase).
- Saving settings with an empty deadline field throws an error in the browser.
- The cap can be set below the number already registered (harmless; new bookings just stop).
- The People table and the CSV still show "Present" for people from rejected bookings. Only the Overview card and the gate counters exclude them.
- Booking codes are 8 hex characters and lookups are not rate-limited (fine for this size of event).
- The `staff.role` column defaults to `admin` (always set the role explicitly).
- Gate search finds a person by guest number digits, by name, phone, current label or Booking ID. A retired coordinator number is not searchable.
- `rejected: N` on the Present card counts people in rejected bookings, including test leftovers until the cleanup.

---

## 13. Change log

- **13 Oct 2026:** Database reviewed from exports and all three HTML pages. Security hardening done (report view, helper functions, bucket limits). `undo_checkin` rewritten to work by ticket id. Project notes and `sql/README.md` created.
- **14 Oct 2026:** Nightly schema snapshot added (`schema-snapshot.yml`, read-only `snapshot_reader`). Numbering rule extended so coordinator numbers also stay with their person (`prev_coord_no`, `prev_coord_secret`, updated `set_coordinator` and `admit_ticket`). Full test passed. Overview changed (Active tickets, Spots used, Present). Admin page accidentally deleted on GitHub and restored from a saved copy with the Overview edits applied. Afternoon checks: helper functions locked, sign-ups off, cap 150, price 250, deadline correct, registration currently closed.
- **14 Oct 2026 (later):** Daily pause + 10-minute grace added: new `settings` columns, `reg_sessions` table, `registration_heartbeat`, `admin_registration_status`, updated `get_public_status`, `submit_booking` and `admin_update_settings`; pause options and live banner in Admin; countdown, paused message and heartbeat on the public page. Run `daily-pause.sql` first, then upload both pages.
- **14 Oct 2026 (end of day):** Decided that the owner and one friend (admin) get logins now, and everyone else is added at the end (section 2). Restyle direction agreed (section 12): public page light (ivory and green), gate and admin dark with one shared colour theme. Explained to the owner how an admin is added (create the Supabase login, copy the User UID, insert a `staff` row with the role written explicitly).

---

## 14. Never share

Supabase **service role key**, database password, the `snapshot_reader` password or connection string, staff passwords, or anything from the Supabase dashboard's secret key section. The publishable key in the pages is safe by design.
