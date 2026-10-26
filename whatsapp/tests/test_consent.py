from whatsapp.src import consent
from whatsapp.tests.base import WhatsAppTestCase


class TestConsent(WhatsAppTestCase):
    def test_default_consent_for_unknown_contact(self):
        state = consent.get_consent("nonexistent-contact")
        self.assertEqual(state["consent_state"], "unknown")
        self.assertFalse(state["can_recontact"])

    def test_stopword_detection_case_insensitive(self):
        self.assertTrue(consent.is_stop_word("stop"))
        self.assertTrue(consent.is_stop_word("STOP"))
        self.assertTrue(consent.is_stop_word("  Unsubscribe  "))
        self.assertFalse(consent.is_stop_word("please stop calling me at odd hours"))

    def test_stopword_revokes_consent(self):
        record = consent.apply_stop_word_if_present("contact-1", "STOP")
        self.assertIsNotNone(record)
        self.assertEqual(record["consent_state"], "revoked")
        current = consent.get_consent("contact-1")
        self.assertEqual(current["consent_state"], "revoked")
        self.assertFalse(current["can_recontact"])
        self.assertFalse(current["can_respond"])

    def test_non_stopword_does_not_revoke(self):
        result = consent.apply_stop_word_if_present("contact-2", "how much does this cost?")
        self.assertIsNone(result)
        current = consent.get_consent("contact-2")
        self.assertEqual(current["consent_state"], "unknown")

    def test_revoked_consent_is_append_only_history(self):
        consent.record_consent("contact-3", "verified", source="manual_opt_in")
        consent.record_consent("contact-3", "revoked", source="stopword_auto_detect")
        history = consent.get_consent("contact-3")
        self.assertEqual(history["consent_state"], "revoked")
