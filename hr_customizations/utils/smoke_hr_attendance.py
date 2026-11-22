# Copyright (c) 2026, Marwan and contributors
# For license information, please see license.txt

"""Live smoke for hr_customizations C package.

bench --site frappe16 execute hr_customizations.utils.smoke_hr_attendance.run
"""

from __future__ import annotations

import frappe


def _ok(msg: str, report: dict):
	report["checks"].append({"ok": True, "msg": msg})
	print(f"OK  {msg}")


def _fail(msg: str, report: dict):
	report["ok"] = False
	report["checks"].append({"ok": False, "msg": msg})
	print(f"FAIL  {msg}")


def run() -> dict:
	report = {"ok": True, "checks": []}
	frappe.set_user("Administrator")

	if not frappe.db.exists("Page", "emppage"):
		_fail("Page emppage missing", report)
	else:
		_ok("Page emppage exists", report)

	# Connections override
	ov = frappe.get_hooks("override_doctype_dashboards") or {}
	hooks = ov.get("Attendance") or []
	if any("attendance_dashboard" in h for h in hooks):
		_ok("Attendance override_doctype_dashboards hooked", report)
	else:
		_fail("Attendance dashboard override not hooked", report)

	data = frappe.get_meta("Attendance").get_dashboard_data()
	internal = data.get("internal_links") or {}
	for key in ("Attendance Request", "Leave Application", "Employee", "Shift Type"):
		if key in internal:
			_ok(f"internal_links has {key}", report)
		else:
			_fail(f"internal_links missing {key}", report)
	items = [i for g in (data.get("transactions") or []) for i in (g.get("items") or [])]
	if "Employee Checkin" in items:
		_ok("Employee Checkin in Connections", report)
	else:
		_fail("Employee Checkin missing from Connections", report)

	# Desktop Icon intentionally not used (sidebar + search only)
	if frappe.db.exists("Desktop Icon", "Attendance Page"):
		_fail("Desktop Icon Attendance Page should be removed", report)
	else:
		_ok("Desktop Icon Attendance Page absent", report)

	# Sidebar
	if frappe.db.exists("Sidebar", "Shift & Attendance"):
		doc = frappe.get_doc("Sidebar", "Shift & Attendance")
		if any(r.link_to == "emppage" for r in doc.items):
			_ok("Sidebar Shift & Attendance has emppage", report)
		else:
			_fail("Sidebar missing emppage link", report)

	# API company + page_length
	from hr_customizations.api import get_monthly_attendance, get_unmarked_employees

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	msg = get_monthly_attendance(
		frappe.utils.now_datetime().year,
		frappe.utils.now_datetime().month,
		company=company,
		page_length=25,
		start=0,
	)
	if msg.get("page_length") == 25:
		_ok("get_monthly_attendance page_length=25", report)
	else:
		_fail(f"page_length expected 25 got {msg.get('page_length')}", report)
	if company and msg.get("company") == company:
		_ok(f"company filter applied ({company})", report)
	elif not company:
		_ok("no default company — skip company assert", report)
	else:
		_fail("company not echoed in response", report)

	unmarked = get_unmarked_employees(frappe.utils.today(), company=company)
	if "count" in unmarked and "employees" in unmarked:
		_ok(f"get_unmarked_employees count={unmarked['count']}", report)
	else:
		_fail("get_unmarked_employees shape bad", report)

	# Insights soft
	if frappe.db.exists("DocType", "Insights Workbook"):
		if frappe.db.exists("Insights Workbook", "attendance_analytics"):
			_ok("Insights workbook attendance_analytics", report)
		else:
			_fail("Insights workbook attendance_analytics missing", report)
		if frappe.get_meta("Dashboard").has_field("insights_dashboard"):
			wired = frappe.db.get_value("Dashboard", "Attendance", "insights_dashboard")
			if wired:
				_ok(f"classic Attendance.insights_dashboard={wired}", report)
			else:
				_fail("classic Attendance insights_dashboard empty", report)
	else:
		_ok("Insights not installed — soft skip", report)

	# Employee still has Attendance in Connections (verify-only)
	emp = frappe.get_meta("Employee").get_dashboard_data()
	emp_items = [i for g in (emp.get("transactions") or []) for i in (g.get("items") or [])]
	if "Attendance" in emp_items:
		_ok("Employee Connections still include Attendance", report)
	else:
		_fail("Employee Connections lost Attendance", report)

	print("ALL_HR_ATTENDANCE_CHECKS_PASSED" if report["ok"] else "HR_ATTENDANCE_CHECKS_FAILED")
	return report
