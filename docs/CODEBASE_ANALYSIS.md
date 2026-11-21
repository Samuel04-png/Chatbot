# Rudo: current codebase analysis

> Historical discovery baseline. Local implementation is now authorized and documented in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md); original source references below describe the audited snapshot. Remote execution remains pending review.

Audit date: 2026-11-20 (Africa/Lusaka). Scope: the local cPanel-derived directory and a public, pinned reference repository. Status: discovery complete; implementation and all external changes await owner review.

## Evidence and limits

**Confirmed** means directly observed in source or an explicitly described offline check. **Inferred** means suggested by code, without deployment evidence. **Unresolved** requires owner evidence. Static source is not proof that a route is internet-accessible, a credential is active, a provider is enabled, or a workflow succeeds in production.

The original directory contains 64 files: 15 HTML pages, one Python application, one requirements file, 18 JavaScript files, 17 CSS files, ten images and two logs. All paths were inventoried; first-party application logic, HTML scripts, dependency headers and local asset references were inspected. Vendor bundles were inventoried and searched, not exhaustively audited internally. Log bodies and image contents were deliberately excluded: they are unnecessary for initial discovery and may contain private material. No data export, production API, authenticated external account, application server or inference service was accessed. Only public GitHub source and official technical documentation were retrieved externally.

No AGENTS.md, Git metadata, automated test suite, package lock, Supabase migration, environment template, WSGI entry point, cPanel configuration, cron definition or deployment manifest exists in the supplied local tree. Their absence here does not prove absence on the host. Requirements are `Flask>=3.0,<4` and `requests>=2.31,<3` (requirements.txt:1–2); deployed versions are unknown. The urllib requests fallback in app.py:12–56 adds a second transport implementation.

See [AUDIT_EVIDENCE.md](AUDIT_EVIDENCE.md) for checks and provenance, [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for findings, and [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md) for Mermaid diagrams.

## File and page inventory

| Path | Actual purpose and boundary |
|---|---|
| app.py | Flask routes, Upstash referral aggregation, Meta send proxy and log-only webhook; no Firebase verification or database write path |
| index.html, index2.html | Nearly duplicate dashboard; Redis conversation/order reads, heuristic metrics, risk queue, JSON metric export; one differing line (541), not byte-identical |
| chats.html | Redis conversation scan/read/whole-array write; direct browser Meta sending; search, risk filters, new threads, cosmetic resolution |
| orders.html | Redis `orders:*` scan/read/status update; multi-encoded JSON parsing and fallback preview orders |
| analytics.html | Redis conversation/referral reads; client-side date metrics, intent/risk charts and clinic QR tally; Chart.js CDN |
| login.html, register.html | Firebase email/password and Google popup; exposed client PIN overlay; registration sets local display role to Admin |
| forgot-password.html, change-password.html | Both send Firebase password reset email; change-password is not an authenticated password-update API |
| reset-password.html | Firebase `confirmPasswordReset` using query-string action code; no local backend |
| profile.html | Browser-local profile and image upload; Firebase displayName/photoURL update; does not synchronize the edited email as a Firebase identity change |
| settings.html | Browser-local landing/refresh preferences; no scheduler or server preference persistence |
| chats copy.html | Older direct Redis/Meta client with unsafe HTML interpolation; no shared RudoAuth integration |
| analytics copy.html | Older Redis analytics client, Firebase SDK and external tracking scripts; references missing `js/script.min.js` |
| cake_orders.html | Separate commerce UI and Redis host; reads `order*`, `payment_data*`, `design_data*`, joins images by order number and writes `order:<id>` |
| js/rudo-auth.js | Firebase initialization and shared client auth/profile helpers; unsafe local-storage fallback |
| js/admin-shell.js | Navigation, account menus, delete-account modal, escaped shared display utilities; UI boundary only |
| js/risk-triage.js | Nine English regex categories, ranked conversation flags, deterministic phone-derived display IDs; no clinical backend or escalation delivery |
| js/core.js | Large bundled legacy vendor library; starts with jQuery 3.2.1, includes multiple plugins |
| js/process.js, js/layout-settings.js | Legacy loader animation and local layout preferences; used by analytics copy |
| Remaining JS | Vendor/legacy layout scripts; no direct script references from supplied HTML to the twelve files listed below |
| css/*, img/* | Local visual assets; CSS references can still depend on absent external font/assets |
| rudo-server.err.log, rudo-server.out.log | Historical log artifacts, 3,534 and 47 bytes; contents not inspected; not production verification |

No direct supplied-HTML script reference was found for `js/isotope.pkgd.min.js`, `js/google-maps.js`, `js/jquery.nice-select.min.js`, `js/topbar-virtual.js`, `js/wow.min.js`, `js/bootstrap.bundle.min.js`, `js/jquery-3.5.1.min.js`, `js/jquery.fancybox.min.js`, `js/script.js`, `js/minibar-virtual.js`, `js/jquery.waypoints.min.js`, or `js/jquery.animateNumber.min.js`. These are **candidates** for legacy cleanup, not approved deletions. google-maps.js defines a Google Maps initializer; no supplied page loads it. No first-party AI HTTP call is present locally.

Navigation in modern pages connects dashboard, chats, orders, analytics, profile and settings. Auth pages link to registration and password recovery. Flask `/` serves chats, while successful login defaults to index2.html; this difference matters for deployment smoke tests. All `*.html` files, including legacy copies and cake orders, are eligible for Flask serving.

## Flask route graph

| Route | Method | Source | Behavior / authorization |
|---|---|---|---|
| /api/qr-analytics | GET | app.py:274–294 | Scans `referrals*`, GET pipeline with per-key fallback, 45s default process-local cache; `refresh` bypasses cache; no auth |
| / | GET | app.py:298–300 | Serves chats.html without a server auth gate |
| /css/<path:filename> | GET | app.py:303–305 | Directory-confined CSS serving |
| /js/<path:filename> | GET | app.py:308–310 | Directory-confined JS serving |
| /img/<path:filename> | GET | app.py:313–315 | Directory-confined image serving |
| /<path:filename> | GET | app.py:318–322 | Serves any existing path ending `.html`; otherwise 404 |
| /webhook | GET, POST | app.py:326–377 | GET challenge verification; POST parses/logs first message per change and returns JSON; no signature gate or persistence |
| /sendWhatsApp | POST | app.py:381–412 | Sends caller-supplied recipient/text with server Meta credential; no auth, role or recipient check |

Flask may add HEAD/OPTIONS and its default `/static/<path:filename>` route; no local static directory is supplied. `send_from_directory` uses Flask/Werkzeug path confinement; no arbitrary file-read exploit was established. app.py:416 enables debug when run directly; actual WSGI settings remain unknown. No CORS middleware, application security headers, request budget or rate-limit implementation is present. Hosting-layer controls remain unverified.

## Integration and endpoint inventory

| Endpoint / configuration | Code evidence | Interpretation |
|---|---|---|
| oriented-gibbon-64178.upstash.io | app.py:69–70; chats.html:172–181; orders.html:119–122; index/index2:369–373; analytics.html:315–316; legacy copies | Primary Redis REST host, live-looking only; never contacted |
| prepared-leopard-18449.upstash.io | cake_orders.html:388–389 | Separate Redis host; ownership and healthcare scope unresolved; never contacted |
| graph.facebook.com | app.py:388; chats.html:591 | Meta messages API; Flask uses v19.0, modern chats v18.0 and a different phone-number ID; do not infer which sender is active |
| dawa-ca263.firebaseapp.com / Firebase project dawa-ca263 | js/rudo-auth.js:2–10 | Client Firebase project config; project ownership/providers/claims unknown |
| www.gstatic.com/firebasejs/9.6.0 | Modern auth/admin pages | Firebase compat SDK loaded from CDN |
| cdn.jsdelivr.net/npm/chart.js | analytics.html:12, analytics copy.html:32 | Unpinned remote executable dependency |
| cdnjs.cloudflare.com | Modern admin pages | Font Awesome CSS; external asset request |
| fonts.googleapis.com | Legacy/cake pages | External font stylesheet; may load further Google font resources |
| www.googletagmanager.com | analytics copy.html:30 | External tracking loader; actual collection and deployment unverified |
| 127.0.0.1:5000 | app.py comments / direct-run configuration | Local development only, not production hostname evidence |

Vendor source also contains documentation domains and optional social/media integrations. A URL in a vendor comment is not evidence of a Rudo integration. No local Vercel, Hugging Face, Supabase or AI endpoint configuration was found. Namecheap and original `public_html/chatbot/` provenance are owner-supplied context, not verified host state.

## Verified workflow traces (code behavior, not live success)

| Interaction | Frontend → service/storage → expected outcome | Failure behavior / missing implementation |
|---|---|---|
| Admin login | login.html:227–264 → Firebase signInWithEmailAndPassword / Google popup → markSignedIn → index2.html; RudoAuth:73–75 writes session marker | Form errors displayed; PIN is browser-only; no staff membership validation or backend token exchange |
| Registration | register.html:264–287 → Firebase creation / Google popup → local profile with role Admin | Provider availability unknown; local role is user-controlled display data, not a trusted claim |
| Open dashboard | index2.html:656–675 → direct SCAN conversation* and orders:* → GET values → heuristic totals and risk lists | Empty/error yields labeled preview data; auth check is asynchronous and data loading is not sequenced behind its result |
| Load conversation | chats.html:343–369,541–564 → direct Redis SCAN/GET → JSON array → render escaped content and regex risk labels | GET/parse failure becomes empty array and thread can silently disappear; scan failure displays error; no pagination or realtime subscription |
| Receive WhatsApp | Meta-like POST → app.py:339–375 → parse first message in each change, text/interactive/image ID handling → raw log → 200 | No persistent record, inference, referral/order creation, deduplication, status updates or automatic reply; malformed input returns 500 with exception string |
| Admin sends message | chats.html:577–617 → optimistic local bot message → direct Meta API → whole Redis thread SET → re-render | Does not use `/sendWhatsApp`; failed sends remain as optimistic messages plus a system failure entry; unchecked Redis response can claim persistence despite failure; concurrent updates can be lost |
| Alternate send API | Caller → POST /sendWhatsApp → Meta text send → response forwarded | No caller authorization, payload validation, timeout or persisted message; remote errors/body exposed |
| New chat | chats.html:620–647 → normalize number → `conversation:<phone>` SET with synthetic initial message | Local thread persists in UI if write fails; normalization assumes Zimbabwe prefix for certain inputs, despite Zambia context |
| Resolve chat | chats.html:672–676 → badge text/class change | Does not write resolution status; refresh loses action; other views infer closure from keywords in last message |
| Create order | No Rudo admin creation handler found | Existing records must come from an external writer; cake page is also mainly reader/status editor; writer ownership unknown |
| Update order | orders.html:302–320 → GET full object → status change → SET → local update | No transaction/version check; write HTTP result ignored; catch still updates local status; multi-encoded payload parser accepts arrays as objects |
| QR referrals | analytics.html:490–596 → direct `referrals*` SCAN/GET → source substring classification → chart | No frontend call to `/api/qr-analytics` found; UI excludes Poster 2, backend includes it and supports extra clinic fields; error and unmatched/empty states exist |
| Other analytics | analytics.html:682–840,975–1000 → full conversation arrays → keyword funnel, response-time approximation, per-message risk counts | General metrics filter thread by last timestamp but then aggregate full history; denominator remains all fetched threads; clinical chart filters messages separately; preview on error/empty |
| Risk event | RiskTriage.assessText / assessConversation → highest-rank regex match → badges/queue/chart | Computed only in browser, no saved triage event, human assignment, alert or acknowledgment; unmatched ≠ clinically safe |
| Profile save | profile.html:251–278 → localStorage → Firebase displayName/photoURL when signed in | Local write precedes remote sync; edited email is only profile data; custom profile/role persists on shared browser |
| Settings save | settings.html:179–218 → localStorage rudoAccountSettings | Preferences are not a server refresh scheduler or globally persisted setting |
| Password recovery | forgot/change-password → Firebase sendPasswordResetEmail; reset-password → confirmPasswordReset | Firebase errors mapped to UI; email delivery/action-link configuration unknown |
| Sign out | RudoAuth:125–134 → clear session marker and redirect key → Firebase signOut → login | Profile and preferences remain; redirect occurs even if signOut fails; no server session to revoke in current app |
| Delete account | admin-shell:228–241 → typed DELETE → RudoAuth:137–157 → Firebase user.delete / local cleanup | Requires recent login where Firebase enforces it; absent Firebase user clears local profile only and reports success; no patient-data deletion or Redis cleanup |

## Persistence reconstruction

| Record | Observed location / shape | Persistence and uncertainty |
|---|---|---|
| Admin identity | Firebase Auth user; UID/email/displayName/photoURL | External persistent identity store; approved-staff claims/list not supplied |
| Admin profile | localStorage userProfileData | Browser-local JSON, includes display role; not authoritative and not necessarily one record per Firebase UID |
| Session shortcut | localStorage rudoSessionActive; sessionStorage rudoRedirectAfterLogin | UI-only marker/redirect, unsafe as auth; do not migrate into trusted sessions |
| Preferences | localStorage rudoAccountSettings; legacy optionsObject | Device-local convenience; explicit opt-in needed for any server import |
| Conversation history | Primary Redis keys matching conversation*, intended `conversation:<phone>`; JSON arrays | role, message/text/content, timestamp, possible display IDs in text; no confirmed canonical user record, TTL or external writer schema |
| Orders | Primary Redis orders:* JSON objects, sometimes repeatedly encoded | Alternative fields mapped by UI; amounts may be formatted strings; status domain in orders.html:132–149; original ID may actually be user_id |
| Referrals/QR attribution | Primary Redis referrals* JSON with source and optional clinic fields | No local writer; record timestamp/uniqueness/first-vs-repeat attribution unknown; these are stored referrals, not verified unique QR scans |
| QR cache | In-process QR_CACHE + lock, app.py:87–89,201–269 | 45s default; per worker, disposable, not business data; cacheAgeSeconds actually reports remaining lifetime |
| Triage and chat status | Recomputed browser regex flags / in-memory cosmetic badge | No persisted triage or resolution entity found |
| Cake orders and images | Second Redis order*, payment_data*, design_data* | Distinct domain, base64 JPEG data joined by order_number; exclude unless owner expressly includes |
| Bot user profiles/state, handoffs, sessions | Not implemented in this local Flask source | May exist in an external bot deployment; obtain its source and state inventory before migration |

All Redis commands observed here are SCAN/GET/SET or GET pipeline; no TTL inspection or expiry-preserving write is implemented locally. This does not establish that stored keys never expire. A whole-key SET can remove a prior TTL unless explicitly retained. Code alone cannot supply row counts, backups, patient history completeness or reconciliation totals.

## Clinical boundary

RiskTriage:133–168 returns only the highest-rank category, retains first match on ties, includes messages with absent roles and excludes explicit non-user roles. It does not handle negation or non-English semantics. Category assignments are existing code behavior, not endorsed clinical priorities. Postpartum Emergencies are ranked HIGH-MODERATE (risk-triage.js:93–103), below other categories; this requires clinical-owner review before reliance. Its deterministic display IDs are pseudonyms, not anonymization or a collision-proof identity scheme. Preserve existing behavior in characterization tests first; have clinicians approve any subsequent change.

## Public reference comparison

Repository: [Samuel04-png/rudo_medgemma](https://github.com/Samuel04-png/rudo_medgemma/tree/af2545c92aea2cbcda5c6d717f67598b386a373d), inspected at commit `af2545c92aea2cbcda5c6d717f67598b386a373d`. This is a separate implementation, not verified production. Public source was kept outside this project; no code was copied into the application.

| Area | Local cPanel snapshot | Pinned newer source |
|---|---|---|
| Product surface | Staff dashboard, direct Redis/Meta clients | WhatsApp bot, product flow and agent handoff; no matching admin dashboard |
| Persistence | Redis thread arrays / loose JSON orders and referrals | db.py PostgREST calls to users, messages, referrals, orders and expiring kv |
| Hosting | Owner reports cPanel; no manifest | api/index.py imports main.app; vercel.json routes requests to it |
| AI | None found locally | MedGemma/translation clients and guardrails; actual model quality/deployment unverified |
| Identity | Firebase staff browser login | Phone-based bot state; no equivalent staff role integration found |
| Schema provenance | No SQL | README mentions supabase_schema.sql, absent from pinned recursive tree; grants, constraints and RLS cannot be verified |

Source concerns prevent a drop-in replacement: main.py:2024–2036 claims message IDs for one hour before processing, fails open on storage errors, and webhook failures are acknowledged as success (2123–2152). Signature validation and scheduler authorization were not found in these handlers. db.py masks several storage failures as empty state/results. main.py logs message payloads. A claim is not a durable completion record.

README-to-code differences also matter: medgemma_client.py:64–95 uses a Gradio call/event stream, rather than the documented plain `/answer` contract; translategemma_client.py:333–383 routes translation through TranslateGemma and/or Gemini with fallback/review, so Gemini may receive health content beyond language classification. API and privacy contracts need source-based verification. LICENSE.txt identifies AGPLv3; verify reuse rights/obligations with the project owner before copying. README points to a different organization for cloning; confirm canonical ownership and deployed commit.

**Recommendation:** migrate the existing dashboard through protected APIs and a measured persistence adapter; retain Firebase initially. Selectively adapt reviewed patterns from the newer bot after provenance, clinical review, schema and API compatibility are established. Consolidating/replacing bot inference is a separate scope and must not be coupled to the initial database move.

## Unresolved production questions

1. Which deployed callback receives WhatsApp events, which code writes Redis, and which Meta sender is authoritative?
2. Which pages, copies and Redis databases actually belong to Dawa Health's supported healthcare workflow?
3. What key types/counts/TTLs and backup consistency guarantees exist, including user state outside this archive?
4. Which Firebase users are approved staff, with which facility access and permissions? Are public sign-up and Google login enabled?
5. Does an existing Supabase project/schema already serve a bot, and must its table/API contracts be maintained?
6. What retention, residency, clinical review, recovery objectives and hosting-layer security controls have owners approved?
7. Who owns deployment, secrets, data approval, clinical sign-off and rollback? None can be inferred from source.
