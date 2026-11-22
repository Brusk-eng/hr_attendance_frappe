# Copyright (c) 2026, Marwan and contributors
# For license information, please see license.txt

"""Desktop Icon for Attendance Page — External link to /app/emppage."""

from __future__ import annotations

import frappe

ICON_NAME = "Attendance Page"
ICON_LABEL = "Attendance Page"
PAGE_ROUTE = "/app/emppage"
ROLES = ("HR Manager", "HR User", "System Manager")


def ensure_desktop_icon() -> dict:
	"""Create or refresh External Desktop Icon for the attendance sheet page."""
	if not frappe.db.exists("Page", "emppage"):
		return {"skipped": "page missing"}

	values = {
		"label": ICON_LABEL,
		"icon_type": "Link",
		"link_type": "External",
		"link": PAGE_ROUTE,
		"icon": "calendar",
		"app": "hr_customizations",
		"standard": 0,
		"hidden": 0,
	}

	if frappe.db.exists("Desktop Icon", ICON_NAME):
		frappe.db.set_value("Desktop Icon", ICON_NAME, values, update_modified=False)
		doc = frappe.get_doc("Desktop Icon", ICON_NAME)
	else:
		doc = frappe.get_doc({"doctype": "Desktop Icon", "name": ICON_NAME, **values})
		doc.insert(ignore_permissions=True)

	existing = {r.role for r in (doc.roles or [])}
	changed = False
	for role in ROLES:
		if role not in existing and frappe.db.exists("Role", role):
			doc.append("roles", {"role": role})
			changed = True
	if changed:
		doc.save(ignore_permissions=True)

	frappe.clear_cache()
	return {"ok": True, "name": ICON_NAME}


def after_migrate() -> None:
	ensure_desktop_icon()
