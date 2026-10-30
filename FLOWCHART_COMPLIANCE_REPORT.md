# Bosidametal Flowchart Compliance Report

Audit date: 30 October 2026

Source of truth:

- `C:\Users\PC\Downloads\flowchart_bosidametal.pdf`
- `C:\Users\PC\Downloads\Bosidametal_App_Requirements.pdf`

## Result

The backend implements all four application swimlanes, all seven decision branches, and all fourteen backend service responsibilities represented by the official flowchart. The automated suite contains 33 passing tests. The local SQLite database was migrated through `0011_pickuporder_proof_submitted_at_and_more` and was also exercised with persisted API records.

External production providers remain configuration boundaries: real SMS delivery, Aadhaar verification, push delivery, route navigation, payment capture/refund, and bank payout require provider credentials. The application does not falsely report those external actions as complete when a provider is unconfigured. Local OTP, map-zone matching, signed sandbox payment/webhook, notification persistence, structured invoice, and recorded payout implementations support deterministic development verification.

## Four swimlanes

| Swimlane | Implemented backend path | Evidence |
|---|---|---|
| User | OTP, consent, profile, addresses/location, categories/pricing, order, two-way negotiation, tracking, invoice, history, review, bank details, support, logout | `/api/user/...`, `API_User.txt`, `PickupOrderFlowTests` |
| Admin | Full-admin login, users/vendors/KYC, cities/zones/categories, negotiation/publication, timeout/manual assignment, order monitoring, payments/invoices, commission/ledgers, payouts, moderation, CMS/settings/reports | `/admin/...`, protected dashboard pages, `FullAdminAccessTests` |
| Vendor | OTP/consent/profile, category/subcategory and zone selection, KYC, availability, matching, accept/reject, status/location, weight/proof, pickup OTP, payment retry/success, invoice/history/ratings/refunds/support/logout | `/api/vendor/...`, `API_Vendor.txt`, `PickupOrderFlowTests` |
| Backend services | Persistent models, signed operations, matching, timers, audit logs, notifications, invoice/ledger calculations and moderation | Migration `0011`, management command, API/admin tests |

## Seven decision branches

| Decision | Yes branch | No branch |
|---|---|---|
| Login OTP valid? | Verified OTP creates/returns authentication token | Wrong, expired, reused, cooldown and attempt-limit responses are rejected |
| User accepts admin price? | `confirm-price` records acceptance and permits publication | `counter-price` persists a user proposal and returns order to admin negotiation |
| Admin approves vendor KYC? | Vendor becomes approved and may go online | Reject/suspend keeps marketplace access blocked with reason |
| Vendor accepts available order? | Atomic first acceptance assigns vendor and starts arrival deadline | Reject is vendor-specific; timeout is escalated and admin can manually assign |
| Pickup OTP valid? | One-time verification advances pickup | Wrong, expired, reused and attempt-limit cases are rejected |
| Vendor payment succeeds? | Signed verification generates paid invoice | Signed failed webhook records failure, notifies vendor and permits a new payment attempt |
| Marketplace finds vendor before timeout? | Zone, online status, KYC, category and subcategory match expose the order | Expired unaccepted order is escalated once; admin manual assignment is available |

## Fourteen backend services

| # | Service | Implementation |
|---:|---|---|
| 1 | OTP | `OTPVerification`, cooldown, expiry, attempt limit, one-time use |
| 2 | User/vendor/KYC database | `UserProfile`, `VendorProfile`, documents and full authenticated/admin KYC fields |
| 3 | Maps/zones | cities, zones, pincodes, center/radius, GPS coordinates, distance calculation |
| 4 | Order state machine | explicit `PickupOrder.Status` transitions and ownership checks |
| 5 | Pricing/negotiation/GST | subcategory rate/GST calculator and two-way proposal history |
| 6 | Vendor matching | online, approved KYC, consent, zone, category, subcategory and prior-rejection filters |
| 7 | Timer/fallback | persisted acceptance/arrival settings, deadlines, idempotent escalation and manual assignment |
| 8 | Pickup OTP | assigned-vendor-only verification after staged proof/weight |
| 9 | Payment | server-calculated totals, configurable commission, HMAC verification, idempotent webhook and retry |
| 10 | Invoice | one structured paid tax invoice per verified order |
| 11 | Commission/ledgers | immutable payment snapshots and dynamic user/vendor ledger views |
| 12 | Payout | bank details, admin-recorded disbursement, method/reference/status |
| 13 | Notifications/audit | `UserNotification` plus immutable `MarketplaceAuditLog` decision events |
| 14 | Reviews | completed-order-only review, one review per order, admin moderation and public approved list |

## Security and integrity checks

- Admin mutations and pages require an authenticated staff or superuser account.
- User, vendor, order, notification, bank and refund records are owner-scoped.
- Vendor order acceptance is atomic and rejects stale/racing acceptance attempts.
- Final weight and proof are persisted before OTP and reused by server-side billing.
- Billing fails closed without an approved commission policy.
- Payment signatures and webhook signatures are verified; webhook event IDs are idempotent.
- Full bank and KYC values are returned only on authenticated owner/admin surfaces, per the explicit unmasked-data requirement.
- Dashboard financial totals honor `from` and `to` dates and configuration cards use persisted values.
- FAQ, static pages, privacy and terms are stored as distinct content types.

## Verification commands

```text
.\env\Scripts\python.exe manage.py check
.\env\Scripts\python.exe manage.py makemigrations --check --dry-run
.\env\Scripts\python.exe manage.py migrate
.\env\Scripts\python.exe manage.py test --verbosity 1
```

