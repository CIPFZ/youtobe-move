import unittest
from datetime import datetime

from app.cron_schedule import next_cron_time, parse_cron, seconds_until_next_cron


class CronScheduleTests(unittest.TestCase):
    def test_parse_cron_supports_steps_ranges_and_lists(self):
        fields = parse_cron("*/15 9-10 1,15 * 0-4")

        self.assertEqual(fields[0], {0, 15, 30, 45})
        self.assertEqual(fields[1], {9, 10})
        self.assertEqual(fields[2], {1, 15})
        self.assertIn(12, fields[3])
        self.assertEqual(fields[4], {0, 1, 2, 3, 4})

    def test_next_cron_time_returns_next_matching_minute(self):
        result = next_cron_time("*/10 * * * *", datetime(2026, 6, 20, 12, 1, 30))

        self.assertEqual(result, datetime(2026, 6, 20, 12, 10))

    def test_seconds_until_next_cron(self):
        result = seconds_until_next_cron("*/5 * * * *", datetime(2026, 6, 20, 12, 3, 0))

        self.assertEqual(result, 120)

    def test_invalid_cron_rejected(self):
        with self.assertRaises(ValueError):
            parse_cron("60 * * * *")
        with self.assertRaises(ValueError):
            parse_cron("* * *")


if __name__ == "__main__":
    unittest.main()
