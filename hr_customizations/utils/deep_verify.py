# Copyright (c) 2026, Marwan and contributors
# For license information, please see license.txt

"""Deep live verification for hr_customizations C package.

bench --site frappe16 execute hr_customizations.utils.deep_verify.run
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, now_datetime, today


def run() -> dict:
	frappe.set_user("Administrator")
	errors: list[str] = []
	oks: list[str] = []

	def _ok(msg: str):
		oks.append(msg)
		print(f"OK  {msg}")

	def _fail(msg: str):
		errors.append(msg)
		print(f"FAIL  {msg}")

	from hr_customizations.api import (
		get_attendance_summary,
		get_monthly_attendance,
		get_unmarked_employees,
		mark_bulk_attendance,
		mark_selected_attendance,
	)

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	yr = now_datetime().year
	mo = now_datetime().month

	# Desktop page size
	desk = get_monthly_attendance(yr, mo, company=company, page_length=100, start=0)
	if len(desk["employees"]) not in (100,) and desk["total"] >= 100:
		_fail(f"desktop page n={len(desk['employees'])}")
	else:
		_ok(f"desktop page n={len(desk['employees'])} has_more={desk.get('has_more')}")

	# Phone pages disjoint
	p1 = get_monthly_attendance(yr, mo, company=company, page_length=25, start=0)
	p2 = get_monthly_attendance(yr, mo, company=company, page_length=25, start=25)
	overlap = {e.name for e in p1["employees"]} & {e.name for e in p2["employees"]}
	if overlap:
		_fail(f"page overlap {len(overlap)}")
	else:
		_ok("phone pages disjoint")
	if p1["total"] > 25:
		if not p1.get("has_more"):
			_fail("has_more false when total>25")
		else:
			_ok("has_more true when total>25")
	else:
		_ok(f"has_more={p1.get('has_more')} (total={p1['total']} ≤25)")

	# Bulk mark 2 + cleanup
	um = get_unmarked_employees(today(), company=company)
	targets = (um.get("employees") or [])[:2]
	if len(targets) < 2:
		_fail(f"need 2 unmarked got {len(targets)}")
	else:
		result = mark_bulk_attendance(targets, today(), "Absent", submit=1)
		if result.get("marked") != 2:
			_fail(f"bulk marked={result}")
		else:
			_ok(f"bulk marked 2 skipped={result.get('skipped')}")
		for emp in targets:
			name = frappe.db.get_value(
				"Attendance",
				{"employee": emp, "attendance_date": today(), "docstatus": 1},
				"name",
			)
			if name:
				frappe.get_doc("Attendance", name).cancel()
		_ok("bulk cleanup cancelled")

	# Selected cells
	emp = p1["employees"][0].name
	test_date = None
	for off in range(0, 20):
		dte = add_days(today(), -off)
		if getdate(dte).month != mo:
			continue
		if not frappe.db.exists(
			"Attendance",
			{"employee": emp, "attendance_date": dte, "docstatus": ["<", 2]},
		):
			test_date = dte
			break
	if test_date:
		result = mark_selected_attendance(
			[{"employee": emp, "attendance_date": str(test_date)}], "Absent", submit=1
		)
		if result.get("marked") != 1:
			_fail(f"selected {result}")
		else:
			_ok(f"selected mark {emp}@{test_date}")
		name = frappe.db.get_value(
			"Attendance",
			{"employee": emp, "attendance_date": test_date, "docstatus": 1},
			"name",
		)
		if name:
			frappe.get_doc("Attendance", name).cancel()
			_ok("selected cleanup")
	else:
		_ok("selected skip (no free day)")

	# Summary + company
	summary = get_attendance_summary(f"{yr}-{mo:02d}-01", today(), company=company)
	if "totals" not in summary:
		_fail("summary missing totals")
	else:
		_ok(f"summary period_days={summary.get('period_days')}")

	# Insights SQL
	for title in ("Status Counts", "Company Counts", "Attendance Detail"):
		qname = frappe.db.get_value(
			"Insights Query v3",
			{"workbook": "attendance_analytics", "title": title},
			"name",
		)
		if not qname:
			_fail(f"missing query {title}")
			continue
		ops = frappe.parse_json(frappe.db.get_value("Insights Query v3", qname, "operations") or "[]")
		sql = next((op.get("raw_sql") for op in ops if op.get("type") == "sql"), "")
		try:
			frappe.db.sql(sql + "\nLIMIT 2")
			_ok(f"insights sql {title}")
		except Exception as e:
			_fail(f"insights sql {title}: {e}")

	wired = frappe.db.get_value("Dashboard", "Attendance", "insights_dashboard")
	if wired:
		_ok(f"classic wired {wired}")
	else:
		_fail("classic insights_dashboard empty")

	# Connections
	data = frappe.get_meta("Attendance").get_dashboard_data()
	items = [i for g in (data.get("transactions") or []) for i in (g.get("items") or [])]
	if "Employee Checkin" not in items:
		_fail("Checkin missing")
	else:
		_ok("connections Checkin")
	internal = data.get("internal_links") or {}
	for key in ("Attendance Request", "Leave Application", "Employee", "Shift Type"):
		if key not in internal:
			_fail(f"internal missing {key}")
		else:
			_ok(f"internal {key}")

	# Desktop Icon
	icon = frappe.get_doc("Desktop Icon", "Attendance Page")
	if icon.link_type == "External" and (icon.link or "").endswith("emppage"):
		_ok("desktop icon link")
	else:
		_fail(f"desktop icon {icon.link_type} {icon.link}")
	roles = {r.role for r in icon.roles}
	for role in ("HR Manager", "HR User", "System Manager"):
		if role not in roles:
			_fail(f"icon role missing {role}")
		else:
			_ok(f"icon role {role}")

	# Hooks
	hooks = frappe.get_hooks("after_migrate") or []
	for path in (
		"hr_customizations.desk_setup.after_migrate",
		"hr_customizations.insights_workbook_builders.after_migrate",
	):
		if path in hooks:
			_ok(f"hook {path}")
		else:
			_fail(f"hook missing {path}")

	# Idempotent after_migrate
	from hr_customizations.desk_setup import after_migrate as desk_am
	from hr_customizations.insights_workbook_builders import after_migrate as insights_am
	from hr_customizations.setup import after_migrate as setup_am

	setup_am()
	desk_am()
	insights_am()
	_ok("after_migrate idempotent")

	print("DEEP_VERIFY_OK" if not errors else "DEEP_VERIFY_FAIL")
	report = {"ok": not errors, "ok_n": len(oks), "fail_n": len(errors), "errors": errors}
	print(frappe.as_json(report))
	return report
