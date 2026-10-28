# Bosidametal vendor backend verification

Verification date: 2026-10-28 (Asia/Kolkata)  
Local HTTP base URL: `http://127.0.0.1:8767`

The vendor app uses the existing `PickupOrder`, user address, category, review,
notification, payment and invoice records. No disconnected vendor order store was
introduced. The verification used isolated local identities and controlled local
provider substitutes; it did not send SMS, call a production Aadhaar service,
charge a payment account, issue a real refund, push a notification, or transfer
money to a user.

## Implemented and reused surfaces

- Shared OTP registration/login/logout, phone-change verification and versioned
  legal consent are reused through vendor aliases.
- Vendor business profiles support real multipart images, immutable verified phone,
  shared service zones and persisted online/offline status.
- Aadhaar initiation/confirmation has an explicit provider boundary; KYC supports
  multipart documents, masked normal responses and admin approval/rejection.
- Marketplace list/detail use one eligibility rule: active account, accepted current
  terms, approved KYC, online status, matching zone, completed negotiation, admin
  publication, unexpired deadline and no prior rejection by that vendor.
- Assignment is a database compare-and-set operation. Rejection is scoped to one
  vendor. Publication and arrival deadlines persist, and the idempotent
  `escalate_unaccepted_orders` command flags missed acceptance deadlines.
- Status, location, pickup OTP, billing, signed payment/webhook, invoice, proof,
  completion, reviews, notifications, history, support and refunds all operate on
  the shared user order.
- Billing snapshots the approved configurable commission/tax/fee policy. Billing is
  blocked with HTTP 503 when no approved policy exists; no 2 percent rate is assumed.

## Actual HTTP lifecycle result

The run created user A, user B, vendor A, vendor B, an unapproved vendor and an
authenticated superuser session. Both approved vendors completed local Aadhaar and
multipart KYC submission, then received admin approval through HTTP. User A saved a
shared service-zone address, created a pickup, accepted an admin price proposal and
had the order published.

Persisted evidence:

- Shared order: `ORD-2026-398896`
- Concurrent acceptance: vendor A HTTP 200; vendor B HTTP 409
- Cross-user tracking: HTTP 404
- Losing vendor assigned-detail access: HTTP 403
- Unapproved vendor online attempt: HTTP 403
- User saw `VENDOR_ASSIGNED`, `VENDOR_ON_THE_WAY` and `REACHED_LOCATION` after the
  corresponding vendor actions.
- Wrong pickup OTP: HTTP 400; correct OTP: HTTP 200; reuse: HTTP 409
- Vendor order/list/accept responses contained no pickup OTP. The unassigned listing
  contained no customer identity or full pickup address.
- Forged payment signature: HTTP 400; controlled valid signature: HTTP 200; repeated
  verification: HTTP 200 without a second invoice.
- Payment: `pay_sbx_7a75cb9400b12226fc849d60`, INR 6,953.00
- Audit-only policy used during the run: 0 percent commission, 0 percent commission
  tax and INR 50 fixed fee. It was explicitly labelled as an audit policy and
  deactivated after verification, so billing now fails closed until an approved
  business policy is configured.
- Invoice: `INV-2026-505962`, one invoice for the shared order
- Multipart proof completion: HTTP 200; duplicate completion: HTTP 409
- Unapproved review comment was blank for the vendor; the comment appeared after
  admin moderation.
- Refund request: HTTP 201; duplicate: HTTP 409; admin-approved controlled local
  processing reached `SUCCEEDED`.
- Final shared order status after review: `USER_REVIEW`

## Automated verification

`python manage.py test nainjyoti` passes 28 tests. Added coverage verifies marketplace
data minimization, no pickup-OTP disclosure, vendor-only rejection, offline/KYC/zone
enforcement, approved billing-policy requirement, refund limits/uniqueness, provider
fail-closed behavior and idempotent escalation. Existing admin, User API, OTP,
payment, review, bank-masking and payout tests remain green.

`python manage.py check` reports no issues. `python manage.py makemigrations --check
--dry-run` reports no changes. Migrations `0008_vendorbillingsetting_and_more` and
`0009_paymenttransaction_one_created_payment_per_order_and_more` were applied to
the local database. The second adds database-level pending/verified-payment
uniqueness and billing-policy range constraints.

## Security and transition rules

`SEARCHING_VENDOR -> VENDOR_ASSIGNED` is vendor acceptance after all eligibility
checks. Only the assigned vendor may continue:

`VENDOR_ASSIGNED -> VENDOR_ON_THE_WAY -> REACHED_LOCATION -> PICKUP_IN_PROGRESS`

The last transition occurs only through the user-provided, expiring, attempt-limited,
single-use pickup OTP. Billing requires that state and a positive final weight.
Payment verification produces `INVOICE_GENERATED`; completion requires the verified
payment/invoice, matching final weight and proof image, then produces `COMPLETED`.
User review advances to `USER_REVIEW`; the separately controlled platform-to-user
payout may later advance to `USER_PAYOUT`.

Sensitive KYC values/files are excluded from ordinary API responses. User bank
details remain masked by the established shared API. Admin operations require an
active staff superuser. Vendor contact data is disclosed only after assignment.

## Honest external and business blockers

- SMS delivery remains an external integration; DEBUG OTP was the isolated substitute.
- Aadhaar production provider credentials/protocol are not configured. The code
  fails closed outside explicit `local-test` mode.
- Payment and refunds used local signed sandbox boundaries; no gateway sandbox
  account was exercised.
- Maps use configured coordinates and Haversine distance; no live routing provider
  was exercised.
- Push notification rows were verified in the database; no external push provider
  was configured.
- Production commission percentage, commission tax, fixed fee and basis still need
  business approval. The code is configurable and blocks when approval is absent.
- The final-weight implementation recalculates item amount and GST from the category
  rate. Whether the negotiated price should instead cap/replace that calculation is
  still a business decision.
- The refund window starting event, eligibility conditions and commission/tax
  treatment are unresolved. Refunds therefore require explicit admin approval.
- Missed acceptance escalates to admin-assisted dispatch. No undefined admin
  purchase/payment behavior was invented.
