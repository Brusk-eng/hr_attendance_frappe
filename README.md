# HR Attendance (hr_customizations)

**A monthly attendance sheet and dashboard for ERPNext / Frappe HRMS.** It lets you mark the daily attendance of a large workforce (100+ workers) from one screen and shows monthly totals automatically.

It suits labour teams who work every day of the month (no weekends, no half days): you open one page, see every worker with the whole month laid out as a grid, and mark *Present / Absent / On Leave* with a click.

> No DocType is modified. The app only adds a page, a few whitelisted API methods and one database index. All attendance is stored as standard HRMS **Attendance** documents.

---

## Features

### Attendance Sheet (`/desk/emppage`)
- Every active employee on one screen, **100 per page** with pagination
- **Search** by employee name or ID (results update as you type)
- Monthly grid: one cell per day, colour coded **P** (Present), **A** (Absent), **L** (On Leave). Drafts show with a dashed border
- Totals per worker: working days, present, absent, leave, not marked, attendance %
  - Every calendar day is a working day (no weekends), counted from the employee's joining date and up to today
- Summary cards for today: total workers, present, absent, on leave, not marked
- **Click a worker or a day cell** to open the *Mark Attendance* dialog:
  - Date (today by default, future dates blocked)
  - Status: Present / Absent / On Leave (*Half Day* and *Work From Home* are deliberately hidden)
  - Leave Type for *On Leave* (default *Leave Without Pay*)
  - **Submit Attendance** (create + submit) or **Save as Draft**
  - Changing an already-submitted day cancels it and creates an amended record automatically
- **Bulk Mark**: mark every not-yet-marked worker on the page in one go
- **Submit Drafts**: submit all drafts on the page
- **New Employee** shortcut
- Month / year selector with previous / next / this-month navigation

### Attendance Dashboard (`/desk/emppage/report`)
- Filters: **From Date**, **To Date**, and **All Employees** or **One Employee** (Employee link field)
- Quick ranges: This Month, Last Month, Last 30 Days
- KPI cards: days in period, Present, Absent, On Leave, attendance rate
- **Donut chart** of the status distribution, with exact numbers and percentages written underneath
- **Stacked bar chart**: per employee (all employees) or per day (one employee)
- Per-employee table with the count for each status, total and attendance %

### Other
- Translations: **Arabic** (`ar`) and **Urdu** (`ur`), with RTL layout supported
- Searchable from the desk search bar: type **"Attendance Page"**
- Adds a composite index `(attendance_date, status)` on `tabAttendance` on every migrate (`after_migrate` hook) to speed up the dashboard queries
- Access: HR Manager, HR User, System Manager

---

## Requirements

| | Version |
|---|---|
| Frappe | v16 |
| ERPNext | v16 |
| HRMS | v16 (**required**) |

## Installation

```bash
cd ~/frappe-bench                      # your bench folder
bench get-app https://github.com/Marwan-badr543/HR_attendance_frappe.git
bench --site your-site-name install-app hr_customizations
bench --site your-site-name migrate
bench build --app hr_customizations
bench restart                          # or restart `bench start` in development
```

Then open `http://<your-site>/desk/emppage`, or search for **Attendance Page**.

## Update

```bash
cd ~/frappe-bench
cd apps/hr_customizations && git pull && cd ../..
bench --site your-site-name migrate
bench build --app hr_customizations
```

## Uninstall

```bash
bench --site your-site-name uninstall-app hr_customizations
bench remove-app hr_customizations
```

## Project structure

```
hr_customizations/
├── api.py                                   # whitelisted API: monthly sheet, mark / bulk mark / submit, dashboard summary, index hook
├── hooks.py                                 # after_migrate -> add_indexes, required_apps = ["hrms"]
├── locale/ar.po, locale/ur.po               # Arabic & Urdu translations
└── hr_customizations/page/emppage/          # the desk page (sheet + dashboard)
    ├── emppage.json
    ├── emppage.js
    └── emppage.css
```

### API (`hr_customizations.api`)
| Method | Purpose |
|---|---|
| `get_monthly_attendance(year, month, search, start)` | 100 employees + their attendance and totals for a month |
| `mark_attendance(employee, attendance_date, status, submit, leave_type)` | Create / update / amend one day |
| `mark_bulk_attendance(employees, attendance_date, status, submit, leave_type)` | Mark many unmarked employees |
| `submit_attendance(names)` | Submit draft Attendance records |
| `get_attendance_summary(from_date, to_date, employee)` | Status totals, per-employee counts and daily trend |

## License

MIT
