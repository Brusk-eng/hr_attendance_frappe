# HR Attendance (hr_customizations)

**A monthly attendance sheet and dashboard for ERPNext / Frappe HRMS.** It lets you mark the daily attendance of a large workforce (100+ workers) from one screen and shows monthly totals automatically.

It suits labour teams who work every day of the month (no weekends, no half days): you open one page, see every worker with the whole month laid out as a grid, and mark *Present / Absent / On Leave* with a click.

> No DocType is modified. The app only adds a page, a few whitelisted API methods and one database index. All attendance is stored as standard HRMS **Attendance** documents.

---

## Features

### Attendance Sheet (`/app/emppage`)
- **Company** filter (defaults to your company) + **Search** by name/ID
- Desktop: monthly grid, **100 per page**, hold-drag multi-select, Bulk / Submit in the page toolbar
- Phone (≤768px): employee cards, **infinite scroll** (25 at a time), tap → day list → mark; sticky bottom bar (Bulk / Submit / New). Drag-paint disabled on phone
- Statuses: Present / Absent / On Leave / Half Day / Work From Home (location Office/Site/Base when TRS field exists)
- **Bulk Mark**: confirms count of unmarked employees matching current filters (not just the visible page)
- Month / year navigation, drafts with dashed border, amend on change

### Attendance Dashboard (`/app/emppage/report`)
- In-page KPIs + donut / bar charts (classic ops view)
- Desk **Attendance** Dashboard (HRMS) wired to Insights **Attendance Analytics** when Insights is installed (soft — Insights not required)

### Connections
- Attendance form: Employee Checkin + internal links (Attendance Request, Leave Application, Employee, Shift Type)
- Employee Connections already include Attendance (verified only; no duplicate override)

### Other
- Desktop Icon **Attendance Page** → `/app/emppage` (HR Manager / HR User / System Manager)
- Sidebar: Shift & Attendance → Attendance Page
- Translations: **Arabic** (`ar`) and **Urdu** (`ur`), RTL supported
- Index `(attendance_date, status)` on migrate
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

Then open `http://<your-site>/app/emppage`, or search for **Attendance Page**.

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
