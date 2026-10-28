# Bazaarpe backend verification

Verification date: 2026-10-28 (Asia/Kolkata)  
Local HTTP base URL: `http://127.0.0.1:8766`

This audit used isolated local identities for user A, user B, vendor, and admin. No real SMS, payment, bank transfer, push notification, or production data was used.

## Requirement checklist

| Requirement | Method and endpoint | Result | Evidence or fix |
|---|---|---|---|
| OTP send/login/register | `POST /api/user/send-otp/`, `/api/user/login-otp/`, `/api/user/register/` | Fixed and verified | Three HTTP registrations succeeded. Cooldown returned 429. Regression tests cover five-attempt lock, expiry, success, and reuse rejection. Local `otp_debug` is DEBUG-only; external SMS remains unverified. |
| Mobile-number change | `POST /api/user/change-phone/request/`, `/confirm/` | Fixed and test-verified | Normal profile edit rejects a different phone. New-number OTP confirmation updates the registered number. |
| Legal retrieval and consent | `GET /api/legal/documents/`; `GET/POST /api/user/consents/` | Fixed and HTTP-verified | Versions `PRIVACY:2026.1` and `TERMS:2026.1` were retrieved and persisted during registration. Order creation returns 428 when current consent is absent. |
| Logout | `POST /api/user/logout/` | Implemented and HTTP-verified | Token worked before logout; the same token returned 401 afterward. |
| Profile/onboarding | `GET/PATCH /api/user/profile/` | Fixed and verified | Full name remains mandatory, phone is immutable through ordinary editing, optional email is supported, onboarding state is persisted. Multipart profile image returned 200 and saved a media file. |
| Saved addresses | `POST /api/user/address/save/`; `GET /api/user/addresses/`; `GET/PUT/PATCH/DELETE /api/user/addresses/<id>/`; `POST .../set-default/` | Fixed and HTTP-verified | Address and GPS coordinates persisted in service zone 1. User B received 404 for user A's address. Six-digit pincode, coordinate range, default selection, and unsupported-zone validation are enforced. |
| Location/serviceability | `POST /api/user/location/detect/`; `GET /api/user/service-zones/` | Implemented; local zone logic verified | Configured zone matching is available. External OSM behavior was not relied on during lifecycle verification. GPS acquisition and permission prompts are frontend-only. |
| Home summary | `GET /api/user/home/` | Fixed and HTTP-verified | Returned current address, active/completed orders, and unread notification count. |
| Notifications | `GET /api/user/notifications/`; `POST .../<id>/read/`; `POST .../read-all/` | Fixed and HTTP-verified | Lifecycle generated 10 notification records; mark-as-read returned 200. Database notifications substitute for unconfigured external push delivery. |
| Categories and pricing | `GET /api/categories/`; `POST /api/pricing/calculate/` | Implemented and HTTP-verified | Active category/subtype retrieved; GST-inclusive price calculated server-side with decimal rounding and minimum-weight validation. |
| Order request | `POST /api/user/orders/create/` | Fixed and HTTP-verified | Positive weight, future date, allowed time slot, owned/serviceable address, and current consent are required. Order persisted as `NEGOTIATION_PENDING`. |
| Negotiation history | `GET /api/user/orders/<id>/negotiations/`; admin `POST /admin/orders/<id>/negotiate` | Fixed and HTTP-verified | Admin proposal persisted separately from final price. Proposal history count was 1. |
| Price acceptance/publication | `POST /api/user/orders/<id>/confirm-price/`; admin `POST /admin/orders/<id>/publish` | Fixed and HTTP-verified | User acceptance set the final amount but did not expose the order. Admin publication then moved it to `SEARCHING_VENDOR`. Premature publication regression test returns 409. |
| Vendor acceptance | `POST /api/vendor/orders/<id>/accept/` | Fixed and verified | Explicit active-vendor capability and assigned authenticated identity are required. Non-vendor acceptance returns 403 and duplicate vendor acceptance returns 409. |
| Tracking/location/status | `GET /api/orders/<id>/tracking/`; vendor `POST .../status/`, `/update-location/` | Fixed and HTTP-verified | User B cross-order tracking returned 403. Assigned vendor location persisted. Out-of-order transition returned 409. |
| Pickup OTP | `POST /api/vendor/orders/<id>/verify-otp/` | Fixed and HTTP-verified | Separate six-digit pickup OTP has expiry and five-attempt state. Wrong OTP returned 400, correct OTP returned 200, reuse returned 409. Only the assigned vendor is authorized. |
| Payment creation | `POST /api/vendor/orders/<id>/billing/` | Fixed and HTTP-verified | Client sent bogus amount/fee values; stored amount was server-calculated from 32.5 kg, GST and configured fee. Transaction remained `CREATED`. |
| Payment verification | `POST /api/vendor/orders/<id>/payment/verify/` | Fixed and HTTP-verified | Forged signature returned 400 and no invoice was accessible. Valid sandbox HMAC verified payment and generated invoice. Repeated verification was idempotent. |
| Payment webhook | `POST /api/payments/webhook/` | Fixed and HTTP-verified | Signed event processed once; identical replay returned `idempotent_replay=true`. Event-id reuse with altered payload is rejected. No external gateway sandbox was configured. |
| Invoice | `GET /api/user/orders/<id>/invoice/` | Fixed and HTTP-verified | Returned 404 before payment verification and 200 afterward. Invoice linked to the order with server-calculated subtotal, GST, fee and paid amount. |
| Pickup completion | `POST /api/vendor/orders/<id>/complete/` | Fixed and HTTP-verified | Real multipart PNG persisted under `media/pickup_proofs/`. Verified OTP/payment and matching positive final weight were required. Duplicate completion returned 409 and completion notification was created. |
| Order history | `GET /api/user/orders/history/?type=active|completed` | Implemented and HTTP-verified | Completed history contained the verified order after completion/payout. |
| Reviews | `GET/POST /api/user/orders/<id>/review/`; `GET /api/user/reviews/`; `GET /api/reviews/` | Fixed and HTTP-verified | Rating 5 persisted. Duplicate returned 409. Unapproved review was absent publicly; approved review appeared after admin moderation. |
| Bank details | `GET/POST/PUT /api/user/bank-details/` | Implemented and HTTP-verified | IFSC/account validation and owner scoping are enforced. Normal response returned only `XXXXXXXXXX8234`; the full number was not logged or reported. |
| User payout | admin `POST /admin/settlements/<order>/disburse` | Implemented and HTTP-verified | Requires paid vendor invoice, existing bank details and exact negotiated payout. Result persisted separately as `DISBURSED`; no automatic transfer was initiated. |
| Help/support | `GET /api/support/` | Fixed and HTTP-verified | Returned environment-configurable phone, email, WhatsApp and support hours. In-app chat is not implemented or required. |

## Final verified status sequence

`NEGOTIATION_PENDING` -> `ADMIN_NEGOTIATION` (admin proposal) -> `ADMIN_NEGOTIATION` (user accepted) -> `SEARCHING_VENDOR` (admin publication) -> `VENDOR_ASSIGNED` -> `VENDOR_ON_THE_WAY` -> `REACHED_LOCATION` -> `PICKUP_IN_PROGRESS` (pickup OTP verified) -> `INVOICE_GENERATED` (payment verified) -> `COMPLETED` -> `USER_REVIEW` -> `USER_PAYOUT`.

## Persisted HTTP evidence

- Order: `ORD-2026-228790`
- Final state: `USER_PAYOUT`
- Agreed user payout: INR 1,250.00
- Final weight: 32.5 kg
- Server item amount: INR 5,560.75
- Verified vendor payment including fee: INR 5,610.75
- Invoice: `INV-2026-161456`, `PAID`
- Multipart proof count: 1
- Negotiation proposals: 1
- Notifications: 10
- Review: approved
- Payout: `DISBURSED`
- Signed webhook events: 1

## External blockers and frontend-only items

- SMS: controlled local OTP substitute verified; no SMS provider credentials were configured.
- Payment gateway: local HMAC sandbox behavior verified; no Razorpay/Stripe/etc. sandbox account was configured, so no claim is made about a real provider.
- Maps: configured local service-zone logic verified; external OSM availability was not treated as proof.
- Push: notification database side effects verified; no external push provider configured.
- Bank transfer: admin recording/tracking only; no automatic bank transfer was added.
- Splash screens, GPS acquisition, device permission prompts and navigation are frontend-only.
