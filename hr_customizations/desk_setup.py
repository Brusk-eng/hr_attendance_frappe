# Copyright (c) 2026, Marwan and contributors
# For license information, please see license.txt

"""Desk helpers — remove unused Desktop Icon for Attendance Page."""

from __future__ import annotations

import frappe

ICON_NAME = "Attendance Page"


def remove_desktop_icon() -> dict:
	"""Delete Attendance Page Desktop Icon if present (sidebar link is enough)."""
	if not frappe.db.exists("Desktop Icon", ICON_NAME):
		return {"ok": True, "already_absent": True}

	frappe.delete_doc("Desktop Icon", ICON_NAME, force=True, ignore_permissions=True)
	frappe.clear_cache()
	return {"ok": True, "removed": ICON_NAME}


def after_migrate() -> None:
	remove_desktop_icon()
