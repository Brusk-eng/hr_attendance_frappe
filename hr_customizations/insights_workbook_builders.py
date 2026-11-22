# Copyright (c) 2026, Marwan and contributors
# For license information, please see license.txt

"""Build Attendance Analytics Insights workbook (soft — Insights optional).

bench --site frappe16 execute hr_customizations.insights_workbook_builders.ship_all
"""

from __future__ import annotations

import frappe


def _dim(column_name: str, data_type: str = "String", label: str | None = None):
	return {
		"dimension_name": label or column_name.replace("_", " ").title(),
		"column_name": column_name,
		"data_type": data_type,
	}


def _measure(column_name: str, data_type: str = "Integer", aggregation: str = "sum", label: str | None = None):
	return {
		"measure_name": label or column_name.replace("_", " ").title(),
		"column_name": column_name,
		"data_type": data_type,
		"aggregation": aggregation,
	}


def _empty_filters():
	return {"logical_operator": "And", "filters": []}


def _filter_links(query_name: str, field: str, chart_names: list[str]) -> dict:
	return {chart: f"`{query_name}`.`{field}`" for chart in chart_names}


def _delete_workbook(name: str) -> bool:
	"""Delete workbook when editable; return False if standard / locked on production."""
	if not frappe.db.exists("Insights Workbook", name):
		return True
	try:
		frappe.delete_doc("Insights Workbook", name, force=True, ignore_permissions=True)
		return True
	except frappe.ValidationError:
		# Insights standard docs are not trashable outside developer mode.
		return False


def _delete_by_title(title: str) -> bool:
	ok = True
	for name in frappe.get_all("Insights Workbook", filters={"title": title}, pluck="name"):
		if not _delete_workbook(name):
			ok = False
	return ok


def _delete_by_name(name: str) -> bool:
	return _delete_workbook(name)


def _create_query(workbook: str, title: str, sql: str, sort_order: int) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Insights Query v3",
				"title": title,
				"workbook": workbook,
				"sort_order": sort_order,
				"use_live_connection": 1,
				"is_native_query": 1,
				"is_builder_query": 0,
				"is_script_query": 0,
				"operations": frappe.as_json(
					[{"type": "sql", "data_source": "Site DB", "raw_sql": sql.strip()}]
				),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _create_chart(workbook: str, title: str, query: str, chart_type: str, config: dict, sort_order: int) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Insights Chart v3",
				"title": title,
				"workbook": workbook,
				"query": query,
				"chart_type": chart_type,
				"config": frappe.as_json(config),
				"sort_order": sort_order,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _create_dashboard(workbook: str, title: str, items: list) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Insights Dashboard v3",
				"title": title,
				"workbook": workbook,
				"items": frappe.as_json(items),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _has_location_field() -> bool:
	return frappe.get_meta("Attendance").has_field("custom_employment_type_location")


_ATTENDANCE_DETAIL_BASE = """
SELECT
	a.name AS attendance,
	a.employee,
	a.employee_name,
	a.company,
	a.status,
	a.attendance_date,
	a.docstatus,
	e.department
FROM `tabAttendance` a
LEFT JOIN `tabEmployee` e ON e.name = a.employee
WHERE a.docstatus < 2
ORDER BY a.attendance_date DESC
""".strip()


def _attendance_detail_sql() -> str:
	if _has_location_field():
		return """
SELECT
	a.name AS attendance,
	a.employee,
	a.employee_name,
	a.company,
	a.status,
	a.attendance_date,
	a.docstatus,
	a.custom_employment_type_location AS location,
	e.department
FROM `tabAttendance` a
LEFT JOIN `tabEmployee` e ON e.name = a.employee
WHERE a.docstatus < 2
ORDER BY a.attendance_date DESC
""".strip()
	return _ATTENDANCE_DETAIL_BASE


def build_attendance_analytics() -> dict:
	title = "Attendance Analytics"
	# On production, shipped standard workbook cannot be deleted/rebuilt.
	if frappe.db.exists("Insights Workbook", "attendance_analytics"):
		if not frappe.conf.developer_mode:
			return {
				"workbook": "attendance_analytics",
				"title": title,
				"dashboard": "attendance_analytics",
				"skipped": "standard workbook already present",
			}
	if not _delete_by_title(title) or not _delete_by_name("attendance_analytics"):
		return {
			"workbook": "attendance_analytics",
			"title": title,
			"dashboard": "attendance_analytics",
			"skipped": "could not replace locked standard workbook",
		}

	workbook = frappe.get_doc({"doctype": "Insights Workbook", "title": title}).insert(
		ignore_permissions=True
	)
	wb = workbook.name

	by_status = _create_query(
		wb,
		"Status Counts",
		"""
SELECT
	status,
	COUNT(*) AS attendance_count
FROM `tabAttendance`
WHERE docstatus < 2
GROUP BY status
ORDER BY attendance_count DESC
""",
		0,
	)
	by_company = _create_query(
		wb,
		"Company Counts",
		"""
SELECT
	IFNULL(company, '') AS company,
	COUNT(*) AS attendance_count
FROM `tabAttendance`
WHERE docstatus < 2
GROUP BY company
ORDER BY attendance_count DESC
""",
		1,
	)
	detail = _create_query(wb, "Attendance Detail", _attendance_detail_sql(), 2)

	charts = {}
	charts["kpi"] = _create_chart(
		wb,
		"Total Records",
		by_status,
		"Number",
		{
			"number_columns": [_measure("attendance_count", label="Records")],
			"number_column_options": [{"shorten_numbers": False}],
			"comparison": False,
			"sparkline": False,
			"order_by": [],
			"limit": 100,
			"filters": _empty_filters(),
		},
		0,
	)
	charts["donut"] = _create_chart(
		wb,
		"Status Mix",
		by_status,
		"Donut",
		{
			"x_axis": {"dimension": _dim("status")},
			"y_axis": {"series": [{"measure": _measure("attendance_count", label="Records")}]},
			"order_by": [],
			"limit": 10,
			"filters": _empty_filters(),
		},
		1,
	)
	charts["bar"] = _create_chart(
		wb,
		"By Company",
		by_company,
		"Bar",
		{
			"x_axis": {"dimension": _dim("company")},
			"y_axis": {"series": [{"measure": _measure("attendance_count", label="Records")}]},
			"order_by": [],
			"limit": 20,
			"filters": _empty_filters(),
		},
		2,
	)
	detail_rows = [
		_dim("attendance"),
		_dim("employee_name"),
		_dim("company"),
		_dim("status"),
		_dim("attendance_date", "Date"),
		_dim("department"),
	]
	if _has_location_field():
		detail_rows.insert(4, _dim("location"))
	charts["table"] = _create_chart(
		wb,
		"Attendance Detail",
		detail,
		"Table",
		{
			"rows": detail_rows,
			"columns": [],
			"values": [],
			"order_by": [
				{"column": {"type": "column", "column_name": "attendance_date"}, "direction": "desc"}
			],
			"limit": 200,
			"filters": _empty_filters(),
		},
		3,
	)

	items = [
		{
			"type": "filter",
			"filter_name": "Status",
			"filter_type": "String",
			"icon": "check",
			"links": {
				**_filter_links(by_status, "status", [charts["kpi"], charts["donut"]]),
				**_filter_links(detail, "status", [charts["table"]]),
			},
			"layout": {"i": "f-status", "x": 0, "y": 0, "w": 4, "h": 1},
		},
		{
			"type": "filter",
			"filter_name": "Company",
			"filter_type": "String",
			"icon": "building",
			"links": {
				**_filter_links(by_company, "company", [charts["bar"]]),
				**_filter_links(detail, "company", [charts["table"]]),
			},
			"layout": {"i": "f-co", "x": 4, "y": 0, "w": 4, "h": 1},
		},
		{
			"type": "filter",
			"filter_name": "Employee",
			"filter_type": "String",
			"icon": "user",
			"links": _filter_links(detail, "employee_name", [charts["table"]]),
			"layout": {"i": "f-emp", "x": 8, "y": 0, "w": 4, "h": 1},
		},
	]
	if _has_location_field():
		items.append(
			{
				"type": "filter",
				"filter_name": "Location",
				"filter_type": "String",
				"icon": "map-pin",
				"links": _filter_links(detail, "location", [charts["table"]]),
				"layout": {"i": "f-loc", "x": 12, "y": 0, "w": 4, "h": 1},
			}
		)
	items.extend(
		[
			{"type": "chart", "chart": charts["kpi"], "layout": {"i": "c-kpi", "x": 0, "y": 1, "w": 5, "h": 3}},
			{"type": "chart", "chart": charts["donut"], "layout": {"i": "c-donut", "x": 5, "y": 1, "w": 7, "h": 8}},
			{"type": "chart", "chart": charts["bar"], "layout": {"i": "c-bar", "x": 12, "y": 1, "w": 8, "h": 8}},
			{"type": "chart", "chart": charts["table"], "layout": {"i": "c-tbl", "x": 0, "y": 9, "w": 20, "h": 10}},
		]
	)
	_create_dashboard(wb, "Attendance Analytics", items)
	shipped = frappe.get_doc("Insights Workbook", wb).mark_as_standard(
		name="attendance_analytics", module="HR Customizations"
	)
	frappe.db.commit()
	return {"workbook": shipped, "title": title, "dashboard": "attendance_analytics"}


def wire_classic_dashboard() -> dict:
	"""Point HRMS classic Dashboard ``Attendance`` at Insights sidecar when present."""
	if not frappe.db.exists("DocType", "Insights Dashboard v3"):
		return {"skipped": "Insights not installed"}
	if not frappe.get_meta("Dashboard").has_field("insights_dashboard"):
		return {"skipped": "insights_dashboard field missing"}

	classic = "Attendance"
	insights = frappe.db.get_value(
		"Insights Dashboard v3",
		{"workbook": "attendance_analytics", "title": "Attendance Analytics"},
		"name",
	)
	if not insights:
		# After mark_as_standard workbook name becomes attendance_analytics
		insights = frappe.db.get_value(
			"Insights Dashboard v3",
			{"title": "Attendance Analytics"},
			"name",
		)
	if frappe.db.exists("Dashboard", classic) and insights:
		frappe.db.set_value("Dashboard", classic, "insights_dashboard", insights)
		frappe.db.commit()
		return {classic: insights}
	return {"missing": [classic, insights]}


def ensure_workbook_imported() -> dict:
	"""Import shipped fixture if Insights present and workbook missing."""
	if not frappe.db.exists("DocType", "Insights Workbook"):
		return {"skipped": "Insights not installed"}
	if frappe.db.exists("Insights Workbook", "attendance_analytics"):
		return {"ok": True, "already": True}
	try:
		from insights.insights.doctype.insights_workbook import insights_workbook as iw_mod

		if hasattr(iw_mod, "import_shipped"):
			# Prefer standard Insights import helpers when available
			pass
	except Exception:
		pass
	# Soft: build on site if missing (idempotent ship for first migrate with Insights)
	try:
		return {"built": build_attendance_analytics()}
	except Exception as e:
		frappe.log_error(title="hr_customizations Insights ship", message=str(e))
		return {"error": str(e)}


def after_migrate() -> None:
	if not frappe.db.exists("DocType", "Insights Workbook"):
		return
	if not frappe.db.exists("Insights Workbook", "attendance_analytics"):
		ensure_workbook_imported()
	wire_classic_dashboard()


def ship_all() -> dict:
	if not frappe.db.exists("DocType", "Insights Workbook"):
		return {"ok": False, "error": "Insights not installed"}
	frappe.set_user("Administrator")
	result = {
		"attendance_analytics": build_attendance_analytics(),
		"classic": wire_classic_dashboard(),
		"ok": True,
	}
	print(frappe.as_json(result))
	return result
