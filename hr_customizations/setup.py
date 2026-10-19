"""Install / migrate helpers for HR Customizations."""

import frappe

ATTENDANCE_PAGE = "emppage"
ATTENDANCE_PAGE_LABEL = "Attendance Page"
SIDEBAR_NAME = "Shift & Attendance"
MODULE = "Shift and Attendance"

# Fields copied when rebuilding Sidebar Item rows (matches frappe SIDEBAR_ITEM_FIELDS + flags).
_ITEM_FIELDS = (
	"type",
	"label",
	"link_type",
	"link_to",
	"icon",
	"child",
	"indent",
	"collapsible",
	"keep_closed",
	"url",
	"show_arrow",
	"filters",
	"route_options",
	"navigate_to_tab",
	"open_in_new_tab",
	"added",
	"hidden",
	"is_default_module",
)


def _page_sidebar_item() -> dict:
	return {
		"type": "Link",
		"label": ATTENDANCE_PAGE_LABEL,
		"link_type": "Page",
		"link_to": ATTENDANCE_PAGE,
		"icon": "calendar",
		"child": 1,
		"indent": 0,
		"collapsible": 1,
		"keep_closed": 0,
		"show_arrow": 0,
		"open_in_new_tab": 0,
		"added": 0,
		"hidden": 0,
		"is_default_module": 0,
	}


def _row_dict(row) -> dict:
	data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
	return {field: data.get(field) for field in _ITEM_FIELDS if field in data}


def ensure_attendance_page_in_sidebar():
	"""Add Attendance Page under the Attendance section in Shift & Attendance sidebar.

	Runs on after_migrate / after_install so live gets the link without editing HRMS fixtures.
	"""
	if not frappe.db.exists("Page", ATTENDANCE_PAGE):
		return
	if not frappe.db.exists("Sidebar", SIDEBAR_NAME):
		return

	doc = frappe.get_doc("Sidebar", SIDEBAR_NAME)
	if any(row.link_to == ATTENDANCE_PAGE for row in doc.items):
		return

	rows = [_row_dict(row) for row in doc.items]
	item = _page_sidebar_item()
	inserted = False
	new_rows = []

	for row in rows:
		new_rows.append(row)
		# Place after Attendance Request inside the Attendance section (child=1).
		if (
			not inserted
			and row.get("link_to") == "Attendance Request"
			and int(row.get("child") or 0) == 1
		):
			new_rows.append(item)
			inserted = True

	if not inserted:
		# Fallback: last child under the Attendance section break.
		out = []
		in_attendance = False
		for row in new_rows:
			if row.get("type") == "Section Break" and row.get("label") == "Attendance":
				in_attendance = True
				out.append(row)
				continue
			if in_attendance and row.get("type") == "Section Break":
				out.append(item)
				inserted = True
				in_attendance = False
			out.append(row)
		if in_attendance and not inserted:
			out.append(item)
			inserted = True
		new_rows = out

	if not inserted:
		new_rows.append(item)

	doc.set("items", [])
	for row in new_rows:
		doc.append("items", row)

	# Avoid exporting the standard Sidebar JSON into the HRMS app on developer sites.
	prev_import = frappe.flags.in_import
	frappe.flags.in_import = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.in_import = prev_import

	frappe.clear_cache()


def after_install():
	ensure_attendance_page_in_sidebar()


def after_migrate():
	from hr_customizations.api import add_indexes

	add_indexes()
	ensure_attendance_page_in_sidebar()
