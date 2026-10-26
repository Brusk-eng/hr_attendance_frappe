import calendar

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

STATUSES = ("Present", "Absent", "On Leave", "Half Day", "Work From Home")
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
	# All matching employees (name + display name) so we can sort marked-first across pages.
	all_employees = frappe.get_list(
		"Employee",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "employee_name"],
		order_by="employee_name asc",
		limit_page_length=0,
	)
	emp_names = [e.name for e in all_employees]
	total = len(emp_names)

	marked_employees = set()
	if emp_names:
		marked_employees = set(
			frappe.get_all(
				"Attendance",
				filters={
					"employee": ["in", emp_names],
					"attendance_date": ["between", [from_date, to_date]],
					"docstatus": ["<", 2],
				},
				pluck="employee",
				distinct=True,
			)
		)

	# Marked attendance first, then unmarked; name A→Z within each group.
	all_employees.sort(
		key=lambda e: (0 if e.name in marked_employees else 1, (e.employee_name or e.name or "").lower())
	)
	page_names = [e.name for e in all_employees[start : start + PAGE_LENGTH]]

	employees = []
	if page_names:
		by_name = {
			e.name: e
			for e in frappe.get_list(
				"Employee",
				filters={"name": ["in", page_names]},
				fields=["name", "employee_name", "designation", "department", "date_of_joining", "company"],
				limit_page_length=0,
			)
		}
		employees = [by_name[n] for n in page_names if n in by_name]

	attendance = {}
	if employees:
		att_fields = [
			"name",
			"employee",
			"attendance_date",
			"status",
			"docstatus",
			"half_day_status",
			"leave_type",
		]
		if _has_employment_type_location_field():
			att_fields.append("custom_employment_type_location")
		rows = frappe.get_list(
			"Attendance",
			filters={
				"employee": ["in", [e.name for e in employees]],
				"attendance_date": ["between", [from_date, to_date]],
				"docstatus": ["<", 2],
			},
			fields=att_fields,
			limit_page_length=0,
		)
		for r in rows:
			attendance.setdefault(r.employee, {})[str(r.attendance_date)] = {
				"name": r.name,
				"status": r.status,
				"docstatus": r.docstatus,
				"half_day_status": r.get("half_day_status") or None,
				"leave_type": r.get("leave_type") or None,
				"employment_type_location": r.get("custom_employment_type_location") or None,
			}

	holiday_day_map = _get_employee_holiday_day_map(
		{e.name: e.company for e in employees}, from_date, to_date
	)

	# Working days = calendar days in range up to today, minus Holiday / Weekly Off from Holiday List.
	last_day = min(to_date, getdate(today()))

	for e in employees:
		marks = attendance.get(e.name, {})
		cal = holiday_day_map.get(e.name, {})
		e.attendance = marks
		e.calendar = cal
		# Days before the joining date are not working days for that employee.
		emp_start = max(from_date, getdate(e.date_of_joining)) if e.date_of_joining else from_date
		emp_working_days = 0
		off_days = 0
		d = emp_start
		while d <= last_day:
			ds = str(d)
			day_off = cal.get(ds)
			if day_off in ("Holiday", "Weekly Off"):
				off_days += 1
			else:
				emp_working_days += 1
			d = add_days(d, 1)
		def _loc_count(loc):
			return sum(
				1
				for m in marks.values()
				if m["status"] == "Present" and (m.get("employment_type_location") or "") == loc
			)

		e.totals = {
			"working_days": emp_working_days,
			"holidays": off_days,
			"present": sum(1 for m in marks.values() if m["status"] in ("Present", "Work From Home")),
			"present_office": _loc_count("Office"),
			"present_site": _loc_count("Site Location"),
			"present_base": _loc_count("Base"),
			"absent": sum(1 for m in marks.values() if m["status"] == "Absent"),
			"leave": sum(1 for m in marks.values() if m["status"] == "On Leave"),
			"half_day": sum(1 for m in marks.values() if m["status"] == "Half Day"),
			"wfh": sum(1 for m in marks.values() if m["status"] == "Work From Home"),
			"draft": sum(1 for m in marks.values() if m["docstatus"] == 0),
		}
		# Unmarked = working days with no Attendance record (H/WO days are not unmarked).
		marked_working = 0
		for ds in marks:
			dd = getdate(ds)
			if dd < emp_start or dd > last_day:
				continue
			if cal.get(ds) in ("Holiday", "Weekly Off"):
				continue
			marked_working += 1
		e.totals["unmarked"] = max(emp_working_days - marked_working, 0)

	# Month-level working days (for sheet header): first page employee companies may differ;
	# use union off-days from holiday lists of employees on this page, else calendar span.
	page_off = set()
	for emp_cal in holiday_day_map.values():
		for ds, kind in emp_cal.items():
			if kind in ("Holiday", "Weekly Off") and from_date <= getdate(ds) <= last_day:
				page_off.add(ds)
	span = (last_day - from_date).days + 1 if last_day >= from_date else 0
	working_days = max(span - len(page_off), 0) if holiday_day_map else span

	# KPI cards: today's status (or the last day of a past month) for all matching employees.
	focus_date = min(to_date, max(from_date, getdate(today())))
	day_counts = {}
	day_location_counts = {"Office": 0, "Site Location": 0, "Base": 0}
	if total:
		for r in frappe.get_list(
			"Attendance",
			filters={"employee": ["in", emp_names], "attendance_date": focus_date, "docstatus": ["<", 2]},
			fields=["status", {"COUNT": "*", "as": "count"}],
			group_by="status",
		):
			day_counts[r.status] = r.count
		if _has_employment_type_location_field():
			for r in frappe.get_list(
				"Attendance",
				filters={
					"employee": ["in", emp_names],
					"attendance_date": focus_date,
					"status": "Present",
					"docstatus": ["<", 2],
				},
				fields=["custom_employment_type_location", {"COUNT": "*", "as": "count"}],
				group_by="custom_employment_type_location",
			):
				loc = (r.get("custom_employment_type_location") or "").strip()
				if loc in day_location_counts:
					day_location_counts[loc] = r.count

	return {
		"focus_date": focus_date,
		"day_counts": day_counts,
		"day_location_counts": day_location_counts,
		"employees": employees,
		"total": total,
		"page_length": PAGE_LENGTH,
		"days_in_month": days_in_month,
		"working_days": working_days,
	}


# Work From Home does not use Employment Type Location (Office/Site/Base).
LOCATION_STATUSES = ("Present", "Half Day")
LOCATION_OPTIONS = ("Office", "Site Location", "Base")


def _get_employee_holiday_day_map(employee_company_map, from_date, to_date):
	"""{employee: {yyyy-mm-dd: 'Holiday'|'Weekly Off'}} from Holiday List (incl. Fri/Sat WO)."""
	if not employee_company_map:
		return {}
	try:
		from hrms.utils.holiday_list import (
			get_holiday_list_ranges_for_employees,
			get_holidays_in_ranges_map,
		)
	except ImportError:
		return {}

	ranges = get_holiday_list_ranges_for_employees(
		employee_company_map, from_date, to_date, raise_exception=False
	)
	holidays_by_emp = get_holidays_in_ranges_map(ranges)
	day_map = {}
	for employee, holidays in holidays_by_emp.items():
		days = {}
		for h in holidays:
			ds = str(getdate(h.holiday_date))
			days[ds] = "Weekly Off" if h.get("weekly_off") else "Holiday"
		day_map[employee] = days
	return day_map


def _has_employment_type_location_field():
	return frappe.get_meta("Attendance").has_field("custom_employment_type_location")


def _apply_employment_type_location(doc, status, employment_type_location=None):
	"""Set Galiska TRS location field when Present (or clear it otherwise)."""
	if not _has_employment_type_location_field():
		return
	if status in LOCATION_STATUSES:
		if not employment_type_location:
			frappe.throw(
				_(
					"Employment Type Location is required when Status is {0}. "
					"Please select Office, Site Location, or Base."
				).format(frappe.bold(status)),
				title=_("Employment Type Location Required"),
			)
		if employment_type_location not in LOCATION_OPTIONS:
			frappe.throw(_("Invalid Employment Type Location {0}").format(employment_type_location))
		doc.custom_employment_type_location = employment_type_location
	else:
		doc.custom_employment_type_location = ""


HALF_DAY_OTHER_STATUSES = ("Present", "Absent")


def _has_approved_leave(employee, attendance_date):
	return bool(
		frappe.db.exists(
			"Leave Application",
			{
				"employee": employee,
				"from_date": ("<=", attendance_date),
				"to_date": (">=", attendance_date),
				"status": "Approved",
				"docstatus": 1,
			},
		)
	)


def _get_approved_leave_application(employee, attendance_date, leave_type=None):
	filters = {
		"employee": employee,
		"from_date": ("<=", attendance_date),
		"to_date": (">=", attendance_date),
		"status": "Approved",
		"docstatus": 1,
	}
	if leave_type:
		filters["leave_type"] = leave_type
	return frappe.db.get_value("Leave Application", filters, "name")


def _cancel_leave_application(leave_application):
	"""Cancel Leave Application so leave balance is restored and linked attendance is cancelled."""
	if not leave_application:
		return
	la = frappe.get_doc("Leave Application", leave_application)
	if la.docstatus != 1:
		return
	la.flags.ignore_permissions = True
	la.cancel()


def _clear_day_for_leave_change(employee, attendance_date, existing):
	"""Cancel linked Leave Application / Attendance before changing the day's mark."""
	leave_application = (existing or {}).get("leave_application") or _get_approved_leave_application(
		employee, attendance_date
	)
	if leave_application:
		_cancel_leave_application(leave_application)
		return

	if not existing:
		return
	doc = frappe.get_doc("Attendance", existing.name)
	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.cancel()
	elif doc.docstatus == 0:
		frappe.delete_doc("Attendance", doc.name, force=1, ignore_permissions=True)


def _leave_allocation_list_link():
	return f'<a href="{frappe.utils.get_url_to_list("Leave Allocation")}">{_("Leave Allocation")}</a>'


def _validate_leave_allocation(employee, leave_type, attendance_date):
	"""Block On Leave when the employee has no usable allocation for that leave type/date.

	Does not create Attendance or Leave Application when validation fails.
	"""
	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on, is_lwp

	if is_lwp(leave_type):
		return

	list_link = _leave_allocation_list_link()
	date_label = frappe.bold(frappe.format(attendance_date, {"fieldtype": "Date"}))

	has_allocation = frappe.db.exists(
		"Leave Allocation",
		{
			"employee": employee,
			"leave_type": leave_type,
			"docstatus": 1,
			"from_date": ("<=", attendance_date),
			"to_date": (">=", attendance_date),
		},
	)
	if not has_allocation:
		frappe.throw(
			_(
				"Leave Type {0} is not allocated to Employee {1} for {2}. "
				"Create a Leave Allocation from {3}, then try again. No attendance was marked."
			).format(frappe.bold(leave_type), frappe.bold(employee), date_label, list_link),
			title=_("Leave Not Allocated"),
		)

	balance = get_leave_balance_on(
		employee,
		leave_type,
		attendance_date,
		to_date=attendance_date,
		for_consumption=True,
	)
	available = flt(balance.get("leave_balance_for_consumption"))
	if available < 1:
		frappe.throw(
			_(
				"Insufficient leave balance for Employee {0} and Leave Type {1} on {2} "
				"(available: {3}). Update the allocation in {4}. No attendance was marked."
			).format(
				frappe.bold(employee),
				frappe.bold(leave_type),
				date_label,
				frappe.bold(available),
				list_link,
			),
			title=_("Insufficient Leave Balance"),
		)


def _ensure_holiday_list_for_leave(employee, attendance_date):
	"""Leave Application ledger creation requires a Holiday List for the employee/company."""
	from hrms.utils.holiday_list import get_holiday_list_for_employee

	if get_holiday_list_for_employee(employee, raise_exception=False, as_on=attendance_date):
		return

	company = frappe.db.get_value("Employee", employee, "company")
	matching = frappe.db.get_value(
		"Holiday List",
		{"from_date": ("<=", attendance_date), "to_date": (">=", attendance_date)},
		"name",
		order_by="creation desc",
	)
	if matching and company and not frappe.db.get_value("Company", company, "default_holiday_list"):
		frappe.db.set_value("Company", company, "default_holiday_list", matching)
		return

	frappe.throw(
		_(
			"No Holiday List found for Employee {0} on {1}. "
			"Assign a Holiday List on the Employee or set Company Default Holiday List first. "
			"No attendance was marked."
		).format(
			frappe.bold(employee),
			frappe.bold(frappe.format(attendance_date, {"fieldtype": "Date"})),
		)
	)


def _create_leave_application_for_day(employee, attendance_date, leave_type):
	"""Create and submit an Approved Leave Application for one day.

	HRMS then deducts leave balance (Leave Ledger) and creates/links Attendance.
	"""
	from hrms.hr.doctype.leave_application.leave_application import get_employee_leave_approver

	# Leave Application refuses submit when Present/WFH attendance already exists for the day.
	blocking = frappe.db.get_value(
		"Attendance",
		{
			"employee": employee,
			"attendance_date": attendance_date,
			"docstatus": 1,
			"status": ["in", ["Present", "Work From Home"]],
		},
		["name", "status"],
		as_dict=True,
	)
	if blocking:
		old = frappe.get_doc("Attendance", blocking.name)
		old.flags.ignore_permissions = True
		old.cancel()

	_ensure_holiday_list_for_leave(employee, attendance_date)

	leave_approver = get_employee_leave_approver(employee) or frappe.session.user
	if (
		frappe.db.get_single_value("HR Settings", "leave_approver_mandatory_in_leave_application")
		and not leave_approver
	):
		frappe.throw(
			_("Leave Approver is required. Set a Leave Approver on Employee {0} or in the Department.").format(
				frappe.bold(employee)
			)
		)

	la = frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": employee,
			"leave_type": leave_type,
			"from_date": attendance_date,
			"to_date": attendance_date,
			"status": "Approved",
			"posting_date": today(),
			"company": frappe.db.get_value("Employee", employee, "company"),
			"leave_approver": leave_approver,
			"description": _("Marked from Worker Attendance"),
			"follow_via_email": 0,
		}
	)
	la.flags.ignore_permissions = True
	la.insert()
	la.submit()

	attendance_name = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": attendance_date, "docstatus": ["<", 2]},
		"name",
	)
	if not attendance_name:
		frappe.throw(
			_("Leave Application {0} was submitted but Attendance was not created.").format(la.name)
		)
	return attendance_name


def _preserve_half_day_status(doc, half_day_status):
	"""HRMS Attendance.check_leave_record forces half_day_status=Absent when there is no leave.

	The attendance page lets HR pick Present/Absent for the other half without a Leave Application,
	so keep the chosen value (and skip the noisy alert) when marking Half Day from this API.
	"""
	from hrms.hr.doctype.attendance.attendance import Attendance as HRMSAttendance

	intended = half_day_status

	def check_leave_record():
		if (
			doc.status == "Half Day"
			and intended in HALF_DAY_OTHER_STATUSES
			and not _has_approved_leave(doc.employee, doc.attendance_date)
		):
			doc.leave_type = None
			doc.leave_application = None
			doc.modify_half_day_status = 0
			doc.half_day_status = intended
			return

		HRMSAttendance.check_leave_record(doc)
		if doc.status == "Half Day" and intended in HALF_DAY_OTHER_STATUSES:
			doc.half_day_status = intended

	doc.check_leave_record = check_leave_record


@frappe.whitelist()
def mark_attendance(
	employee,
	attendance_date,
	status,
	submit=1,
	leave_type=None,
	employment_type_location=None,
	half_day_status=None,
):
	"""Create (or update) the Attendance of an employee for one day.

	On Leave creates an Approved Leave Application so allocated leave balance is deducted.
	"""
	if status not in STATUSES:
		frappe.throw(_("Invalid attendance status {0}").format(status))
	attendance_date = getdate(attendance_date)
	if attendance_date > getdate(today()):
		frappe.throw(_("Attendance can not be marked for future dates"))
	submit = cint(submit)

	if status == "On Leave":
		if not leave_type:
			frappe.throw(_("Leave Type is required when Status is On Leave"))
		if not frappe.db.exists("Leave Type", leave_type):
			frappe.throw(_("Invalid Leave Type {0}").format(leave_type))
	else:
		leave_type = None

	if status == "Half Day":
		half_day_status = half_day_status or "Absent"
		if half_day_status not in HALF_DAY_OTHER_STATUSES:
			frappe.throw(_("Invalid Status for Other Half {0}").format(half_day_status))
	else:
		half_day_status = None

	existing_fields = ["name", "docstatus", "status", "half_day_status", "leave_type", "leave_application"]
	if _has_employment_type_location_field():
		existing_fields.append("custom_employment_type_location")
	existing = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": attendance_date, "docstatus": ["<", 2]},
		existing_fields,
		as_dict=True,
	)

	if status == "On Leave":
		same_leave = (
			existing
			and existing.status == "On Leave"
			and (existing.get("leave_type") or None) == leave_type
			and (
				existing.get("leave_application")
				or _get_approved_leave_application(employee, attendance_date, leave_type)
			)
		)
		if same_leave:
			return existing.name

		# Validate before changing anything so a failed leave mark never creates/cancels attendance.
		_validate_leave_allocation(employee, leave_type, attendance_date)
		_ensure_holiday_list_for_leave(employee, attendance_date)
		_clear_day_for_leave_change(employee, attendance_date, existing)
		return _create_leave_application_for_day(employee, attendance_date, leave_type)

	# Leaving an On Leave day: cancel Leave Application first (restores balance).
	if existing and (
		existing.status == "On Leave"
		or existing.get("leave_application")
		or _get_approved_leave_application(employee, attendance_date)
	):
		_clear_day_for_leave_change(employee, attendance_date, existing)
		existing = None

	amended_from = None
	if existing and existing.docstatus == 1:
		same = existing.status == status and (existing.get("half_day_status") or None) == half_day_status
		if same and status in LOCATION_STATUSES and _has_employment_type_location_field():
			same = (existing.get("custom_employment_type_location") or None) == (
				employment_type_location or None
			)
		if same:
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
	doc.leave_type = None
	doc.leave_application = None
	doc.half_day_status = half_day_status
	_apply_employment_type_location(doc, status, employment_type_location)
	if status == "Half Day":
		_preserve_half_day_status(doc, half_day_status)
	doc.save()
	if submit:
		doc.submit()
	return doc.name


@frappe.whitelist()
def mark_bulk_attendance(
	employees,
	attendance_date,
	status,
	submit=1,
	leave_type=None,
	employment_type_location=None,
	half_day_status=None,
):
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
			mark_attendance(
				employee,
				attendance_date,
				status,
				submit,
				leave_type,
				employment_type_location=employment_type_location,
				half_day_status=half_day_status,
			)
			marked += 1
		except Exception:
			frappe.clear_last_message()
			failed.append(employee)
	return {"marked": marked, "skipped": len(already), "failed": failed}


@frappe.whitelist()
def mark_selected_attendance(
	cells, status, submit=1, leave_type=None, employment_type_location=None, half_day_status=None
):
	"""Mark attendance for specific employee+date cells selected on the sheet."""
	cells = frappe.parse_json(cells) or []
	if not cells:
		frappe.throw(_("Please select at least one day cell."))
	if status not in STATUSES:
		frappe.throw(_("Invalid attendance status {0}").format(status))

	marked, skipped, failed = 0, 0, []
	for cell in cells:
		employee = cell.get("employee")
		attendance_date = cell.get("attendance_date")
		if not employee or not attendance_date:
			continue
		existing = frappe.db.exists(
			"Attendance",
			{"employee": employee, "attendance_date": getdate(attendance_date), "docstatus": ["<", 2]},
		)
		if existing:
			skipped += 1
			continue
		try:
			mark_attendance(
				employee,
				attendance_date,
				status,
				submit,
				leave_type,
				employment_type_location=employment_type_location,
				half_day_status=half_day_status,
			)
			marked += 1
		except Exception:
			frappe.clear_last_message()
			failed.append(f"{employee} @ {attendance_date}")
	return {"marked": marked, "skipped": skipped, "failed": failed}


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
	location_keys = list(LOCATION_OPTIONS)  # Office, Site Location, Base
	totals = dict.fromkeys(all_statuses, 0)
	location_totals = dict.fromkeys(location_keys, 0)
	per_employee = {}
	for r in rows:
		totals[r.status] = totals.get(r.status, 0) + r.count
		emp = per_employee.setdefault(
			r.employee,
			{
				"employee": r.employee,
				"employee_name": r.employee_name,
				**dict.fromkeys(all_statuses, 0),
				**dict.fromkeys(location_keys, 0),
			},
		)
		emp[r.status] = emp.get(r.status, 0) + r.count

	# Present days split by Employment Type Location (P-O / P-S / P-B).
	if _has_employment_type_location_field():
		loc_rows = frappe.get_list(
			"Attendance",
			filters={**filters, "status": "Present"},
			fields=["employee", "custom_employment_type_location", {"COUNT": "*", "as": "count"}],
			group_by="employee, custom_employment_type_location",
			limit_page_length=0,
		)
		for r in loc_rows:
			loc = (r.get("custom_employment_type_location") or "").strip()
			if loc not in location_totals:
				continue
			location_totals[loc] += r.count
			emp = per_employee.get(r.employee)
			if emp is not None:
				emp[loc] = emp.get(loc, 0) + r.count

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
		"location_totals": location_totals,
		"location_keys": location_keys,
		"employees": list(per_employee.values()),
		"days": days,
		"trend": {s: list(v.values()) for s, v in trend.items()},
		"period_days": (to_date - from_date).days + 1,
	}


def add_indexes():
	"""after_migrate: composite index used by the attendance page and dashboard."""
	frappe.db.add_index("Attendance", ["attendance_date", "status"], "attendance_date_status_index")
