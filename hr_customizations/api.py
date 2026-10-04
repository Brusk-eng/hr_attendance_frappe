import calendar

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today

STATUSES = ("Present", "Absent", "On Leave")
PAGE_LENGTH = 100


def _employee_filters(search=None, employee=None):
	filters = {"status": "Active"}
	if employee:
		filters["name"] = employee
	or_filters = None
	if search:
		or_filters = {"employee_name": ["like", f"%{search}%"], "name": ["like", f"%{search}%"]}
	return filters, or_filters


@frappe.whitelist()
def get_monthly_attendance(year, month, search=None, start=0):
	"""Employees (100 per page) with their attendance for the given month."""
	frappe.has_permission("Attendance", "read", throw=True)

	year, month, start = cint(year), cint(month), cint(start)
	days_in_month = calendar.monthrange(year, month)[1]
	from_date = getdate(f"{year}-{month:02d}-01")
	to_date = getdate(f"{year}-{month:02d}-{days_in_month:02d}")

	filters, or_filters = _employee_filters(search)
	employees = frappe.get_list(
		"Employee",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "employee_name", "designation", "department", "date_of_joining"],
		order_by="employee_name asc",
		start=start,
		page_length=PAGE_LENGTH,
	)
	emp_names = frappe.get_list(
		"Employee", filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0
	)
	total = len(emp_names)

	attendance = {}
	if employees:
		rows = frappe.get_list(
			"Attendance",
			filters={
				"employee": ["in", [e.name for e in employees]],
				"attendance_date": ["between", [from_date, to_date]],
				"docstatus": ["<", 2],
			},
			fields=["name", "employee", "attendance_date", "status", "docstatus"],
			limit_page_length=0,
		)
		for r in rows:
			attendance.setdefault(r.employee, {})[str(r.attendance_date)] = {
				"name": r.name,
				"status": r.status,
				"docstatus": r.docstatus,
			}

	# Workers have no weekends: every day of the month counts, up to today for the current month.
	last_day = min(to_date, getdate(today()))
	working_days = (last_day - from_date).days + 1 if last_day >= from_date else 0

	for e in employees:
		marks = attendance.get(e.name, {})
		e.attendance = marks
		# Days before the joining date are not working days for that employee.
		emp_start = max(from_date, getdate(e.date_of_joining)) if e.date_of_joining else from_date
		emp_working_days = (last_day - emp_start).days + 1 if last_day >= emp_start else 0
		e.totals = {
			"working_days": emp_working_days,
			"present": sum(1 for m in marks.values() if m["status"] in ("Present", "Work From Home")),
			"absent": sum(1 for m in marks.values() if m["status"] == "Absent"),
			"leave": sum(1 for m in marks.values() if m["status"] == "On Leave"),
			"half_day": sum(1 for m in marks.values() if m["status"] == "Half Day"),
			"draft": sum(1 for m in marks.values() if m["docstatus"] == 0),
		}
		e.totals["unmarked"] = max(emp_working_days - len(marks), 0)

	# KPI cards: today's status (or the last day of a past month) for all matching employees.
	focus_date = min(to_date, max(from_date, getdate(today())))
	day_counts = {}
	if total:
		for r in frappe.get_list(
			"Attendance",
			filters={"employee": ["in", emp_names], "attendance_date": focus_date, "docstatus": ["<", 2]},
			fields=["status", {"COUNT": "*", "as": "count"}],
			group_by="status",
		):
			day_counts[r.status] = r.count

	return {
		"focus_date": focus_date,
		"day_counts": day_counts,
		"employees": employees,
		"total": total,
		"page_length": PAGE_LENGTH,
		"days_in_month": days_in_month,
		"working_days": working_days,
	}


@frappe.whitelist()
def mark_attendance(employee, attendance_date, status, submit=1, leave_type=None):
	"""Create (or update) the Attendance of an employee for one day."""
	if status not in STATUSES:
		frappe.throw(_("Invalid attendance status {0}").format(status))
	attendance_date = getdate(attendance_date)
	if attendance_date > getdate(today()):
		frappe.throw(_("Attendance can not be marked for future dates"))
	submit = cint(submit)

	existing = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": attendance_date, "docstatus": ["<", 2]},
		["name", "docstatus", "status"],
		as_dict=True,
	)

	amended_from = None
	if existing and existing.docstatus == 1:
		if existing.status == status:
			return existing.name
		# Changing a submitted attendance: cancel it and create an amendment.
		old = frappe.get_doc("Attendance", existing.name)
		old.cancel()
		amended_from = old.name
		existing = None

	if existing:
		doc = frappe.get_doc("Attendance", existing.name)
	else:
		doc = frappe.new_doc("Attendance")
		doc.employee = employee
		doc.attendance_date = attendance_date
		doc.company = frappe.db.get_value("Employee", employee, "company")
		doc.amended_from = amended_from

	doc.status = status
	doc.leave_type = (leave_type or "Leave Without Pay") if status == "On Leave" else None
	doc.save()
	if submit:
		doc.submit()
	return doc.name


@frappe.whitelist()
def mark_bulk_attendance(employees, attendance_date, status, submit=1, leave_type=None):
	"""Mark the same status for several employees who are not yet marked on that date."""
	employees = frappe.parse_json(employees) or []
	already = set(
		frappe.get_all(
			"Attendance",
			filters={
				"employee": ["in", employees],
				"attendance_date": getdate(attendance_date),
				"docstatus": ["<", 2],
			},
			pluck="employee",
		)
	) if employees else set()

	marked, failed = 0, []
	for employee in employees:
		if employee in already:
			continue
		try:
			mark_attendance(employee, attendance_date, status, submit, leave_type)
			marked += 1
		except Exception:
			frappe.clear_last_message()
			failed.append(employee)
	return {"marked": marked, "skipped": len(already), "failed": failed}


@frappe.whitelist()
def submit_attendance(names):
	"""Submit draft Attendance records."""
	names = frappe.parse_json(names) or []
	submitted = 0
	for name in names:
		doc = frappe.get_doc("Attendance", name)
		if doc.docstatus == 0:
			doc.submit()
			submitted += 1
	return submitted


@frappe.whitelist()
def get_attendance_summary(from_date, to_date, employee=None):
	"""Attendance status counts for a period, overall and per employee."""
	frappe.has_permission("Attendance", "read", throw=True)
	from_date, to_date = getdate(from_date), getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("From Date can not be after To Date"))

	filters = {"attendance_date": ["between", [from_date, to_date]], "docstatus": 1}
	if employee:
		filters["employee"] = employee

	rows = frappe.get_list(
		"Attendance",
		filters=filters,
		fields=["employee", "employee_name", "status", {"COUNT": "*", "as": "count"}],
		group_by="employee, employee_name, status",
		order_by="employee_name asc",
		limit_page_length=0,
	)

	all_statuses = ["Present", "Absent", "On Leave", "Half Day", "Work From Home"]
	totals = dict.fromkeys(all_statuses, 0)
	per_employee = {}
	for r in rows:
		totals[r.status] = totals.get(r.status, 0) + r.count
		emp = per_employee.setdefault(
			r.employee, {"employee": r.employee, "employee_name": r.employee_name, **dict.fromkeys(all_statuses, 0)}
		)
		emp[r.status] = emp.get(r.status, 0) + r.count

	# Daily trend for the period (capped to keep the chart readable).
	daily = frappe.get_list(
		"Attendance",
		filters=filters,
		fields=["attendance_date", "status", {"COUNT": "*", "as": "count"}],
		group_by="attendance_date, status",
		order_by="attendance_date asc",
		limit_page_length=0,
	)
	days = []
	d = from_date
	while d <= to_date and len(days) < 370:
		days.append(str(d))
		d = add_days(d, 1)
	trend = {s: dict.fromkeys(days, 0) for s in all_statuses}
	for r in daily:
		key = str(r.attendance_date)
		if key in trend.get(r.status, {}):
			trend[r.status][key] = r.count

	return {
		"statuses": all_statuses,
		"totals": totals,
		"employees": list(per_employee.values()),
		"days": days,
		"trend": {s: list(v.values()) for s, v in trend.items()},
		"period_days": (to_date - from_date).days + 1,
	}


def add_indexes():
	"""after_migrate: composite index used by the attendance page and dashboard."""
	frappe.db.add_index("Attendance", ["attendance_date", "status"], "attendance_date_status_index")
