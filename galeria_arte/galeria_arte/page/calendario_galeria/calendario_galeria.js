// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Calendario de salas: exposiciones, cenas, subastas y alquileres.
// Usa FullCalendar v3, que ya viene con Frappe.

frappe.pages["calendario-galeria"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Calendario"), single_column: true });
	frappe.require(
		[
			"assets/frappe/js/lib/fullcalendar/fullcalendar.min.css",
			"assets/frappe/js/lib/fullcalendar/fullcalendar.min.js",
			"assets/frappe/js/lib/fullcalendar/locale-all.js",
		],
		() => (wrapper.calendario = new CalendarioGaleria(page))
	);
};

frappe.pages["calendario-galeria"].on_page_show = function (wrapper) {
	if (wrapper.calendario && wrapper.calendario.visto) wrapper.calendario.refrescar();
	if (wrapper.calendario) wrapper.calendario.visto = true;
};

class CalendarioGaleria {
	constructor(page) {
		this.page = page;
		const cambio = () => this.refrescar();
		this.f = {
			sala: page.add_field({ fieldname: "sala", label: __("Sala"), fieldtype: "Link", options: "Sala", change: cambio }),
			tipo: page.add_field({
				fieldname: "tipo",
				label: __("Tipo"),
				fieldtype: "Select",
				options: ["", "Exposición", "Cena", "Subasta", "Alquiler"],
				change: cambio,
			}),
			inactivos: page.add_field({
				fieldname: "inactivos",
				label: __("Ver cancelados y vencidos"),
				fieldtype: "Check",
				change: cambio,
			}),
		};
		page.set_primary_action(__("Nuevo evento"), () => galeria.eventos.nuevo({}, cambio), "add");
		page.set_secondary_action(__("Actualizar"), cambio, "refresh");
		page.add_menu_item(__("Lista de eventos"), () => frappe.set_route("List", "Evento"));
		page.add_menu_item(__("Salas"), () => frappe.set_route("List", "Sala"));

		const col = galeria.eventos.COLORES;
		$(`<div class="cal-gal-leyenda">
			${Object.keys(col).map((t) => `<span><span class="muestra" style="background:${col[t]}"></span>${__(t)}</span>`).join("")}
			<span><span class="muestra tentativo"></span>${__("Alquiler tentativo (sin anticipo)")}</span>
			<span>${__("Las exposiciones no ocupan la sala")}</span>
		</div>`).appendTo(page.main);
		this.$cal = $(`<div class="cal-gal"></div>`).appendTo(page.main);
		this.armar();
	}

	armar() {
		const movil = window.matchMedia("(max-width: 767px)").matches;
		this.$cal.fullCalendar({
			locale: "es",
			header: movil
				? { left: "prev,next today", center: "title", right: "listMonth,month" }
				: { left: "prev,next today", center: "title", right: "month,agendaWeek,agendaDay,listMonth" },
			defaultView: movil ? "listMonth" : "month",
			// Flechas como texto: la fuente de íconos de FullCalendar no carga en Frappe.
			buttonIcons: false,
			buttonText: {
				prev: "‹",
				next: "›",
				today: __("Hoy"),
				month: __("Mes"),
				week: __("Semana"),
				day: __("Día"),
				list: __("Lista"),
			},
			firstDay: 1,
			height: "auto",
			nowIndicator: true,
			slotDuration: "00:30:00",
			minTime: "07:00:00",
			maxTime: "24:00:00",
			timeFormat: "H:mm",
			slotLabelFormat: "H:mm",
			eventLimit: 4,
			selectable: true,
			selectHelper: true,
			editable: true,
			eventDurationEditable: true,
			timezone: false,
			noEventsMessage: __("No hay eventos en este período."),
			events: (start, end, _tz, callback) => {
				frappe
					.xcall("galeria_arte.api.eventos.calendario", {
						start: start.format("YYYY-MM-DD HH:mm:ss"),
						end: end.format("YYYY-MM-DD HH:mm:ss"),
						sala: this.f.sala.get_value() || null,
						tipo: this.f.tipo.get_value() || null,
						ver_inactivos: this.f.inactivos.get_value() ? 1 : 0,
					})
					.then(callback);
			},
			eventRender: (ev, $el) => {
				$el.attr("title", `${ev.title} · ${ev.lugar} · ${ev.estado}${ev.saldo_pendiente ? " · " + __("saldo pendiente") : ""}`);
				const lugar = `<span class="gal-ev-lugar">${frappe.utils.escape_html(ev.lugar || "")}${
					ev.estado === "Tentativo" ? " · " + __("tentativo") : ""
				}${ev.saldo_pendiente ? " · " + __("saldo pendiente") : ""}</span>`;
				$el.find(".fc-title, .fc-list-item-title a").append(lugar);
			},
			eventClick: (ev) => {
				galeria.eventos.resumen(ev.id, () => this.refrescar());
				return false;
			},
			select: (inicio, fin) => {
				// En la vista de mes, el clic en un día propone un horario de tarde.
				let a = inicio.clone();
				let b = fin.clone();
				if (!inicio.hasTime()) {
					a = inicio.clone().hour(18).minute(0);
					b = inicio.clone().hour(21).minute(0);
				}
				this.$cal.fullCalendar("unselect");
				galeria.eventos.nuevo(
					{
						inicio: a.format("YYYY-MM-DD HH:mm:ss"),
						fin: b.format("YYYY-MM-DD HH:mm:ss"),
						sala: this.f.sala.get_value() || undefined,
					},
					() => this.refrescar()
				);
			},
			eventDrop: (ev, _delta, revertir) => this.mover(ev, revertir),
			eventResize: (ev, _delta, revertir) => this.mover(ev, revertir),
		});
	}

	mover(ev, revertir) {
		const fin = ev.end || (ev.allDay ? ev.start.clone().add(1, "day") : ev.start.clone().add(2, "hours"));
		const formato = ev.allDay ? "YYYY-MM-DD" : "YYYY-MM-DD HH:mm:ss";
		frappe
			.xcall("galeria_arte.api.eventos.mover", {
				evento: ev.id,
				inicio: ev.start.format(formato),
				fin: fin.format(formato),
				todo_el_dia: ev.allDay ? 1 : 0,
			})
			.then(() => frappe.show_alert({ message: __("Evento movido"), indicator: "green" }))
			.catch(() => revertir());
	}

	refrescar() {
		this.$cal.fullCalendar("refetchEvents");
	}
}
