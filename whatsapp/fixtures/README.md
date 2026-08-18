# Sanitized Fixtures

All phone numbers, wa_ids, phone_number_ids, and message ids in this directory are fabricated test
values (`1555...`, `wamid.FIXTURE_...`) and do not correspond to any real WhatsApp account. No real
access tokens or app secrets appear anywhere in this directory or in the test suite — signatures are
computed at test time against a fixture app secret (`tests/conftest_helpers.py`), never hardcoded.

Do not add real customer payloads here, sanitized or not — synthesize new fixtures by hand instead of
copying live traffic.
