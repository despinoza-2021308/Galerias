// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Eventos de la galería: crear, ver resumen, vender boletos de cena, cobrar
// alquileres y llevar las subastas (obras, resultado y cobro al contado).
// Se usan desde el Calendario, la ficha del evento y Venta de Obras.

frappe.provide("galeria.eventos");

const EV_API = "galeria_arte.api.eventos";

galeria.eventos.COLORES = { Exposición: "#7C3AED", Cena: "#EA580C", Subasta: "#0891B2", Alquiler: "#2563EB" };
galeria.eventos.COLORES_ESTADO = {
	Planificado: "gray",
	Publicado: "green",
	Tentativo: "orange",
	Confirmado: "blue",
	Liquidado: "green",
	Realizado: "gray",
	Cancelado: "red",
	Vencido: "red",
};

galeria.eventos.RESULTADOS_SUBASTA = {
	Pendiente: [__("Pendiente"), "gray"],
	Adjudicada: [__("Por pagar"), "orange"],
	Pagada: [__("Pagada"), "green"],
	"No vendida": [__("No vendida"), "gray"],
	Vencida: [__("No pagó"), "red"],
};

// Plazo del comprador de una subasta: fecha y días que le quedan.
galeria.eventos.plazo_pago = function (fecha, dias) {
	const f = frappe.datetime.str_to_user(fecha);
	if (dias < 0) return `<span class="text-danger">${__("Venció el {0}", [f])}</span>`;
	if (dias === 0) return `<span class="text-danger">${__("Pagar hoy ({0})", [f])}</span>`;
	const texto = `${__("Pagar antes del {0}", [f])}<br>${dias === 1 ? __("queda 1 día") : __("quedan {0} días", [dias])}`;
	return dias <= 2 ? `<span class="text-warning">${texto}</span>` : texto;
};

galeria.eventos.rango = function (inicio, fin) {
	const a = moment(inicio);
	const b = moment(fin);
	if (a.isSame(b, "day")) return `${a.format("DD-MM-YYYY")} · ${a.format("HH:mm")}–${b.format("HH:mm")}`;
	return `${a.format("DD-MM-YYYY HH:mm")} – ${b.format("DD-MM-YYYY HH:mm")}`;
};

// ---------------------------------------------------------------------------
// Crear
// ---------------------------------------------------------------------------

galeria.eventos.nuevo = async function (opciones = {}, on_done) {
	const datos = await frappe.xcall(`${EV_API}.datos_formulario`);
	const precio_sala = (sala, todo) =>
		todo ? datos.precio_todo : flt((datos.salas.find((s) => s.name === sala) || {}).precio_alquiler);

	const d = new frappe.ui.Dialog({
		title: __("Nuevo evento"),
		fields: [
			{
				fieldtype: "Select",
				fieldname: "tipo",
				label: __("Tipo"),
				options: "Exposición\nCena\nSubasta\nAlquiler",
				default: opciones.tipo || "Cena",
				reqd: 1,
			},
			{ fieldtype: "Data", fieldname: "nombre", label: __("Nombre del evento"), reqd: 1 },
			{ fieldtype: "Column Break" },
			{ fieldtype: "Datetime", fieldname: "inicio", label: __("Inicio"), reqd: 1, default: opciones.inicio },
			{ fieldtype: "Datetime", fieldname: "fin", label: __("Fin"), reqd: 1, default: opciones.fin },
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Check",
				fieldname: "todo_el_espacio",
				label: __("Todo el espacio (las tres salas)"),
				onchange: () => poner_precio(),
			},
			{
				fieldtype: "Select",
				fieldname: "sala",
				label: __("Sala"),
				options: datos.salas.map((s) => s.name).join("\n"),
				default: opciones.sala || (datos.salas[0] || {}).name,
				depends_on: "eval:!doc.todo_el_espacio",
				onchange: () => poner_precio(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Int",
				fieldname: "cupo",
				label: __("Cupo"),
				depends_on: "eval:doc.tipo == 'Cena'",
				mandatory_depends_on: "eval:doc.tipo == 'Cena'",
			},
			{
				fieldtype: "Currency",
				fieldname: "precio_boleto",
				label: __("Precio del boleto"),
				depends_on: "eval:doc.tipo == 'Cena'",
				mandatory_depends_on: "eval:doc.tipo == 'Cena'",
			},
			{
				fieldtype: "Link",
				fieldname: "cliente",
				label: __("Cliente"),
				options: "Customer",
				depends_on: "eval:doc.tipo == 'Alquiler'",
				mandatory_depends_on: "eval:doc.tipo == 'Alquiler'",
			},
			{
				fieldtype: "Currency",
				fieldname: "precio_alquiler",
				label: __("Precio del alquiler"),
				depends_on: "eval:doc.tipo == 'Alquiler'",
				description: __("Precio de la sala; se puede ajustar."),
			},
			{
				fieldtype: "HTML",
				fieldname: "nota",
				depends_on: "eval:['Alquiler', 'Exposición', 'Subasta'].includes(doc.tipo)",
			},
		],
		primary_action_label: __("Crear"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${EV_API}.crear`, { datos: v });
				d.hide();
				frappe.show_alert({ message: __("Evento {0} creado", [r.evento]), indicator: "green" });
				on_done && on_done(r);
				// La subasta sigue con sus obras: se abre su resumen para agregarlas.
				if (v.tipo === "Subasta") galeria.eventos.resumen(r.evento, on_done);
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	const poner_precio = () => {
		if (d.get_value("tipo") !== "Alquiler") return;
		d.set_value("precio_alquiler", precio_sala(d.get_value("sala"), d.get_value("todo_el_espacio")));
	};
	d.fields_dict.nota.$wrapper.html(
		`<div class="text-muted small">${__(
			"Alquiler: queda Tentativo y aparta la fecha unos días; se confirma con un anticipo. Exposición: ocupa la sala todos los días que dure. Subasta: después de crearla se agregan las obras con su precio inicial."
		)}</div>`
	);
	d.fields_dict.tipo.$input.on("change", poner_precio);
	d.show();
	poner_precio();
};

// ---------------------------------------------------------------------------
// Resumen con acciones
// ---------------------------------------------------------------------------

galeria.eventos.resumen = async function (evento, on_done) {
	const e = await frappe.xcall(`${EV_API}.resumen`, { evento });
	const m = galeria.pagos.moneda;
	const esc = frappe.utils.escape_html;
	const recargar = () => {
		d.hide();
		on_done && on_done();
	};
	// Las acciones de la subasta vuelven a abrir el resumen para seguir trabajando.
	const reabrir = () => {
		recargar();
		galeria.eventos.resumen(evento, on_done);
	};
	const acciones = [];
	const accion = (texto, fn, primaria = false) => acciones.push({ texto, fn, primaria });

	if (e.tipo === "Subasta" && ["Planificado", "Publicado"].includes(e.estado))
		accion(__("Agregar obra"), () => galeria.eventos.agregar_obra(e.name, reabrir), !e.lotes.length);
	if (e.tipo !== "Alquiler" && e.estado === "Planificado")
		accion(__("Publicar"), () => galeria.eventos.publicar(e.name, recargar), e.tipo !== "Subasta" || e.lotes.length > 0);
	if (e.tipo === "Cena" && e.estado === "Publicado" && e.disponibles > 0)
		accion(__("Vender boletos"), () => galeria.eventos.vender_boletos(e.name, recargar), true);
	if (e.tipo === "Cena" && (e.boletos || []).some((b) => b.estado !== "Anulado")) {
		accion(__("Check-in"), () => frappe.set_route("check-in-galeria", { evento: e.name }));
		accion(__("Imprimir boletos"), () => galeria.boletos.imprimir(e.boletos.filter((b) => b.estado === "Válido").map((b) => b.name)));
	}
	if (e.tipo === "Alquiler" && e.estado === "Tentativo")
		accion(__("Confirmar con anticipo"), () => galeria.eventos.confirmar(e.name, e.total, recargar), true);
	if (e.tipo === "Alquiler" && e.estado === "Confirmado")
		accion(__("Registrar abono"), () => galeria.eventos.abonar(e.name, e.saldo, recargar), true);
	if ((e.tipo !== "Alquiler" && ["Planificado", "Publicado"].includes(e.estado)) || (e.tipo === "Alquiler" && e.estado === "Liquidado"))
		accion(__("Marcar realizado"), () => galeria.eventos.realizado(e.name, e.tipo === "Subasta" ? reabrir : recargar));
	if (e.tipo === "Exposición" && (e.obras || []).length)
		accion(__("Imprimir fichas"), () => galeria.obras.imprimir_fichas(e.obras.map((o) => o.obra)));
	if (!["Cancelado", "Vencido", "Realizado", "Liquidado"].includes(e.estado))
		accion(__("Cancelar evento"), () => galeria.eventos.cancelar(e.name, e, recargar));

	let cuerpo = `
		<div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom: var(--margin-md)">
			<div>
				<span class="indicator-pill" style="background:${galeria.eventos.COLORES[e.tipo]}; color:#fff">${esc(e.tipo)}</span>
				<span class="indicator-pill ${galeria.eventos.COLORES_ESTADO[e.estado] || "gray"}">${esc(e.estado)}</span>
			</div>
			<a href="/app/evento/${encodeURIComponent(e.name)}">${esc(e.name)} · ${__("Abrir ficha")}</a>
		</div>
		<div class="gal-desglose">
			<span>${__("Cuándo")}: <b>${galeria.eventos.rango(e.inicio, e.fin)}</b></span>
			<span>${__("Dónde")}: <b>${esc(e.lugar || "")}</b></span>
		</div>`;

	if (e.tipo === "Cena") {
		const pct = e.cupo ? Math.round((e.vendidos / e.cupo) * 100) : 0;
		cuerpo += `
			<div class="gal-progreso">
				<div class="gal-progreso-texto"><span><b>${__("{0} de {1} lugares vendidos", [e.vendidos, e.cupo])}</b> · ${__(
			"quedan {0}",
			[e.disponibles]
		)}</span><span class="text-muted">${__("Boleto")}: ${m(e.precio_boleto)} · ${__("Ingresos")}: ${m(e.ingresos)}</span></div>
				<div class="gal-progreso-barra"><div style="width:${pct}%"></div></div>
			</div>
			${galeria.boletos.html_lista(e)}
			}`;
	}
	if (e.tipo === "Alquiler") {
		const alerta =
			e.estado === "Confirmado" && flt(e.saldo) > 0
				? `<div class="alert alert-${e.dias_para_evento <= 3 ? "danger" : "warning"} small">${__(
						"Saldo pendiente de {0}: debe pagarse antes del evento ({1}).",
						[m(e.saldo), e.dias_para_evento <= 0 ? __("es hoy o ya pasó") : __("faltan {0} días", [e.dias_para_evento])]
				  )}</div>`
				: e.estado === "Tentativo"
				? `<div class="alert alert-warning small">${__("Apartado hasta el {0}. Si no deja anticipo, la fecha se libera.", [
						frappe.datetime.str_to_user(e.vence_tentativa),
				  ])}</div>`
				: "";
		cuerpo += `
			${alerta}
			<table class="gal-cuotas">
				<tbody>
					<tr><td>${__("Cliente")}</td><td class="text-right"><b>${esc(e.cliente_nombre || e.cliente || "")}</b></td></tr>
					<tr><td>${__("Alquiler")}</td><td class="text-right">${m(e.precio_alquiler)}</td></tr>
					${e.cargos.map((c) => `<tr><td>${esc(c.descripcion)}</td><td class="text-right">${m(c.monto)}</td></tr>`).join("")}
					<tr><td><b>${__("Total")}</b></td><td class="text-right"><b>${m(e.total)}</b></td></tr>
					<tr><td>${__("Abonado")}</td><td class="text-right text-success">${m(e.abonado)}</td></tr>
					<tr><td>${__("Saldo")}</td><td class="text-right ${flt(e.saldo) > 0 ? "text-danger" : ""}">${m(e.saldo)}</td></tr>
					${e.factura ? `<tr><td>${__("Factura")}</td><td class="text-right"><a href="/app/sales-invoice/${encodeURIComponent(e.factura)}">${esc(e.factura)}</a></td></tr>` : ""}
				</tbody>
			</table>`;
	}
	if (e.tipo === "Subasta") cuerpo += galeria.eventos.html_subasta(e);
	if (e.tipo === "Exposición") {
		cuerpo += e.obras.length
			? `<div class="gal-dato-label" style="margin-bottom:4px">${__("Obras exhibidas")}: ${e.obras.length} · ${__("vendidas durante la exposición")}: ${
					e.vendidas.length
			  } (${m(e.monto_vendido)})</div>
				<table class="gal-cuotas"><tbody>${e.obras
					.map((o) => {
						const vendida = e.vendidas.some((v) => v.name === o.obra);
						return `<tr><td>${esc(o.titulo || o.obra)}</td><td>${esc(o.artista || "")}</td>
							<td>${vendida ? `<span class="indicator-pill gray">${__("Vendida")}</span>` : ""}</td></tr>`;
					})
					.join("")}</tbody></table>`
			: `<p class="text-muted">${__("Agregue las obras exhibidas desde la ficha del evento.")}</p>`;
	}
	if (e.descripcion) cuerpo += `<p class="text-muted small" style="margin-top: var(--margin-sm)">${esc(e.descripcion)}</p>`;
	cuerpo += `<div style="display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; margin-top: var(--margin-md)">
		${acciones
			.map((a, i) => `<button type="button" class="btn ${a.primaria ? "btn-primary" : "btn-default"}" data-ev-accion="${i}">${a.texto}</button>`)
			.join("")}</div>`;

	const d = new frappe.ui.Dialog({ title: e.nombre, size: "large", fields: [{ fieldtype: "HTML", fieldname: "html" }] });
	d.fields_dict.html.$wrapper.html(cuerpo);
	d.fields_dict.html.$wrapper.on("click", "[data-ev-accion]", (ev) => acciones[cint($(ev.currentTarget).attr("data-ev-accion"))].fn());
	d.fields_dict.html.$wrapper.on("click", "[data-wa-boleto]", (ev) => {
		ev.preventDefault();
		galeria.boletos.whatsapp([$(ev.currentTarget).attr("data-wa-boleto")]);
	});
	d.fields_dict.html.$wrapper.on("click", "[data-lote-accion]", (ev) => {
		const $b = $(ev.currentTarget);
		const l = (e.lotes || []).find((x) => x.lote === $b.attr("data-lote"));
		const accion = $b.attr("data-lote-accion");
		if (!l) return;
		if (accion === "quitar") galeria.eventos.quitar_obra(e.name, l, reabrir);
		if (accion === "resultado") galeria.eventos.resultado(e.name, l, e.dias_pago, reabrir);
		if (accion === "cobrar") galeria.eventos.cobrar_subasta(e.name, l.lote, reabrir);
		if (accion === "factura") galeria.obras.imprimir("Sales Invoice", l.factura, "Factura Galería");
	});
	d.show();
};

// Obras de la subasta con su precio inicial, el resultado y lo que falta hacer.
galeria.eventos.html_subasta = function (e) {
	const m = galeria.pagos.moneda;
	const esc = frappe.utils.escape_html;
	const antes = ["Planificado", "Publicado"].includes(e.estado);
	const realizada = e.estado === "Realizado";
	if (!e.lotes.length) {
		return `<div class="alert alert-info small">${__("Agregue las obras que se van a subastar, con su precio inicial.")}</div>`;
	}
	let html = "";
	if (antes) {
		html += `<div class="text-muted small" style="margin-bottom: var(--margin-sm)">${__(
			"Las obras quedan apartadas para la subasta. Cuando termine, márquela como realizada para registrar el precio ganador y el comprador de cada obra."
		)}</div>`;
	}
	if (realizada) {
		html += `<div class="gal-desglose">
			<span>${__("Obras")}: <b>${e.ofrecidas}</b></span>
			<span>${__("Vendidas")}: <b>${e.vendidas}</b></span>
			<span>${__("Total ganador")}: <b>${m(e.total_ganador)}</b></span>
			<span>${__("Cobrado")}: <b class="text-success">${m(e.cobrado)}</b></span>
			${flt(e.por_cobrar) ? `<span>${__("Por cobrar")}: <b class="text-danger">${m(e.por_cobrar)}</b></span>` : ""}
		</div>`;
		if (e.pendientes) {
			html += `<div class="alert alert-warning small">${__(
				"Falta registrar el resultado de {0}. El comprador tiene {1} días para pagar al contado.",
				[e.pendientes === 1 ? __("1 obra") : __("{0} obras", [e.pendientes]), e.dias_pago]
			)}</div>`;
		}
	}
	const btn = (accion, l, texto, clase = "btn-default") =>
		`<button type="button" class="btn btn-xs ${clase}" data-lote-accion="${accion}" data-lote="${esc(l.lote)}">${texto}</button>`;
	const filas = e.lotes
		.map((l) => {
			const [etiqueta, color] = galeria.eventos.RESULTADOS_SUBASTA[l.resultado] || [l.resultado, "gray"];
			let detalle = "";
			if (l.resultado === "Adjudicada") detalle = galeria.eventos.plazo_pago(l.fecha_limite_pago, l.dias_restantes);
			if (l.resultado === "Pagada" && l.factura)
				detalle = `<a href="/app/sales-invoice/${encodeURIComponent(l.factura)}">${esc(l.factura)}</a>`;
			let botones = "";
			if (antes && l.resultado === "Pendiente") botones = btn("quitar", l, __("Quitar"));
			if (realizada && l.resultado === "Pendiente") botones = btn("resultado", l, __("Registrar resultado"), "btn-primary");
			if (l.resultado === "Adjudicada") botones = btn("cobrar", l, __("Cobrar"), "btn-primary") + btn("resultado", l, __("Corregir"));
			if (realizada && l.resultado === "No vendida") botones = btn("resultado", l, __("Corregir"));
			if (l.resultado === "Pagada" && l.factura) botones = btn("factura", l, __("Imprimir"));
			const comprador = l.comprador_nombre || l.comprador;
			return `<tr>
				<td><a href="/app/obra-de-arte/${encodeURIComponent(l.obra)}">${esc(l.titulo || l.obra)}</a><span class="gal-sub">${esc(l.artista || "")}</span></td>
				<td class="text-right gal-ocultar-movil">${m(l.precio_inicial)}</td>
				<td class="text-right">${flt(l.precio_ganador) ? `<b>${m(l.precio_ganador)}</b>` : `<span class="text-muted">—</span>`}${
					comprador ? `<span class="gal-sub">${esc(comprador)}</span>` : ""
				}</td>
				<td><span class="indicator-pill ${color}">${etiqueta}</span>${detalle ? `<span class="gal-sub">${detalle}</span>` : ""}</td>
				<td class="gal-lote-acciones">${botones}</td>
			</tr>`;
		})
		.join("");
	return `${html}<div style="overflow-x: auto"><table class="table gal-tabla gal-tabla-subasta" style="margin: 0">
		<thead><tr><th>${__("Obra")}</th><th class="text-right gal-ocultar-movil">${__("Precio inicial")}</th>
		<th class="text-right">${__("Precio ganador")}</th><th>${__("Estado")}</th><th></th></tr></thead>
		<tbody>${filas}</tbody></table></div>`;
};

// ---------------------------------------------------------------------------
// Acciones
// ---------------------------------------------------------------------------

galeria.eventos.publicar = async function (evento, on_done) {
	await frappe.xcall(`${EV_API}.publicar`, { evento });
	frappe.show_alert({ message: __("Evento publicado"), indicator: "green" });
	on_done && on_done();
};

galeria.eventos.realizado = function (evento, on_done) {
	frappe.confirm(__("¿Marcar el evento como realizado?"), async () => {
		await frappe.xcall(`${EV_API}.marcar_realizado`, { evento });
		on_done && on_done();
	});
};

galeria.eventos.cancelar = function (evento, e, on_done) {
	const m = galeria.pagos.moneda;
	let aviso = __("El evento se cancela y libera la sala.");
	if (e && e.tipo === "Cena" && e.vendidos) aviso += " " + __("Hay {0} lugares vendidos: la devolución de esos boletos se gestiona aparte.", [e.vendidos]);
	if (e && e.tipo === "Alquiler" && flt(e.abonado)) aviso += " " + __("Lo abonado ({0}) queda como saldo a favor del cliente.", [m(e.abonado)]);
	const d = new frappe.ui.Dialog({
		title: __("Cancelar evento"),
		fields: [
			{ fieldtype: "HTML", options: `<p>${aviso}</p>` },
			{ fieldtype: "Small Text", fieldname: "motivo", label: __("Motivo"), reqd: 1 },
		],
		primary_action_label: __("Cancelar evento"),
		primary_action: async (v) => {
			await frappe.xcall(`${EV_API}.cancelar`, { evento, motivo: v.motivo });
			d.hide();
			frappe.show_alert({ message: __("Evento cancelado"), indicator: "orange" });
			on_done && on_done();
		},
	});
	d.show();
};

galeria.eventos.vender_boletos = async function (evento, on_done) {
	const [e, datos] = await Promise.all([
		frappe.xcall(`${EV_API}.resumen`, { evento }),
		frappe.xcall(`${EV_API}.datos_formulario`),
	]);
	const m = galeria.pagos.moneda;
	const esc = frappe.utils.escape_html;
	let editor = null;
	const d = new frappe.ui.Dialog({
		title: __("Boletos · {0}", [e.nombre]),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "info" },
			{
				fieldtype: "Int",
				fieldname: "cantidad",
				label: __("Lugares"),
				default: 1,
				reqd: 1,
				description: __("Quedan {0} lugares · {1} cada boleto", [e.disponibles, m(e.precio_boleto)]),
				onchange: () => {
					pintar_asistentes();
					total_a_editor();
				},
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Link",
				fieldname: "cliente",
				label: __("Comprador"),
				options: "Customer",
				default: datos.cliente_defecto,
				onchange: () => datos_comprador(),
			},
			{
				fieldtype: "Data",
				fieldname: "correo",
				label: __("Correo del comprador"),
				options: "Email",
				description: __("Recibe todos los boletos."),
			},
			{
				fieldtype: "Data",
				fieldname: "whatsapp",
				label: __("WhatsApp del comprador"),
				description: __("Para enviarle todos los boletos por WhatsApp."),
			},
			{ fieldtype: "Section Break", label: __("Asistentes (cada boleto lleva su nombre)") },
			{ fieldtype: "HTML", fieldname: "asistentes" },
			{ fieldtype: "Section Break", label: __("Pago (los boletos se pagan al reservar)") },
			{ fieldtype: "HTML", fieldname: "pagos" },
			{ fieldtype: "HTML", fieldname: "total" },
		],
		primary_action_label: __("Vender boletos"),
		primary_action: async (v) => {
			const asistentes = leer_asistentes();
			if (asistentes.some((a) => !a.nombre)) {
				frappe.msgprint(__("Escriba el nombre de cada asistente."));
				return;
			}
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${EV_API}.vender_boletos`, {
					evento,
					cantidad: v.cantidad,
					cliente: v.cliente,
					pagos: editor.leer(),
					asistentes,
					correo: v.correo || null,
					whatsapp: v.whatsapp || null,
				});
				d.hide();
				galeria.boletos.vendidos(r, on_done);
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	const $asistentes = () => d.fields_dict.asistentes.$wrapper;
	const leer_asistentes = () =>
		$asistentes()
			.find(".gal-asistente")
			.map((_, el) => ({
				nombre: ($(el).find("[data-nombre]").val() || "").trim(),
				correo: ($(el).find("[data-correo]").val() || "").trim() || null,
				whatsapp: ($(el).find("[data-whatsapp]").val() || "").trim() || null,
			}))
			.get();
	// Rehace las filas al cambiar la cantidad, conservando lo ya escrito.
	const pintar_asistentes = () => {
		const previos = leer_asistentes();
		const n = Math.max(0, Math.min(cint(d.get_value("cantidad")), e.disponibles));
		const filas = [];
		for (let i = 0; i < n; i++) {
			const a = previos[i] || { nombre: i === 0 ? d.nombre_comprador || "" : "", correo: "", whatsapp: "" };
			filas.push(`<div class="gal-asistente" style="display: grid; grid-template-columns: 24px minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 0.8fr); gap: 6px; align-items: center; margin-bottom: 6px">
				<span class="text-muted">${i + 1}.</span>
				<input type="text" class="form-control" data-nombre placeholder="${__("Nombre del asistente")}" value="${esc(a.nombre || "")}">
				<input type="email" class="form-control" data-correo placeholder="${__("Correo (opcional)")}" value="${esc(a.correo || "")}">
				<input type="tel" class="form-control" data-whatsapp placeholder="${__("WhatsApp (opcional)")}" value="${esc(a.whatsapp || "")}">
			</div>`);
		}
		$asistentes().html(filas.join("") || `<div class="text-muted">${__("Indique cuántos lugares.")}</div>`);
	};
	const datos_comprador = async () => {
		const cliente = d.get_value("cliente");
		d.nombre_comprador = "";
		if (cliente && cliente !== datos.cliente_defecto) {
			const r = await frappe.db.get_value("Customer", cliente, ["customer_name", "email_id", "mobile_no"]);
			const c = r.message || {};
			d.nombre_comprador = c.customer_name || "";
			if (c.email_id && !d.get_value("correo")) d.set_value("correo", c.email_id);
			if (c.mobile_no && !d.get_value("whatsapp")) d.set_value("whatsapp", c.mobile_no);
			const primero = $asistentes().find("[data-nombre]").first();
			if (primero.length && !primero.val()) primero.val(d.nombre_comprador);
		}
	};
	const total = () => flt(cint(d.get_value("cantidad")) * flt(e.precio_boleto), 2);
	const actualizar = () => {
		const t = total();
		const pagado = editor ? editor.total() : 0;
		const falta = flt(t - pagado, 2);
		const cant = cint(d.get_value("cantidad"));
		d.fields_dict.total.$wrapper.html(`<div class="gal-total-pago">
			<span>${__("Total")}: <b>${m(t)}</b></span>
			<span class="${falta !== 0 ? "text-danger" : "text-success"}">${
				falta === 0 ? __("Pago completo") : falta > 0 ? __("Falta {0}", [m(falta)]) : __("Sobra {0}", [m(-falta)])
			}</span></div>`);
		d.get_primary_btn().prop("disabled", falta !== 0 || cant <= 0 || cant > e.disponibles);
	};
	const total_a_editor = () => {
		if (editor) editor.poner([{ monto: total() }]);
		actualizar();
	};
	d.fields_dict.info.$wrapper.html(
		`<div class="gal-desglose"><span>${galeria.eventos.rango(e.inicio, e.fin)}</span><span>${esc(e.lugar || "")}</span>
		<span>${__("{0} de {1} lugares vendidos", [e.vendidos, e.cupo])}</span></div>`
	);
	d.show();
	editor = galeria.pagos.editor(d.fields_dict.pagos.$wrapper, datos.modos_pago, actualizar);
	pintar_asistentes();
	total_a_editor();
};

// ---------------------------------------------------------------------------
// Boletos con QR
// ---------------------------------------------------------------------------

frappe.provide("galeria.boletos");

// Boletos de una cena en el resumen del evento.
galeria.boletos.html_lista = function (e) {
	const esc = frappe.utils.escape_html;
	const boletos = e.boletos || [];
	if (!boletos.length) return `<p class="text-muted">${__("Aún no hay boletos vendidos.")}</p>`;
	const colores = { Válido: "green", Usado: "blue", Anulado: "red" };
	const etiquetas = { Válido: __("Válido"), Usado: __("Llegó"), Anulado: __("Anulado") };
	return `<div class="gal-dato-label" style="margin-bottom: 4px">${__("Llegaron {0} de {1}", [
		e.llegaron || 0,
		boletos.filter((b) => b.estado !== "Anulado").length,
	])}</div>
		<div style="max-height: 320px; overflow-y: auto"><table class="gal-cuotas"><thead><tr><th>${__("Asistente")}</th><th>${__("Estado")}</th><th>${__("Factura")}</th><th></th></tr></thead><tbody>
		${boletos
			.map(
				(b) => `<tr><td>${esc(b.asistente)}<span class="gal-sub">${esc(b.name)}${b.correo ? " · " + esc(b.correo) : ""}</span></td>
				<td><span class="indicator-pill ${colores[b.estado] || "gray"}">${etiquetas[b.estado] || esc(b.estado)}</span></td>
				<td><a href="/app/sales-invoice/${encodeURIComponent(b.factura || "")}">${esc(b.factura || "")}</a></td>
				<td class="text-right" style="white-space: nowrap">${
					b.estado === "Válido"
						? `<a href="#" data-wa-boleto="${esc(b.name)}" title="${__("Enviar por WhatsApp")}">WhatsApp</a>${b.whatsapp_enviado ? " ✓" : ""} · `
						: ""
				}<a href="${galeria.boletos.url(b.codigo)}" target="_blank">${__("Ver")}</a></td></tr>`
			)
			.join("")}</tbody></table></div>`;
};

galeria.boletos.ICONO_WA = `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style="vertical-align: -2px"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2c-1.5 0-3-.4-4.3-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2c0 1.3.9 2.5 1.1 2.7.1.2 1.8 2.8 4.4 3.9 1.6.7 2.3.8 3.1.6.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.1-1.2l-.7-.4z"/></svg>`;

galeria.boletos.url = function (codigo) {
	return `${frappe.urllib.get_base_url()}/boleto?c=${encodeURIComponent(codigo)}`;
};

galeria.boletos.imprimir = async function (boletos) {
	if (!boletos || !boletos.length) return;
	// La ventana se abre antes de la llamada para que el navegador no la bloquee.
	const ventana = window.open("", "_blank");
	try {
		const html = await frappe.xcall("galeria_arte.api.boletos.html_boletos", { boletos });
		ventana.document.open();
		ventana.document.write(html);
		ventana.document.close();
	} catch (e) {
		ventana && ventana.close();
	}
};

// Abre WhatsApp con el mensaje listo (la ventana se abre antes de la llamada
// para que el navegador no la bloquee). Sin número, WhatsApp deja elegir el contacto.
galeria.boletos.whatsapp = async function (boletos, numero = null, para_comprador = false) {
	const ventana = window.open("", "_blank");
	try {
		const r = await frappe.xcall("galeria_arte.api.boletos.whatsapp", {
			boletos,
			numero,
			para_comprador: para_comprador ? 1 : 0,
		});
		ventana.location.href = r.url;
	} catch (e) {
		ventana && ventana.close();
	}
};

galeria.boletos.enviar = function (boletos, correo) {
	const d = new frappe.ui.Dialog({
		title: __("Enviar boletos por correo"),
		fields: [
			{
				fieldtype: "Data",
				fieldname: "correo",
				label: __("Correo"),
				options: "Email",
				default: correo || "",
				description: __("Además, cada asistente que tenga correo recibe el suyo."),
			},
		],
		primary_action_label: __("Enviar"),
		primary_action: async (v) => {
			const r = await frappe.xcall("galeria_arte.api.boletos.enviar", { boletos, correo: v.correo || null });
			d.hide();
			galeria.boletos.aviso_correo(r.enviados, r.hay_cuenta);
		},
	});
	d.show();
};

galeria.boletos.aviso_correo = function (enviados, hay_cuenta) {
	if (!enviados || !enviados.length) return;
	frappe.show_alert({
		message: hay_cuenta
			? __("Boletos enviados a: {0}", [enviados.join(", ")])
			: __("Correo preparado para {0}. Se enviará cuando se configure la cuenta de correo de salida.", [enviados.join(", ")]),
		indicator: hay_cuenta ? "green" : "orange",
	}, 8);
};

// Después de vender: los boletos con sus enlaces, para imprimir o compartir.
galeria.boletos.vendidos = async function (r, on_done) {
	const lista = await frappe.xcall("frappe.client.get_list", {
		doctype: "Boleto",
		filters: { name: ["in", r.boletos] },
		fields: ["name", "asistente", "codigo", "correo", "whatsapp"],
		order_by: "creation asc",
		limit_page_length: 100,
	});
	const esc = frappe.utils.escape_html;
	const d = new frappe.ui.Dialog({
		title: __("Boletos vendidos"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "html" }],
		primary_action_label: __("Imprimir boletos"),
		primary_action: () => galeria.boletos.imprimir(r.boletos),
		secondary_action_label: __("Cerrar"),
		secondary_action: () => d.hide(),
	});
	d.onhide = () => on_done && on_done(r);
	d.fields_dict.html.$wrapper.html(`
		<div class="gal-desglose">
			<span>${__("Factura")}: <a href="/app/sales-invoice/${encodeURIComponent(r.factura)}">${esc(r.factura)}</a></span>
			<span>${__("{0} de {1} lugares vendidos", [r.lugares_vendidos, r.cupo])}</span>
		</div>
		<div style="margin-bottom: var(--margin-sm)">
			<button type="button" class="btn btn-sm btn-success" data-wa-comprador>${galeria.boletos.ICONO_WA} ${__("Enviar todos al comprador por WhatsApp")}</button>
		</div>
		<table class="table gal-tabla" style="margin: 0"><tbody>
		${lista
			.map(
				(b) => `<tr><td>${esc(b.asistente)}<span class="gal-sub">${esc(b.name)}${b.correo ? " · " + esc(b.correo) : ""}${
					b.whatsapp ? " · +" + esc(b.whatsapp) : ""
				}</span></td>
				<td class="text-right" style="white-space: nowrap">
				<button type="button" class="btn btn-xs btn-default" data-wa="${esc(b.name)}">${galeria.boletos.ICONO_WA} WhatsApp</button>
				<a class="btn btn-xs btn-default" href="${galeria.boletos.url(b.codigo)}" target="_blank">${__("Ver boleto")}</a>
				<button type="button" class="btn btn-xs btn-default" data-copiar="${esc(galeria.boletos.url(b.codigo))}">${__("Copiar enlace")}</button></td></tr>`
			)
			.join("")}
		</tbody></table>`);
	d.fields_dict.html.$wrapper.on("click", "[data-copiar]", (ev) => frappe.utils.copy_to_clipboard($(ev.currentTarget).attr("data-copiar")));
	d.fields_dict.html.$wrapper.on("click", "[data-wa]", (ev) => galeria.boletos.whatsapp([$(ev.currentTarget).attr("data-wa")]));
	d.fields_dict.html.$wrapper.on("click", "[data-wa-comprador]", () => galeria.boletos.whatsapp(r.boletos, r.whatsapp_comprador, true));
	d.show();
	galeria.boletos.aviso_correo(r.correos, r.hay_cuenta_de_correo);
};

galeria.eventos.confirmar = async function (evento, total, on_done) {
	const datos = await frappe.xcall(`${EV_API}.datos_formulario`);
	const d = new frappe.ui.Dialog({
		title: __("Confirmar alquiler"),
		fields: [
			{
				fieldtype: "Currency",
				fieldname: "anticipo",
				label: __("Anticipo"),
				reqd: 1,
				description: __("Total del alquiler: {0}. El saldo se paga antes del evento.", [galeria.pagos.moneda(total)]),
			},
			{
				fieldtype: "Select",
				fieldname: "modo_pago",
				label: __("Forma de pago"),
				options: datos.modos_pago.join("\n"),
				default: datos.modos_pago[0],
				reqd: 1,
			},
			{ fieldtype: "Data", fieldname: "referencia", label: __("Referencia") },
		],
		primary_action_label: __("Confirmar"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${EV_API}.confirmar_alquiler`, { evento, ...v });
				d.hide();
				galeria.eventos.aviso_alquiler(r);
				on_done && on_done(r);
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.show();
};

galeria.eventos.abonar = async function (evento, saldo, on_done) {
	const datos = await frappe.xcall(`${EV_API}.datos_formulario`);
	const d = new frappe.ui.Dialog({
		title: __("Abono al alquiler"),
		fields: [
			{
				fieldtype: "Currency",
				fieldname: "monto",
				label: __("Monto"),
				reqd: 1,
				default: saldo,
				description: __("Saldo: {0}", [galeria.pagos.moneda(saldo)]),
			},
			{
				fieldtype: "Select",
				fieldname: "modo_pago",
				label: __("Forma de pago"),
				options: datos.modos_pago.join("\n"),
				default: datos.modos_pago[0],
				reqd: 1,
			},
			{ fieldtype: "Data", fieldname: "referencia", label: __("Referencia") },
		],
		primary_action_label: __("Registrar abono"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${EV_API}.abonar_alquiler`, { evento, ...v });
				d.hide();
				galeria.eventos.aviso_alquiler(r);
				on_done && on_done(r);
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.show();
};

// ---------------------------------------------------------------------------
// Subastas
// ---------------------------------------------------------------------------

galeria.eventos.agregar_obra = function (evento, on_done) {
	const d = new frappe.ui.Dialog({
		title: __("Agregar obra a la subasta"),
		fields: [
			{
				fieldtype: "Link",
				fieldname: "obra",
				label: __("Obra"),
				options: "Obra de Arte",
				reqd: 1,
				get_query: () => ({ filters: { estado: "Disponible" } }),
				description: __("Solo obras disponibles; quedan apartadas hasta la subasta."),
				onchange: async () => {
					const obra = d.get_value("obra");
					if (!obra) return;
					const r = await frappe.db.get_value("Obra de Arte", obra, "precio_venta");
					if (r.message && !flt(d.get_value("precio_inicial"))) d.set_value("precio_inicial", r.message.precio_venta);
				},
			},
			{
				fieldtype: "Currency",
				fieldname: "precio_inicial",
				label: __("Precio inicial"),
				reqd: 1,
				description: __("Precio con el que empieza la subasta (por defecto, el precio de la obra)."),
			},
		],
		primary_action_label: __("Agregar"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				await frappe.xcall(`${EV_API}.agregar_lote`, { evento, obra: v.obra, precio_inicial: v.precio_inicial });
				d.hide();
				frappe.show_alert({ message: __("Obra agregada a la subasta"), indicator: "green" });
				on_done && on_done();
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.show();
};

galeria.eventos.quitar_obra = function (evento, l, on_done) {
	frappe.confirm(__("¿Quitar {0} de la subasta? La obra vuelve a estar disponible.", [frappe.utils.escape_html(l.titulo || l.obra)]), async () => {
		await frappe.xcall(`${EV_API}.quitar_lote`, { evento, lote: l.lote });
		on_done && on_done();
	});
};

galeria.eventos.resultado = function (evento, l, dias_pago, on_done) {
	const m = galeria.pagos.moneda;
	const VENDIDA = __("Se vendió");
	const d = new frappe.ui.Dialog({
		title: __("Resultado · {0}", [l.titulo || l.obra]),
		fields: [
			{
				fieldtype: "Select",
				fieldname: "resultado",
				label: __("Resultado"),
				options: [VENDIDA, __("No se vendió")].join("\n"),
				default: l.resultado === "No vendida" ? __("No se vendió") : VENDIDA,
				reqd: 1,
			},
			{
				fieldtype: "Currency",
				fieldname: "precio_ganador",
				label: __("Precio ganador"),
				default: flt(l.precio_ganador) || null,
				depends_on: `eval:doc.resultado == '${VENDIDA}'`,
				mandatory_depends_on: `eval:doc.resultado == '${VENDIDA}'`,
				description: __("Precio final con el que se vendió. Precio inicial: {0}.", [m(l.precio_inicial)]),
			},
			{
				fieldtype: "Link",
				fieldname: "comprador",
				label: __("Comprador"),
				options: "Customer",
				default: l.comprador || null,
				depends_on: `eval:doc.resultado == '${VENDIDA}'`,
				mandatory_depends_on: `eval:doc.resultado == '${VENDIDA}'`,
				description: __("Si es un cliente nuevo, escriba su nombre y elija «Crear nuevo Cliente»."),
			},
			{ fieldtype: "HTML", fieldname: "nota" },
		],
		primary_action_label: __("Guardar resultado"),
		primary_action: async (v) => {
			const vendida = v.resultado === VENDIDA;
			if (vendida && flt(v.precio_ganador) < flt(l.precio_inicial)) {
				frappe.msgprint(__("El precio ganador no puede ser menor que el inicial ({0}).", [m(l.precio_inicial)]));
				return;
			}
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${EV_API}.registrar_resultado`, {
					evento,
					lote: l.lote,
					vendida: vendida ? 1 : 0,
					precio_ganador: vendida ? v.precio_ganador : null,
					comprador: vendida ? v.comprador : null,
				});
				d.hide();
				frappe.show_alert({
					message:
						r.resultado === "Adjudicada"
							? __("Adjudicada. Debe pagar antes del {0}.", [frappe.datetime.str_to_user(r.fecha_limite_pago)])
							: __("Resultado guardado"),
					indicator: "green",
				});
				on_done && on_done(r);
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.fields_dict.nota.$wrapper.html(
		`<div class="text-muted small">${__(
			"El comprador paga el precio ganador completo, al contado, en un plazo de {0} días. La factura se emite cuando pague; si no paga a tiempo, la obra vuelve a estar disponible.",
			[dias_pago || 7]
		)}</div>`
	);
	d.show();
};

galeria.eventos.cobrar_subasta = async function (evento, lote, on_done) {
	const c = await frappe.xcall(`${EV_API}.datos_cobro_subasta`, { evento, lote });
	const m = galeria.pagos.moneda;
	const esc = frappe.utils.escape_html;
	if (c.resultado !== "Adjudicada") {
		frappe.msgprint(__("La obra no está pendiente de pago."));
		return;
	}
	if (c.dias_restantes < 0) {
		frappe.msgprint(__("El plazo para pagar venció el {0}.", [frappe.datetime.str_to_user(c.fecha_limite_pago)]));
		return;
	}
	let editor = null;
	const d = new frappe.ui.Dialog({
		title: __("Cobrar obra de subasta · {0}", [c.titulo]),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "info" },
			{
				fieldtype: "Currency",
				fieldname: "monto_artista",
				label: __("Monto para el artista"),
				reqd: 1,
				default: c.monto_artista,
				description: __("Queda congelado en la factura."),
				onchange: () => actualizar(),
			},
			{ fieldtype: "Section Break", label: __("Pago al contado (precio ganador completo)") },
			{ fieldtype: "HTML", fieldname: "pagos" },
			{ fieldtype: "HTML", fieldname: "total" },
		],
		primary_action_label: __("Cobrar y facturar"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${EV_API}.cobrar_subasta`, {
					evento,
					lote,
					pagos: editor.leer(),
					monto_artista: v.monto_artista,
				});
				d.hide();
				// El resumen de la subasta se vuelve a abrir al cerrar el aviso de venta.
				galeria.obras.venta_lista(r, () => on_done && on_done(r));
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	const actualizar = () => {
		const total = flt(c.precio_ganador, 2);
		const falta = flt(total - (editor ? editor.total() : 0), 2);
		const monto = flt(d.get_value("monto_artista"));
		const gan = galeria.obras.ganancia(total, monto);
		d.fields_dict.total.$wrapper.html(`<div class="gal-total-pago">
			<span>${__("Total")}: <b>${m(total)}</b></span>
			<span class="${falta !== 0 ? "text-danger" : "text-success"}">${
				falta === 0 ? __("Pago completo") : falta > 0 ? __("Falta {0}", [m(falta)]) : __("Sobra {0}", [m(-falta)])
			}</span></div>
			<div class="text-muted small" style="margin-top: 6px">${__("Para el artista")}: ${m(monto)} · ${__("Ganancia de la galería")}:
				<b class="${gan < 0 ? "text-danger" : "text-success"}">${m(gan)}</b></div>`);
		d.get_primary_btn().prop("disabled", falta !== 0);
	};
	d.fields_dict.info.$wrapper.html(`<div class="gal-desglose">
		<span>${__("Subasta")}: <b>${esc(c.subasta)}</b></span>
		<span>${__("Comprador")}: <b>${esc(c.comprador_nombre || c.comprador)}</b></span>
		<span>${__("Precio ganador")}: <b>${m(c.precio_ganador)}</b></span>
		<span>${galeria.eventos.plazo_pago(c.fecha_limite_pago, c.dias_restantes)}</span>
	</div>`);
	d.show();
	editor = galeria.pagos.editor(d.fields_dict.pagos.$wrapper, c.modos_pago, actualizar);
	editor.poner([{ monto: c.precio_ganador }]);
	actualizar();
};

galeria.eventos.aviso_alquiler = function (r) {
	if (r.factura) {
		frappe.msgprint({
			title: __("Alquiler liquidado"),
			indicator: "green",
			message: __("El saldo quedó en cero y se emitió la factura {0}, ya pagada.", [
				`<a href="/app/sales-invoice/${encodeURIComponent(r.factura)}">${frappe.utils.escape_html(r.factura)}</a>`,
			]),
		});
	} else {
		frappe.show_alert({
			message: __("Pago registrado. Saldo: {0}", [galeria.pagos.moneda(r.saldo)]),
			indicator: "green",
		});
	}
};
