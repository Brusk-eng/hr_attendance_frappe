# Copyright (c) 2026, Marwan and contributors
# For license information, please see license.txt

"""Extend Attendance Connections (v16.60-safe)."""

from __future__ import annotations


def get_dashboard_data(data):
	"""Keep Employee Checkin; expose internal links already on Attendance.

	Does not touch Employee Connections (HRMS + HSE already cover Attendance).
	"""
	transactions = data.setdefault("transactions", [])
	internal = data.setdefault("internal_links", {})

	# Ensure Checkin group exists (HRMS baseline).
	has_checkin = False
	for group in transactions:
		items = group.setdefault("items", [])
		if "Employee Checkin" in items:
			has_checkin = True
			break
	if not has_checkin:
		transactions.append({"label": "", "items": ["Employee Checkin"]})

	# Values live on the Attendance doc itself.
	internal.setdefault("Attendance Request", "attendance_request")
	internal.setdefault("Leave Application", "leave_application")
	internal.setdefault("Employee", "employee")
	internal.setdefault("Shift Type", "shift")

	return data
