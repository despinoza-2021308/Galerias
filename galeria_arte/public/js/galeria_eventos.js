// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Eventos de la galería: crear, ver resumen, vender boletos de cena y cobrar
// alquileres. Se usan desde el Calendario y desde la ficha del evento.

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
				depends_on: "eval:doc.tipo == 'Alquiler' || doc.tipo == 'Exposición'",
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
			"Alquiler: queda Tentativo y aparta la fecha unos días; se confirma con un anticipo. Exposición: no bloquea la sala."
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
	const acciones = [];
	const accion = (texto, fn, primaria = false) => acciones.push({ texto, fn, primaria });

	if (e.tipo !== "Alquiler" && e.estado === "Planificado") accion(__("Publicar"), () => galeria.eventos.publicar(e.name, recargar), true);
	if (e.tipo === "Cena" && e.estado === "Publicado" && e.disponibles > 0)
		accion(__("Vender boletos"), () => galeria.eventos.vender_boletos(e.name, recargar), true);
	if (e.tipo === "Alquiler" && e.estado === "Tentativo")
		accion(__("Confirmar con anticipo"), () => galeria.eventos.confirmar(e.name, e.total, recargar), true);
	if (e.tipo === "Alquiler" && e.estado === "Confirmado")
		accion(__("Registrar abono"), () => galeria.eventos.abonar(e.name, e.saldo, recargar), true);
	if ((e.tipo !== "Alquiler" && ["Planificado", "Publicado"].includes(e.estado)) || (e.tipo === "Alquiler" && e.estado === "Liquidado"))
		accion(__("Marcar realizado"), () => galeria.eventos.realizado(e.name, recargar));
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
			${
				e.asistentes.length
					? `<table class="gal-cuotas"><thead><tr><th>${__("Asistente")}</th><th class="text-right">${__("Lugares")}</th><th>${__("Factura")}</th></tr></thead><tbody>
					${e.asistentes
						.map(
							(a) => `<tr><td>${esc(a.nombre || "")}</td><td class="text-right">${a.lugares}</td>
							<td><a href="/app/sales-invoice/${encodeURIComponent(a.factura || "")}">${esc(a.factura || "")}</a></td></tr>`
						)
						.join("")}</tbody></table>`
					: `<p class="text-muted">${__("Aún no hay boletos vendidos.")}</p>`
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
	d.show();
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
				onchange: () => total_a_editor(),
			},
			{ fieldtype: "Column Break" },
			{ fieldtype: "Link", fieldname: "cliente", label: __("Cliente"), options: "Customer", default: datos.cliente_defecto },
			{ fieldtype: "Section Break", label: __("Pago (los boletos se pagan al reservar)") },
			{ fieldtype: "HTML", fieldname: "pagos" },
			{ fieldtype: "HTML", fieldname: "total" },
		],
		primary_action_label: __("Vender boletos"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${EV_API}.vender_boletos`, {
					evento,
					cantidad: v.cantidad,
					cliente: v.cliente,
					pagos: editor.leer(),
				});
				d.hide();
				frappe.show_alert({
					message: __("{0} lugares vendidos ({1}/{2}) · factura {3}", [v.cantidad, r.lugares_vendidos, r.cupo, r.factura]),
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
		`<div class="gal-desglose"><span>${galeria.eventos.rango(e.inicio, e.fin)}</span><span>${frappe.utils.escape_html(e.lugar || "")}</span>
		<span>${__("{0} de {1} lugares vendidos", [e.vendidos, e.cupo])}</span></div>`
	);
	d.show();
	editor = galeria.pagos.editor(d.fields_dict.pagos.$wrapper, datos.modos_pago, actualizar);
	total_a_editor();
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
