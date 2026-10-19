import frappe


def execute():
	frappe.get_attr("hr_customizations.setup.ensure_attendance_page_in_sidebar")()
