import unittest
from unittest.mock import patch

from notifier import _notification_request, console, format_terminal_award_deals, send_alert


class NotificationRequestTests(unittest.TestCase):
    def test_formats_a_slack_incoming_webhook(self):
        endpoint, payload = _notification_request("https://hooks.slack.com/services/example", "Hello")
        self.assertEqual(endpoint, "https://hooks.slack.com/services/example")
        self.assertEqual(payload, {"text": "Hello"})

    def test_formats_a_telegram_bot_message(self):
        endpoint, payload = _notification_request(
            "https://api.telegram.org/botTOKEN/sendMessage?chat_id=12345", "Hello"
        )
        self.assertEqual(endpoint, "https://api.telegram.org/botTOKEN/sendMessage")
        self.assertEqual(payload["chat_id"], "12345")
        self.assertEqual(payload["text"], "Hello")

    def test_requires_a_telegram_chat_id(self):
        with self.assertRaisesRegex(ValueError, "chat_id"):
            _notification_request("https://api.telegram.org/botTOKEN/sendMessage", "Hello")

    @patch("notifier._post_message")
    def test_includes_package_flights_in_webhook_messages(self, post_message):
        send_alert(
            "https://discord.com/api/webhooks/example",
            "Flight + stay packages",
            [{
                "flight": {
                    "origin": "SFO", "destination": "CUN", "price": 470,
                    "airline": "United", "departure_date": "2026-11-13", "return_date": "2026-11-20",
                },
                "stays": [{"name": "Beach house", "nightly_rate": 200}],
            }],
        )
        self.assertIn("SFO ➔ CUN", post_message.call_args.args[1])
        self.assertIn("Beach house", post_message.call_args.args[1])

    def test_terminal_award_output_labels_reported_unverified_leads(self):
        with console.capture() as capture:
            format_terminal_award_deals([{
                "title": "SFO to Cancun from 20,000 points",
                "source": "Fixture Awards",
                "source_url": "https://publisher.example/cancun",
                "matched_regions": ["cancun"],
                "travel_months": ["2026-11"],
                "points": 20000,
                "confidence_score": 90,
            }])

        rendered = capture.get()
        self.assertIn("Reported Award Leads", rendered)
        self.assertIn("Verify live availability", rendered)
        self.assertIn("20,000", rendered)

    @patch("notifier._post_message")
    def test_webhook_award_output_labels_reported_unverified_leads(self, post_message):
        send_alert(
            "https://discord.com/api/webhooks/example",
            "Reported Award Leads",
            [{
                "title": "SFO to Cancun from 20,000 points",
                "source": "Fixture Awards",
                "source_url": "https://publisher.example/cancun",
                "availability_status": "reported",
                "verification_required": True,
            }],
        )

        message = post_message.call_args.args[1]
        self.assertIn("Reported award lead", message)
        self.assertIn("verify live availability", message)


if __name__ == "__main__":
    unittest.main()
