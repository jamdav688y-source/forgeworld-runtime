# Platform Policy Evidence Record

Verified: 2026-08-18, against live Meta/WhatsApp developer documentation fetched during this session.
**Re-verify before go-live** — Meta changes these rules without notice; this record is a snapshot, not
a permanent assumption, and code must read behavior from configuration/response payloads, not hardcode
policy dates.

## Webhook verification handshake

Source: `developers.facebook.com/docs/graph-api/webhooks/getting-started`

- Meta sends `GET` with `hub.mode=subscribe`, `hub.challenge=<int>`, `hub.verify_token=<string>`.
- The endpoint must check `hub.verify_token` against the configured secret and echo `hub.challenge`
  back verbatim in the response body (as plain text/int, not JSON) with HTTP 200.
- Any mismatch must return a non-200 (implemented as 403).

## Inbound POST authenticity

- Header: `X-Hub-Signature-256: sha256=<hex>`.
- Verification: HMAC-SHA256 over the raw request body, keyed with the app secret; compare the computed
  hex digest to the header value using constant-time comparison.
- Meta's own docs say validation is optional but recommended — this system treats it as **mandatory**;
  an unverified or missing signature is `BLOCKED_BY_POLICY`, never processed as a real event.

## Delivery/response contract

- Respond `200 OK` to every accepted event notification.
- Meta retries failed deliveries with decreasing frequency for up to 36 hours (per the current webhooks
  guide) or up to 7 days (per the Cloud API webhooks guide) — the two docs disagree on the exact retry
  window, so the adapter must be idempotent regardless of retry duration rather than relying on either
  number.
- Notifications may batch up to 1000 updates per payload and may arrive out of order — the adapter must
  not assume ordering and must dedupe on `platform_message_id`.
- Payloads can be up to 3 MB.

## Customer service window (CSW) / template rules

Source: `developers.facebook.com/docs/whatsapp/pricing`

- An inbound user message opens a 24-hour customer service window; free-form (non-template) replies are
  only permitted inside that window.
- Outside the CSW, only approved **message templates** (marketing / utility / authentication
  categories) may be sent.
- Click-to-WhatsApp ads and Facebook Page CTA entry points open a 72-hour free-form window instead of
  24 hours.
- Consequence for this build: the outbound adapter must check `now - last_inbound_at` against the
  applicable window before allowing a free-form send, and require a template reference otherwise; this
  is enforced in `whatsapp/src/outbound.py`.

## Data use restriction

Source: `whatsappbusiness.com/policy/`

- "Don't use any data obtained from us about a person you message within WhatsApp, other than the
  content of message threads, for any purpose other than as reasonably necessary to support messaging
  with that person." — this directly prohibits using WhatsApp conversation data to train or improve
  general AI models, matching the mission's Section 4 restriction. No component in this build sends
  conversation content to any model-training pipeline; classification and drafting are per-request only
  and outputs are not persisted for training.
- Opt-in is required before contact: "You may only contact people on WhatsApp if... you have received
  opt-in permission from the recipient." Enforced via `consent_state` gating in `whatsapp/src/authority.py`.
- Opt-out/stop requests must be honored.

## Gaps not resolved by this record

- Exact current API version string, endpoint paths, and full webhook JSON schema per message type were
  not exhaustively fetched (only a partial sample was available in the fetched pages). The adapter's
  `normalize.py` handles the fields documented here and degrades unknown/unhandled message types to
  `message_type: "unknown"` rather than guessing structure.
- This record does not substitute for Meta Business verification, WhatsApp Business Platform
  onboarding, or legal/privacy counsel review, all of which remain the user's responsibility before any
  live traffic.
