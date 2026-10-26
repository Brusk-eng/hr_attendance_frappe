// Worker Attendance
//   /desk/emppage         -> monthly attendance sheet (mark attendance per worker / day)
//   /desk/emppage/report  -> attendance dashboard (charts per period / employee)

const API = "hr_customizations.api";
const MARK_STATUSES = ["Present", "Absent", "On Leave", "Half Day", "Work From Home"];
// Work From Home does not require Employment Type Location.
const LOCATION_STATUSES = ["Present", "Half Day"];
const EMPLOYMENT_TYPE_LOCATION_OPTIONS = ["Office", "Site Location", "Base"];
const HALF_DAY_OTHER_OPTIONS = ["Absent", "Present"];
const LOCATION_ABBR = {
	Office: "P-O",
	"Site Location": "P-S",
	Base: "P-B",
};
const STATUS_META = {
	Present: { abbr: "P", cls: "c-present", color: "#16a34a" },
	Absent: { abbr: "A", cls: "c-absent", color: "#dc2626" },
	"On Leave": { abbr: "L", cls: "c-leave", color: "#d97706" },
	"Half Day": { abbr: "HD", cls: "c-half", color: "#2563eb" },
	"Work From Home": { abbr: "WFH", cls: "c-wfh", color: "#7c3aed" },
	Holiday: { abbr: "H", cls: "c-holiday", color: "#6b7280" },
	"Weekly Off": { abbr: "WO", cls: "c-wo", color: "#9ca3af" },
};
const status_color = (s) => STATUS_META[s].color;
const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const abbr = (s) => __(STATUS_META[s]?.abbr || "?", null, "Attendance Abbreviation");
const cell_label = (status, location) => {
	if (status === "Present" && location && LOCATION_ABBR[location]) {
		return LOCATION_ABBR[location];
	}
	return abbr(status);
};
const cell_title = (status, location, is_draft) => {
	let t = __(status);
	if (LOCATION_STATUSES.includes(status) && location) {
		t = `${__(status)} · ${__(location)}`;
	}
	if (is_draft) t += ` (${__("Draft")})`;
	return t;
};

frappe.pages["emppage"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Worker Attendance"),
		single_column: true,
	});
	$(wrapper).addClass("emppage");
	wrapper.emp_page = new EmpAttendancePage(page);
};

frappe.pages["emppage"].on_page_show = function (wrapper) {
	wrapper.emp_page && wrapper.emp_page.route();
};

class EmpAttendancePage {
	constructor(page) {
		this.page = page;
		this.$body = $(page.body);
		this.$tabs = $(`
			<div class="att-tabs">
				<a href="#" data-view="sheet">${frappe.utils.icon("calendar", "sm")} ${__("Attendance Sheet")}</a>
				<a href="#" data-view="report">${frappe.utils.icon("chart", "sm")} ${__("Dashboard")}</a>
			</div>`).appendTo(this.$body);
		this.$tabs.on("click", "a", (e) => {
			e.preventDefault();
			$(e.currentTarget).attr("data-view") === "report"
				? frappe.set_route("emppage", "report")
				: frappe.set_route("emppage");
		});
		this.$sheet = $("<div></div>").appendTo(this.$body);
		this.$report = $("<div></div>").appendTo(this.$body);

		frappe.router.on("change", () => {
			if (frappe.get_route()[0] === "emppage") this.route();
		});
	}

	route() {
		const view = frappe.get_route()[1] === "report" ? "report" : "sheet";
		if (view === this.view) return;
		this.view = view;
		this.$tabs.find("a").removeClass("active").filter(`[data-view="${view}"]`).addClass("active");
		this.page.clear_primary_action();
		this.page.clear_secondary_action();
		this.page.clear_inner_toolbar();
		this.page.add_inner_button(__("New Employee"), () => frappe.new_doc("Employee"));

		if (view === "report") {
			this.page.set_title(__("Attendance Dashboard"));
			this.page.set_secondary_action(__("Refresh"), () => this.report.refresh(true), "refresh");
			this.$sheet.hide();
			this.$report.show();
			if (!this.report) this.report = new AttendanceDashboard(this.$report);
			else this.report.refresh(true);
		} else {
			this.page.set_title(__("Worker Attendance"));
			this.page.set_primary_action(__("Bulk Mark"), () => this.sheet.bulk_dialog(), "users");
			this.page.set_secondary_action(__("Submit Drafts"), () => this.sheet.submit_drafts(), "check");
			this.$report.hide();
			this.$sheet.show();
			if (!this.sheet) this.sheet = new AttendanceSheet(this.$sheet);
			else this.sheet.refresh();
		}
	}
}

function kpi(cls, icon, label, value, sub) {
	return `<div class="att-panel kpi">
		<div class="ico ${cls}">${icon}</div>
		<div><div class="lbl">${label}</div><div class="val">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>
	</div>`;
}

function avatar(name) {
	return frappe.avatar(null, "avatar-small", name, null, false, name);
}

/* ---------------------------------------------------------------- sheet */

class AttendanceSheet {
	constructor($wrapper) {
		this.$wrapper = $wrapper;
		const now = moment(frappe.datetime.get_today());
		this.year = now.year();
		this.month = now.month() + 1;
		this.start = 0;
		this.search = "";
		/** @type {Set<string>} keys: `${employee}::${yyyy-mm-dd}` */
		this.selected = new Set();
		this._painting = false;
		this._paint_on = true;
		this._did_paint = false;
		this._suppress_click = false;
		this._paint_start = null;
		$(document).on("mouseup.emppageSel", () => this.end_paint());
		this.make();
		this.refresh();
	}

	cell_key(employee, date) {
		return `${employee}::${date}`;
	}

	parse_cell_key(key) {
		const i = key.indexOf("::");
		return { employee: key.slice(0, i), attendance_date: key.slice(i + 2) };
	}

	clear_selection() {
		this.selected.clear();
		this.$wrapper.find("td.day.selected").removeClass("selected");
		this.$wrapper.find(".row-check").prop("checked", false).prop("indeterminate", false);
		this.update_selection_bar();
	}

	update_selection_bar() {
		const n = this.selected.size;
		const $bar = this.$wrapper.find(".att-selection-bar");
		if (!$bar.length) return;
		$bar.toggleClass("hidden", n === 0);
		$bar.find(".sel-count").text(__("{0} day(s) selected", [n]));
	}

	selectable_dates_for_employee(emp) {
		const today = frappe.datetime.get_today();
		const days = this.data?.days_in_month || 0;
		const dates = [];
		for (let d = 1; d <= days; d++) {
			const ds = this.date_str(d);
			if (ds > today) continue;
			dates.push(ds);
		}
		return dates;
	}

	find_day_cell(employee, date) {
		return this.$wrapper
			.find("tr")
			.filter((_, el) => el.getAttribute("data-employee") === employee)
			.find(`td.day[data-date="${date}"]`);
	}

	set_cell_selected(employee, date, on) {
		if (!employee || !date || date > frappe.datetime.get_today()) return;
		const key = this.cell_key(employee, date);
		if (on) this.selected.add(key);
		else this.selected.delete(key);
		this.find_day_cell(employee, date).toggleClass("selected", on);
	}

	set_row_selection(employee, checked) {
		const emp = (this.data?.employees || []).find((e) => e.name === employee);
		if (!emp) return;
		this.selectable_dates_for_employee(emp).forEach((ds) => {
			this.set_cell_selected(employee, ds, checked);
		});
		this.update_selection_bar();
	}

	sync_row_checks() {
		(this.data?.employees || []).forEach((emp) => {
			const dates = this.selectable_dates_for_employee(emp);
			const n = dates.filter((ds) => this.selected.has(this.cell_key(emp.name, ds))).length;
			const $cb = this.$wrapper
				.find("tr")
				.filter((_, el) => el.getAttribute("data-employee") === emp.name)
				.find(".row-check");
			$cb.prop("checked", n > 0 && n === dates.length);
			$cb.prop("indeterminate", n > 0 && n < dates.length);
		});
	}

	end_paint() {
		if (!this._painting) return;
		this._painting = false;
		this.$wrapper.removeClass("is-painting");
		if (this._did_paint) {
			this._suppress_click = true;
			this.sync_row_checks();
			this.update_selection_bar();
			// drop suppress if click never fires (mouseup outside cell)
			setTimeout(() => {
				this._suppress_click = false;
			}, 0);
		}
		this._did_paint = false;
		this._paint_start = null;
	}

	paint_cell($td) {
		const employee = $td.closest("tr").attr("data-employee");
		const date = $td.attr("data-date");
		this.set_cell_selected(employee, date, this._paint_on);
	}

	make() {
		this.$wrapper.html(`
			<div class="att-panel att-filters"></div>
			<div class="kpis"></div>
			<div class="att-panel">
				<div class="sheet-head">
					<div class="title"></div>
					<div class="legend">
						${MARK_STATUSES.map((s) => `<span><span class="chip ${STATUS_META[s].cls}">${abbr(s)}</span> ${__(s)}</span>`).join("")}
						<span><span class="chip c-present loc">P-O</span> ${__("Present")} · ${__("Office")}</span>
						<span><span class="chip c-present loc">P-S</span> ${__("Present")} · ${__("Site")}</span>
						<span><span class="chip c-present loc">P-B</span> ${__("Present")} · ${__("Base")}</span>
						<span><span class="chip c-holiday">${abbr("Holiday")}</span> ${__("Holiday")}</span>
						<span><span class="chip c-wo">${abbr("Weekly Off")}</span> ${__("Weekly Off")}</span>
						<span><span class="chip c-present draft">${abbr("Present")}</span> ${__("Draft")}</span>
						<span><span class="chip empty"></span> ${__("Not Marked")}</span>
					</div>
				</div>
				<div class="att-selection-bar hidden">
					<span class="sel-count">0</span>
					<span class="text-muted">${__("Hold & drag across days to select · employee checkbox for whole row")}</span>
					<button type="button" class="btn btn-default btn-sm btn-clear-sel">${__("Clear")}</button>
					<button type="button" class="btn btn-primary btn-sm btn-mark-sel">${__("Mark Selected")}</button>
				</div>
				<div class="att-scroll"></div>
				<div class="att-pager"></div>
			</div>
		`);
		this.$wrapper.find(".btn-clear-sel").on("click", () => this.clear_selection());
		this.$wrapper.find(".btn-mark-sel").on("click", () => this.bulk_dialog({ use_selection: true }));
		const $f = this.$wrapper.find(".att-filters");

		const $nav = $(`<div class="month-nav">
			<button class="btn btn-default btn-sm prev" title="${__("Previous Month")}">${frappe.utils.icon("left", "sm")}</button>
		</div>`).appendTo($f);
		this.month_field = frappe.ui.form.make_control({
			parent: $nav,
			df: {
				fieldtype: "Select",
				label: __("Month"),
				options: moment.months().map((m, i) => ({ label: __(m), value: String(i + 1) })),
				change: () => this.set_period(cint(this.month_field.get_value()), this.year),
			},
			render_input: true,
		});
		const years = [];
		const this_year = moment().year();
		for (let y = this_year - 5; y <= this_year + 1; y++) years.push(String(y));
		this.year_field = frappe.ui.form.make_control({
			parent: $nav,
			df: {
				fieldtype: "Select",
				label: __("Year"),
				options: years,
				change: () => this.set_period(this.month, cint(this.year_field.get_value())),
			},
			render_input: true,
		});
		$(`<button class="btn btn-default btn-sm next" title="${__("Next Month")}">${frappe.utils.icon("right", "sm")}</button>
		   <button class="btn btn-default btn-sm this-month">${__("This Month")}</button>`).appendTo($nav);
		$nav.find(".prev").on("click", () => this.shift_month(-1));
		$nav.find(".next").on("click", () => this.shift_month(1));
		$nav.find(".this-month").on("click", () => {
			const now = moment(frappe.datetime.get_today());
			this.set_period(now.month() + 1, now.year());
		});
		this.month_field.set_value(String(this.month));
		this.year_field.set_value(String(this.year));

		this.search_field = frappe.ui.form.make_control({
			parent: $f,
			df: { fieldtype: "Data", label: __("Search Employee"), placeholder: __("Employee name or ID") },
			render_input: true,
		});
		this.search_field.$input.on(
			"input",
			frappe.utils.debounce(() => {
				const v = (this.search_field.get_value() || "").trim();
				if (v === this.search) return;
				this.search = v;
				this.start = 0;
				this.refresh();
			}, 350)
		);
	}

	shift_month(n) {
		const m = moment([this.year, this.month - 1, 1]).add(n, "months");
		this.set_period(m.month() + 1, m.year());
	}

	set_period(month, year) {
		if (!month || !year || (month === this.month && year === this.year)) return;
		this.month = month;
		this.year = year;
		this.month_field.set_value(String(month));
		if (!this.year_field.df.options.includes(String(year))) {
			this.year_field.df.options.push(String(year));
			this.year_field.refresh();
		}
		this.year_field.set_value(String(year));
		this.start = 0;
		this.refresh();
	}

	refresh() {
		this.clear_selection();
		this.$wrapper.find(".att-scroll").css("opacity", 0.5);
		return frappe
			.call(`${API}.get_monthly_attendance`, {
				year: this.year,
				month: this.month,
				search: this.search,
				start: this.start,
			})
			.then((r) => {
				this.data = r.message;
				this.render();
			})
			.always(() => this.$wrapper.find(".att-scroll").css("opacity", 1));
	}

	date_str(day) {
		return `${this.year}-${String(this.month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
	}

	render() {
		this.render_kpis();
		const { employees, days_in_month, total, page_length, working_days } = this.data;
		const today = frappe.datetime.get_today();
		const $scroll = this.$wrapper.find(".att-scroll");
		this.$wrapper
			.find(".sheet-head .title")
			.text(`${__(moment.months()[this.month - 1])} ${this.year} · ${__("{0} working days", [working_days])}`);

		if (!employees.length) {
			$scroll.html(`<div class="empty-state">${frappe.utils.icon("users", "lg")}<p class="mt-2">${
				this.search ? __("No employee matches {0}", [`<b>${esc(this.search)}</b>`]) : __("No active employees found")
			}</p></div>`);
			this.$wrapper.find(".att-pager").empty();
			return;
		}

		let head = `<th class="col-emp"><span title="${__(
			"Tick employee = select all days in that row"
		)}">${__("Employee")}</span></th>`;
		for (let d = 1; d <= days_in_month; d++) {
			const ds = this.date_str(d);
			const future = ds > today;
			head += `<th class="${ds === today ? "today" : ""}${future ? " future" : ""}" data-date="${ds}" title="${esc(
				frappe.datetime.str_to_user(ds)
			)}">
				<span class="dnum">${d}</span><br><small>${esc(moment(ds).format("dd"))}</small></th>`;
		}
		head += `
			<th class="tot first" title="${__("Total Working Days")}">${__("Days")}</th>
			<th class="tot" style="color:var(--att-present)" title="${__("Present")} + ${__("Work From Home")}">${__("Present")}</th>
			<th class="tot" style="color:var(--att-present)" title="${__("Present")} · ${__("Office")}">P-O</th>
			<th class="tot" style="color:var(--att-present)" title="${__("Present")} · ${__("Site Location")}">P-S</th>
			<th class="tot" style="color:var(--att-present)" title="${__("Present")} · ${__("Base")}">P-B</th>
			<th class="tot" style="color:var(--att-wfh)" title="${__("Work From Home")}">WFH</th>
			<th class="tot" style="color:var(--att-half)" title="${__("Half Day")}">HD</th>
			<th class="tot" style="color:var(--att-absent)">${__("Absent")}</th>
			<th class="tot" style="color:var(--att-leave)">${__("Leave")}</th>
			<th class="tot">${__("Not Marked")}</th>
			<th class="rate">${__("Attendance %")}</th>`;

		const rows = employees
			.map((emp) => {
				let cells = "";
				for (let d = 1; d <= days_in_month; d++) {
					const ds = this.date_str(d);
					const a = emp.attendance[ds];
					const cal = (emp.calendar || {})[ds];
					const future = ds > today;
					const is_sel = this.selected.has(this.cell_key(emp.name, ds));
					const is_off = cal === "Holiday" || cal === "Weekly Off";
					let chip = `<span class="chip empty"></span>`;
					let title = frappe.datetime.str_to_user(ds);
					if (a) {
						const meta = STATUS_META[a.status] || { cls: "c-none" };
						const loc = a.employment_type_location;
						const label = cell_label(a.status, loc);
						const loc_cls = a.status === "Present" && loc ? " loc" : "";
						chip = `<span class="chip ${meta.cls}${loc_cls}${a.docstatus === 0 ? " draft" : ""}">${esc(label)}</span>`;
						title += ` · ${cell_title(a.status, loc, a.docstatus === 0)}`;
					} else if (is_off) {
						const meta = STATUS_META[cal];
						chip = `<span class="chip ${meta.cls}">${esc(meta.abbr)}</span>`;
						title += ` · ${__(cal)}`;
					} else if (!future) {
						title += ` · ${__("Not Marked")}`;
					}
					if (!future && !is_off) title += ` · ${__("Hold & drag to select · click to mark")}`;
					cells += `<td class="day${future ? " future" : ""}${is_off ? " day-off" : ""}${
						ds === today ? " today-col" : ""
					}${is_sel ? " selected" : ""}" data-date="${ds}" title="${esc(title)}">${
						future && !a && !is_off ? "" : chip
					}</td>`;
				}
				const t = emp.totals;
				const rate = t.working_days ? Math.round((t.present * 100) / t.working_days) : 0;
				return `<tr data-employee="${esc(emp.name)}">
					<td class="col-emp"><div class="emp-cell">
						<input type="checkbox" class="row-check" title="${__("Select all days for this employee")}">
						<div class="emp-open" title="${__("Click to mark attendance")}">
						${avatar(emp.employee_name || emp.name)}
						<div><div class="nm">${esc(emp.employee_name || emp.name)}</div>
						<div class="id">${esc(emp.name)}${emp.designation ? " · " + esc(__(emp.designation)) : ""}</div></div>
						</div>
					</div></td>
					${cells}
					<td class="tot first">${t.working_days}</td>
					<td class="tot" style="color:var(--att-present)">${t.present || 0}</td>
					<td class="tot" style="color:var(--att-present)">${t.present_office || 0}</td>
					<td class="tot" style="color:var(--att-present)">${t.present_site || 0}</td>
					<td class="tot" style="color:var(--att-present)">${t.present_base || 0}</td>
					<td class="tot" style="color:var(--att-wfh)">${t.wfh || 0}</td>
					<td class="tot" style="color:var(--att-half)">${t.half_day || 0}</td>
					<td class="tot" style="color:var(--att-absent)">${t.absent}</td>
					<td class="tot" style="color:var(--att-leave)">${t.leave}</td>
					<td class="tot text-muted">${t.unmarked}</td>
					<td class="rate"><b>${rate}%</b><div class="rate-bar"><span style="width:${rate}%"></span></div></td>
				</tr>`;
			})
			.join("");

		$scroll.html(`<table class="att-grid"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`);

		const default_date = today.slice(0, 7) === this.date_str(1).slice(0, 7) ? today : null;
		$scroll.find(".emp-open").on("click", (e) => {
			this.open_dialog($(e.currentTarget).closest("tr").attr("data-employee"), default_date || today);
		});
		$scroll.find(".row-check").on("click", (e) => {
			e.stopPropagation();
			const emp = $(e.currentTarget).closest("tr").attr("data-employee");
			this.set_row_selection(emp, e.currentTarget.checked);
		});
		const $days = $scroll.find("td.day:not(.future)");
		$days.on("mousedown", (e) => {
			if (e.button !== 0) return;
			e.preventDefault();
			const $td = $(e.currentTarget);
			const emp = $td.closest("tr").attr("data-employee");
			const date = $td.attr("data-date");
			this._painting = true;
			this._did_paint = false;
			this._paint_start = { employee: emp, date, $td };
			this._paint_on = !this.selected.has(this.cell_key(emp, date));
			this.$wrapper.addClass("is-painting");
		});
		$days.on("mouseenter", (e) => {
			if (!this._painting) return;
			const $td = $(e.currentTarget);
			if (!this._did_paint && this._paint_start) {
				this._did_paint = true;
				this.paint_cell(this._paint_start.$td);
			}
			this._did_paint = true;
			this.paint_cell($td);
		});
		$days.on("click", (e) => {
			if (this._suppress_click) {
				e.preventDefault();
				e.stopImmediatePropagation();
				this._suppress_click = false;
				return;
			}
			const $td = $(e.currentTarget);
			this.open_dialog($td.closest("tr").attr("data-employee"), $td.attr("data-date"));
		});

		this.sync_row_checks();
		this.update_selection_bar();

		// scroll today's column into view
		const $today = $scroll.find("th.today");
		if ($today.length) {
			const left = $today[0].offsetLeft - $scroll.width() / 2;
			$scroll.scrollLeft(left > 0 ? left : 0);
		}

		this.render_pager(this.start + 1, this.start + employees.length, total, page_length);
	}

	render_kpis() {
		const { day_counts = {}, day_location_counts = {}, total, focus_date } = this.data;
		const c = (s) => day_counts[s] || 0;
		const loc = (k) => day_location_counts[k] || 0;
		const marked = Object.values(day_counts).reduce((a, b) => a + b, 0);
		const is_today = focus_date === frappe.datetime.get_today();
		const day_lbl = is_today ? __("Today") : frappe.datetime.str_to_user(focus_date);
		const pct = (n) => (total ? Math.round((n * 100) / total) + "% " + __("of workers") : "");
		const present_total = c("Present") + c("Work From Home");
		this.$wrapper.find(".kpis").html(
			kpi("c-total", frappe.utils.icon("users", "md"), __("Total Workers"), total, day_lbl) +
				kpi("c-present", abbr("Present"), `${__("Present")} · ${day_lbl}`, present_total, pct(present_total)) +
				kpi("c-present", "P-O", `P-O · ${day_lbl}`, loc("Office"), __("Office")) +
				kpi("c-present", "P-S", `P-S · ${day_lbl}`, loc("Site Location"), __("Site Location")) +
				kpi("c-present", "P-B", `P-B · ${day_lbl}`, loc("Base"), __("Base")) +
				kpi("c-wfh", "WFH", `WFH · ${day_lbl}`, c("Work From Home"), pct(c("Work From Home"))) +
				kpi("c-half", "HD", `HD · ${day_lbl}`, c("Half Day"), pct(c("Half Day"))) +
				kpi("c-absent", abbr("Absent"), `${__("Absent")} · ${day_lbl}`, c("Absent"), pct(c("Absent"))) +
				kpi("c-leave", abbr("On Leave"), `${__("On Leave")} · ${day_lbl}`, c("On Leave"), pct(c("On Leave"))) +
				kpi("c-none", "?", `${__("Not Marked")} · ${day_lbl}`, Math.max(total - marked, 0), pct(Math.max(total - marked, 0)))
		);
	}

	render_pager(from, to, total, page_length) {
		const $p = this.$wrapper.find(".att-pager");
		const pages = Math.ceil(total / page_length);
		const current = Math.floor(this.start / page_length) + 1;
		$p.html(`
			<div>${__("Showing {0} - {1} of {2} employees", [from, to, total])}</div>
			<div class="d-flex align-items-center" style="gap:8px">
				<span>${__("Page {0} of {1}", [current, pages])}</span>
				<div class="btn-group">
					<button class="btn btn-default btn-sm btn-prev" ${current === 1 ? "disabled" : ""}>${__("Previous")}</button>
					<button class="btn btn-default btn-sm btn-next" ${current >= pages ? "disabled" : ""}>${__("Next")}</button>
				</div>
			</div>
		`);
		$p.find(".btn-prev").on("click", () => {
			this.start = Math.max(this.start - page_length, 0);
			this.refresh();
		});
		$p.find(".btn-next").on("click", () => {
			this.start += page_length;
			this.refresh();
		});
	}

	open_dialog(employee, date) {
		const emp = this.data.employees.find((e) => e.name === employee) || { name: employee, attendance: {} };
		const today = frappe.datetime.get_today();
		let status = "Present";
		let half_day_status = "Absent";

		const d = new frappe.ui.Dialog({
			title: __("Mark Attendance"),
			fields: [
				{ fieldname: "emp_html", fieldtype: "HTML" },
				{
					fieldname: "attendance_date",
					fieldtype: "Date",
					label: __("Date"),
					reqd: 1,
					default: date || today,
					max_date: frappe.datetime.str_to_obj(today),
					change: () => show_existing(),
				},
				{ fieldname: "status_html", fieldtype: "HTML", label: __("Status") },
				{
					fieldname: "employment_type_location",
					fieldtype: "Select",
					label: __("Employment Type Location"),
					options: EMPLOYMENT_TYPE_LOCATION_OPTIONS,
					default: "Base",
					description: __(
						"Required for Present and Half Day. Used for Salary Slip day calculation when TRS is installed."
					),
					hidden: 0,
				},
				{ fieldname: "half_day_html", fieldtype: "HTML" },
				{
					fieldname: "leave_type",
					fieldtype: "Link",
					label: __("Leave Type"),
					options: "Leave Type",
					hidden: 1,
				},
				{ fieldname: "existing_html", fieldtype: "HTML" },
			],
			primary_action_label: __("Submit Attendance"),
			primary_action: (values) => save(values, 1),
			secondary_action_label: __("Save as Draft"),
			secondary_action: () => {
				const values = d.get_values();
				if (values) save(values, 0);
			},
		});

		d.$wrapper.addClass("att-dialog");
		d.fields_dict.emp_html.$wrapper.html(`<div class="att-emp-head">
			${frappe.avatar(null, "avatar-medium", emp.employee_name || emp.name, null, false, emp.employee_name || emp.name)}
			<div><div class="nm">${esc(emp.employee_name || emp.name)}</div>
			<div class="id">${esc(emp.name)}${emp.designation ? " · " + esc(__(emp.designation)) : ""}</div></div>
		</div>`);

		const $picker = $(`<div>
			<label class="control-label reqd">${__("Status")}</label>
			<div class="att-status-picker">
				${MARK_STATUSES.map(
					(s) => `<button type="button" data-status="${s}"><span class="ic">${abbr(s)}</span>${__(s)}</button>`
				).join("")}
			</div></div>`).appendTo(d.fields_dict.status_html.$wrapper);

		const $half = $(`<div class="att-half-wrap" style="display:none">
			<label class="control-label reqd">${__("Status for Other Half")}</label>
			<div class="att-status-picker att-half-picker">
				${HALF_DAY_OTHER_OPTIONS.map(
					(s) =>
						`<button type="button" data-half="${s}"><span class="ic">${abbr(s)}</span>${__(s)}</button>`
				).join("")}
			</div>
			<div class="help-box small text-muted">${__(
				"What the other half of the day counts as when status is Half Day."
			)}</div>
		</div>`).appendTo(d.fields_dict.half_day_html.$wrapper);

		const set_half_day_status = (s) => {
			half_day_status = HALF_DAY_OTHER_OPTIONS.includes(s) ? s : "Absent";
			$half
				.find("button")
				.removeClass("active")
				.filter(`[data-half="${half_day_status}"]`)
				.addClass("active");
		};
		$half.on("click", "button", (e) => set_half_day_status($(e.currentTarget).attr("data-half")));
		set_half_day_status("Absent");

		const set_status = (s) => {
			status = s;
			$picker.find("button").removeClass("active").filter(`[data-status="${s}"]`).addClass("active");
			d.set_df_property("leave_type", "hidden", s !== "On Leave");
			d.set_df_property("leave_type", "reqd", s === "On Leave");
			if (s !== "On Leave") {
				d.set_value("leave_type", "");
			}
			const needs_location = LOCATION_STATUSES.includes(s);
			d.set_df_property("employment_type_location", "hidden", needs_location ? 0 : 1);
			d.set_df_property("employment_type_location", "reqd", needs_location ? 1 : 0);
			$half.toggle(s === "Half Day");
			if (s === "Half Day" && !HALF_DAY_OTHER_OPTIONS.includes(half_day_status)) {
				set_half_day_status("Absent");
			}
			if (!needs_location) {
				d.set_value("employment_type_location", "");
			} else if (!d.get_value("employment_type_location")) {
				d.set_value("employment_type_location", "Base");
			}
		};
		$picker.on("click", "button", (e) => set_status($(e.currentTarget).attr("data-status")));

		const show_existing = () => {
			const ds = d.get_value("attendance_date");
			const a = ds && emp.attendance[ds];
			set_status(a && MARK_STATUSES.includes(a.status) ? a.status : "Present");
			if (a?.employment_type_location) {
				d.set_value("employment_type_location", a.employment_type_location);
			}
			if (a?.status === "Half Day") {
				set_half_day_status(a.half_day_status || "Absent");
			}
			d.set_value("leave_type", a?.status === "On Leave" && a.leave_type ? a.leave_type : "");
			const loc_txt =
				a && LOCATION_STATUSES.includes(a.status) && a.employment_type_location
					? ` · ${__(a.employment_type_location)}`
					: "";
			const half_txt =
				a?.status === "Half Day" && a.half_day_status
					? ` · ${__("Other half")}: ${__(a.half_day_status)}`
					: "";
			const leave_txt =
				a?.status === "On Leave" && a.leave_type ? ` · ${esc(a.leave_type)}` : "";
			d.fields_dict.existing_html.$wrapper.html(
				a
					? `<div class="att-existing">${frappe.utils.icon("info", "sm")}
						${__("Already marked as {0}", [`<b>${__(a.status)}${esc(loc_txt)}${esc(half_txt)}${leave_txt}</b>`])}
						(${a.docstatus === 0 ? __("Draft") : __("Submitted")}) ·
						<a href="${frappe.utils.get_form_link("Attendance", a.name)}" target="_blank">${esc(a.name)}</a>
						${a.docstatus === 1 ? `<br>${__("Choosing a different status will cancel and amend it.")}` : ""}</div>`
					: ""
			);
		};

		const save = (values, submit) => {
			if (values.attendance_date > today) {
				frappe.msgprint(__("Attendance can not be marked for future dates"));
				return;
			}
			if (LOCATION_STATUSES.includes(status) && !values.employment_type_location) {
				frappe.msgprint({
					title: __("Employment Type Location Required"),
					indicator: "red",
					message: __(
						"Employment Type Location is required for Present and Half Day. Please select Office, Site Location, or Base."
					),
				});
				return;
			}
			if (status === "On Leave" && !values.leave_type) {
				frappe.msgprint({
					title: __("Leave Type Required"),
					indicator: "red",
					message: __("Please select a Leave Type (for example Annual Leave)."),
				});
				return;
			}
			if (status === "Half Day" && !HALF_DAY_OTHER_OPTIONS.includes(half_day_status)) {
				frappe.msgprint(__("Please select Status for Other Half."));
				return;
			}
			frappe
				.call({
					method: `${API}.mark_attendance`,
					args: {
						employee,
						attendance_date: values.attendance_date,
						status,
						leave_type: values.leave_type,
						employment_type_location: values.employment_type_location || null,
						half_day_status: status === "Half Day" ? half_day_status : null,
						submit,
					},
					freeze: true,
				})
				.then(() => {
					d.hide();
					frappe.show_alert({
						message: submit ? __("Attendance submitted") : __("Attendance saved as draft"),
						indicator: "green",
					});
					this.refresh();
				});
		};

		d.show();
		show_existing();
		// keyboard shortcuts: P / A / L / H / W
		d.$wrapper.on("keydown", (e) => {
			if ($(e.target).is("input, textarea")) return;
			const map = {
				p: "Present",
				a: "Absent",
				l: "On Leave",
				h: "Half Day",
				w: "Work From Home",
			};
			if (map[e.key?.toLowerCase()]) set_status(map[e.key.toLowerCase()]);
		});
	}

	bulk_dialog(opts = {}) {
		const use_selection = opts.use_selection || this.selected.size > 0;
		const employees = (this.data?.employees || []).map((e) => e.name);
		if (!use_selection && !employees.length) return;
		if (use_selection && !this.selected.size) {
			frappe.msgprint(
				__("Hold & drag across days (or use the employee checkbox), then Mark Selected.")
			);
			return;
		}
		const today = frappe.datetime.get_today();
		const selected_cells = [...this.selected].map((k) => this.parse_cell_key(k));
		const fields = [
			{
				fieldtype: "HTML",
				options: use_selection
					? `<div class="att-existing">${__(
							"Will mark {0} selected employee-day cell(s). Already marked cells are skipped.",
							[selected_cells.length]
					  )}</div>`
					: `<div class="att-existing">${__(
							"Marks every employee shown on this page ({0}) who is not yet marked on the selected date. Already marked employees are skipped. Tip: hold & drag on the sheet to select cells for multi-day bulk mark.",
							[employees.length]
					  )}</div>`,
			},
		];
		if (!use_selection) {
			fields.push({
				fieldname: "attendance_date",
				fieldtype: "Date",
				label: __("Date"),
				reqd: 1,
				default: today,
				max_date: frappe.datetime.str_to_obj(today),
			});
		}
		fields.push(
			{
				fieldname: "status",
				fieldtype: "Select",
				label: __("Status"),
				reqd: 1,
				options: MARK_STATUSES.map((s) => ({ label: __(s), value: s })),
				default: "Present",
			},
			{
				fieldname: "employment_type_location",
				fieldtype: "Select",
				label: __("Employment Type Location"),
				options: EMPLOYMENT_TYPE_LOCATION_OPTIONS,
				default: "Base",
				depends_on: "eval:['Present','Half Day'].includes(doc.status)",
				mandatory_depends_on: "eval:['Present','Half Day'].includes(doc.status)",
				description: __(
					"Required for Present and Half Day (not Work From Home). Used for Salary Slip day calculation when TRS is installed."
				),
			},
			{
				fieldname: "half_day_status",
				fieldtype: "Select",
				label: __("Status for Other Half"),
				options: HALF_DAY_OTHER_OPTIONS,
				default: "Absent",
				depends_on: "eval:doc.status=='Half Day'",
				mandatory_depends_on: "eval:doc.status=='Half Day'",
				description: __("What the other half of the day counts as when status is Half Day."),
			},
			{
				fieldname: "leave_type",
				fieldtype: "Link",
				label: __("Leave Type"),
				options: "Leave Type",
				depends_on: "eval:doc.status=='On Leave'",
				mandatory_depends_on: "eval:doc.status=='On Leave'",
			},
			{ fieldname: "submit", fieldtype: "Check", label: __("Submit Immediately"), default: 1 }
		);

		const d = new frappe.ui.Dialog({
			title: __("Bulk Mark Attendance"),
			fields,
			primary_action_label: __("Mark Attendance"),
			primary_action: (v) => {
				if (v.status === "On Leave" && !v.leave_type) {
					frappe.msgprint({
						title: __("Leave Type Required"),
						indicator: "red",
						message: __("Please select a Leave Type (for example Annual Leave)."),
					});
					return;
				}
				const finish = (r) => {
					d.hide();
					const { marked, skipped, failed } = r.message;
					frappe.msgprint({
						title: __("Bulk Mark Attendance"),
						indicator: failed.length ? "orange" : "green",
						message:
							__("{0} marked, {1} already marked (skipped).", [marked, skipped]) +
							(failed.length ? `<br>${__("Failed")}: ${failed.map(esc).join(", ")}` : ""),
					});
					this.refresh();
				};
				if (use_selection) {
					frappe
						.call({
							method: `${API}.mark_selected_attendance`,
							args: {
								cells: selected_cells,
								status: v.status,
								leave_type: v.leave_type,
								employment_type_location: v.employment_type_location || null,
								half_day_status: v.status === "Half Day" ? v.half_day_status : null,
								submit: v.submit,
							},
							freeze: true,
							freeze_message: __("Marking attendance..."),
						})
						.then(finish);
					return;
				}
				if (v.attendance_date > today) {
					frappe.msgprint(__("Attendance can not be marked for future dates"));
					return;
				}
				frappe
					.call({
						method: `${API}.mark_bulk_attendance`,
						args: {
							employees,
							attendance_date: v.attendance_date,
							status: v.status,
							leave_type: v.leave_type,
							employment_type_location: v.employment_type_location || null,
							half_day_status: v.status === "Half Day" ? v.half_day_status : null,
							submit: v.submit,
						},
						freeze: true,
						freeze_message: __("Marking attendance..."),
					})
					.then(finish);
			},
		});
		d.show();
	}

	submit_drafts() {
		const names = [];
		(this.data?.employees || []).forEach((e) =>
			Object.values(e.attendance).forEach((a) => a.docstatus === 0 && names.push(a.name))
		);
		if (!names.length) {
			frappe.msgprint(__("There are no draft attendance records on this page."));
			return;
		}
		frappe.confirm(__("Submit {0} draft attendance record(s)?", [names.length]), () => {
			frappe
				.call({ method: `${API}.submit_attendance`, args: { names }, freeze: true })
				.then((r) => {
					frappe.show_alert({ message: __("{0} submitted", [r.message]), indicator: "green" });
					this.refresh();
				});
		});
	}
}

/* ------------------------------------------------------------ dashboard */

class AttendanceDashboard {
	constructor($wrapper) {
		this.$wrapper = $wrapper;
		this.make();
		this.refresh();
	}

	make() {
		this.$wrapper.html(`
			<div class="att-panel att-filters"></div>
			<div class="kpis"></div>
			<div class="dash-charts">
				<div class="att-panel dash-box">
					<h6>${__("Status Distribution")}</h6><div class="hint">${__("Share of each attendance status in the period")}</div>
					<div class="chart-pie"></div><div class="dash-caption caption-pie"></div>
				</div>
				<div class="att-panel dash-box">
					<h6 class="bar-title"></h6><div class="hint bar-hint"></div>
					<div class="chart-bar"></div><div class="dash-caption caption-bar"></div>
				</div>
			</div>
			<div class="att-panel">
				<div class="sheet-head"><div class="title">${__("Attendance per Employee")}</div></div>
				<div class="dash-emp-table" style="overflow:auto"></div>
			</div>
		`);
		const $f = this.$wrapper.find(".att-filters");
		const today = frappe.datetime.get_today();
		const mk = (df) => {
			const c = frappe.ui.form.make_control({ parent: $f, df, render_input: true });
			if (df.default) c.set_value(df.default);
			return c;
		};
		const on_change = () => this.refresh();

		this.from_field = mk({
			fieldtype: "Date",
			label: __("From Date"),
			default: frappe.datetime.month_start(),
			change: on_change,
		});
		this.to_field = mk({ fieldtype: "Date", label: __("To Date"), default: today, change: on_change });
		this.mode_field = mk({
			fieldtype: "Select",
			label: __("Employees"),
			options: [
				{ label: __("All Employees"), value: "all" },
				{ label: __("One Employee"), value: "one" },
			],
			default: "all",
			change: () => {
				this.employee_field.$wrapper.toggle(this.mode_field.get_value() === "one");
				this.refresh();
			},
		});
		this.employee_field = mk({
			fieldtype: "Link",
			label: __("Employee"),
			options: "Employee",
			get_query: () => ({ filters: { status: "Active" } }),
			change: on_change,
		});
		this.employee_field.$wrapper.hide();

		$('<div class="spacer"></div>').appendTo($f);
		const $presets = $(`<div class="btn-group">
			<button class="btn btn-default btn-sm" data-p="this">${__("This Month")}</button>
			<button class="btn btn-default btn-sm" data-p="last">${__("Last Month")}</button>
			<button class="btn btn-default btn-sm" data-p="30">${__("Last 30 Days")}</button>
		</div>`).appendTo($f);
		$presets.on("click", "button", (e) => {
			const p = $(e.currentTarget).attr("data-p");
			let from, to;
			if (p === "this") [from, to] = [frappe.datetime.month_start(), today];
			else if (p === "last") {
				const m = moment(today).subtract(1, "month");
				[from, to] = [m.startOf("month").format("YYYY-MM-DD"), m.endOf("month").format("YYYY-MM-DD")];
			} else [from, to] = [frappe.datetime.add_days(today, -29), today];
			this.silent = true;
			Promise.all([this.from_field.set_value(from), this.to_field.set_value(to)]).then(() => {
				this.silent = false;
				this.refresh();
			});
		});
	}

	get_filters() {
		return {
			from_date: this.from_field.get_value(),
			to_date: this.to_field.get_value(),
			employee: this.mode_field.get_value() === "one" ? this.employee_field.get_value() : null,
		};
	}

	refresh(force) {
		if (this.silent) return;
		const f = this.get_filters();
		if (!f.from_date || !f.to_date) return;
		if (this.mode_field.get_value() === "one" && !f.employee) {
			this.show_empty(__("Select an employee to see their attendance"));
			return;
		}
		const key = JSON.stringify(f);
		if (!force && key === this.last_key) return;
		this.last_key = key;
		frappe.call(`${API}.get_attendance_summary`, f).then((r) => {
			this.data = r.message;
			this.render();
		});
	}

	destroy_charts() {
		(this.charts || []).forEach((c) => c.destroy && c.destroy());
		this.charts = [];
	}

	show_empty(msg) {
		this.destroy_charts();
		this.$wrapper.find(".kpis").empty();
		this.$wrapper.find(".chart-pie").html(`<div class="empty-state">${esc(msg)}</div>`);
		this.$wrapper.find(".chart-bar, .caption-pie, .caption-bar, .bar-hint, .dash-emp-table").empty();
		this.$wrapper.find(".bar-title").text(__("Attendance"));
	}

	render() {
		const {
			statuses,
			totals,
			location_totals = {},
			location_keys = EMPLOYMENT_TYPE_LOCATION_OPTIONS,
			employees,
			days,
			trend,
			period_days,
		} = this.data;
		const f = this.get_filters();
		const grand = statuses.reduce((s, k) => s + (totals[k] || 0), 0);
		const pct = (n) => (grand ? ((n * 100) / grand).toFixed(1) + "%" : "0%");
		const shown = statuses.filter((s) => totals[s] || MARK_STATUSES.includes(s));
		const present = (totals["Present"] || 0) + (totals["Work From Home"] || 0);
		const loc_kpis = location_keys
			.map((loc) => {
				const n = location_totals[loc] || 0;
				const chip = LOCATION_ABBR[loc] || loc;
				return kpi("c-present", chip, chip, n, __(loc));
			})
			.join("");

		this.$wrapper.find(".kpis").html(
			kpi(
				"c-total",
				frappe.utils.icon("calendar", "md"),
				__("Days in Period"),
				period_days,
				f.employee ? esc(employees[0]?.employee_name || f.employee) : __("{0} employee(s)", [employees.length])
			) +
				shown
					.map((s) => kpi(STATUS_META[s].cls, abbr(s), __(s), totals[s] || 0, pct(totals[s] || 0)))
					.join("") +
				loc_kpis +
				kpi("c-present", "%", __("Attendance Rate"), pct(present), __("Total records: {0}", [grand]))
		);

		if (!grand) {
			this.show_empty(__("No submitted attendance in this period"));
			return;
		}

		this.destroy_charts();
		const colors = shown.map((s) => status_color(s));
		const $pie = this.$wrapper.find(".chart-pie").empty();
		const $bar = this.$wrapper.find(".chart-bar").empty();
		// Charts are created last (next frame), after all surrounding DOM is in place:
		// a layout shift during a chart's first draw makes frappe-charts lose its svg.
		const specs = [];

		specs.push([$pie[0], {
			type: "donut",
			height: 280,
			colors,
			data: { labels: shown.map((s) => __(s)), datasets: [{ values: shown.map((s) => totals[s] || 0) }] },
		}]);
		this.$wrapper
			.find(".caption-pie")
			.html(
				shown
					.map(
						(s) =>
							`<span><span class="dot" style="background:${status_color(s)}"></span>${__(s)}: <b>${totals[s] || 0}</b> (${pct(totals[s] || 0)})</span>`
					)
					.join("")
			);

		if (!f.employee && employees.length > 1) {
			const top = employees.slice(0, 40);
			this.$wrapper.find(".bar-title").text(__("Attendance by Employee"));
			this.$wrapper
				.find(".bar-hint")
				.text(
					__("Number of days per status for each employee") +
						(employees.length > 40 ? ` · ${__("first {0} shown, see the table below for all", [40])}` : "")
				);
			specs.push([$bar[0], {
				type: "bar",
				height: 280,
				colors,
				barOptions: { stacked: 1, spaceRatio: 0.4 },
				axisOptions: { xIsSeries: 0, xAxisMode: "tick" },
				data: {
					labels: top.map((e) => e.employee_name || e.employee),
					datasets: shown.map((s) => ({ name: __(s), values: top.map((e) => e[s] || 0) })),
				},
			}]);
		} else {
			this.$wrapper.find(".bar-title").text(__("Daily Attendance"));
			this.$wrapper.find(".bar-hint").text(__("Status recorded on each day of the period"));
			specs.push([$bar[0], {
				type: "bar",
				height: 280,
				colors,
				barOptions: { stacked: 1, spaceRatio: 0.3 },
				axisOptions: { xIsSeries: 1, xAxisMode: "tick" },
				data: {
					labels: days.map((d) => frappe.datetime.str_to_user(d)),
					datasets: shown.map((s) => ({ name: __(s), values: trend[s] })),
				},
			}]);
		}
		this.$wrapper
			.find(".caption-bar")
			.html(
				`<span>${__("Total records")}: <b>${grand}</b></span>` +
					`<span>${__("Attendance Rate")}: <b>${pct(present)}</b></span>` +
					shown.map((s) => `<span>${__(s)}: <b>${totals[s] || 0}</b></span>`).join("") +
					location_keys
						.map(
							(loc) =>
								`<span>${LOCATION_ABBR[loc] || __(loc)}: <b>${location_totals[loc] || 0}</b></span>`
						)
						.join("")
			);

		const sorted = [...employees].sort((a, b) => (b["Present"] || 0) - (a["Present"] || 0));
		this.$wrapper.find(".dash-emp-table").html(`
			<table class="dash-table">
				<thead><tr>
					<th>${__("Employee")}</th>
					${shown.map((s) => `<th class="n">${__(s)}</th>`).join("")}
					${location_keys
						.map((loc) => `<th class="n" title="${esc(__(loc))}">${esc(LOCATION_ABBR[loc] || loc)}</th>`)
						.join("")}
					<th class="n">${__("Total")}</th><th class="n">${__("Attendance %")}</th>
				</tr></thead>
				<tbody>${sorted
					.map((e) => {
						const tot = shown.reduce((s, k) => s + (e[k] || 0), 0);
						const rate = tot ? Math.round((((e["Present"] || 0) + (e["Work From Home"] || 0)) * 100) / tot) : 0;
						return `<tr>
							<td><div class="d-flex align-items-center" style="gap:8px">${avatar(e.employee_name || e.employee)}
								<div><a href="${frappe.utils.get_form_link("Employee", e.employee)}">${esc(e.employee_name || e.employee)}</a>
								<div class="text-muted small">${esc(e.employee)}</div></div></div></td>
							${shown.map((s) => `<td class="n"><span class="pill ${e[s] ? STATUS_META[s].cls : "c-none"}">${e[s] || 0}</span></td>`).join("")}
							${location_keys
								.map(
									(loc) =>
										`<td class="n"><span class="pill ${
											e[loc] ? "c-present" : "c-none"
										}">${e[loc] || 0}</span></td>`
								)
								.join("")}
							<td class="n"><b>${tot}</b></td>
							<td class="n"><b>${rate}%</b></td>
						</tr>`;
					})
					.join("")}</tbody>
			</table>`);

		requestAnimationFrame(() => {
			this.destroy_charts();
			specs.forEach(([el, opts]) => {
				if (el.isConnected) this.charts.push(new frappe.Chart(el, opts));
			});
		});
	}
}
