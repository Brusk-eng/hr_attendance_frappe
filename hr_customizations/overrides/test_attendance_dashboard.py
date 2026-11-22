# Copyright (c) 2026, Marwan and contributors
# For license information, please see license.txt

import unittest

from hr_customizations.overrides.attendance_dashboard import get_dashboard_data


class TestAttendanceDashboard(unittest.TestCase):
	def test_keeps_checkin_and_adds_internal_links(self):
		data = get_dashboard_data(
			{
				"fieldname": "attendance",
				"transactions": [{"label": "", "items": ["Employee Checkin"]}],
				"internal_links": {},
			}
		)
		items = [i for g in data["transactions"] for i in g.get("items") or []]
		self.assertIn("Employee Checkin", items)
		self.assertEqual(data["internal_links"]["Attendance Request"], "attendance_request")
		self.assertEqual(data["internal_links"]["Leave Application"], "leave_application")
		self.assertEqual(data["internal_links"]["Employee"], "employee")
		self.assertEqual(data["internal_links"]["Shift Type"], "shift")

	def test_creates_checkin_when_absent(self):
		data = get_dashboard_data({"transactions": [], "internal_links": {}})
		items = [i for g in data["transactions"] for i in g.get("items") or []]
		self.assertEqual(items, ["Employee Checkin"])


if __name__ == "__main__":
	unittest.main()
