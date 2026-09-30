// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Venta de obras de arte: reservar, abonar, extender, cancelar y vender.
// Se usan desde Venta de Obras, el catálogo, la ficha de la obra y la del
// coleccionista.

frappe.provide("galeria.obras");

const ARTE_API = "galeria_arte.api.arte";
const IVA_GALERIA = 0.12;

galeria.obras.ganancia = function (precio, monto_artista) {
	return flt(flt(precio) / (1 + IVA_GALERIA) - flt(monto_artista), 2);
};

galeria.obras.COLORES_ESTADO = {
	Disponible: "green",
	Reservada: "yellow",
	Vendida: "gray",
	"Devuelta al artista": "blue",
};

galeria.obras.imprimir = function (doctype, name, formato) {
	window.open(
		"/printview?doctype=" +
			encodeURIComponent(doctype) +
			"&name=" +
			encodeURIComponent(name) +
			"&format=" +
			encodeURIComponent(formato) +
			"&no_letterhead=1&trigger_print=1",
		"_blank"
	);
};

function campo_modo_pago(modos) {
	return {
		fieldtype: "Select",
		fieldname: "modo_pago",
		label: __("Forma de pago"),
		options: modos.join("\n"),
		default: modos.includes("Efectivo") ? "Efectivo" : modos[0],
		reqd: 1,
	};
}

// ---------------------------------------------------------------------------
// Reservaciones
// ---------------------------------------------------------------------------

galeria.obras.reservar = async function (obra, on_done) {
	const datos = await frappe.xcall(`${ARTE_API}.datos_venta`, { obra });
	const o = datos.obra;
	const d = new frappe.ui.Dialog({
		title: __("Reservar · {0}", [o.titulo]),
		fields: [
			{ fieldtype: "Link", fieldname: "cliente", label: __("Cliente"), options: "Customer", reqd: 1 },
			{
				fieldtype: "Currency",
				fieldname: "anticipo",
				label: __("Anticipo (obligatorio)"),
				reqd: 1,
				description: __("Precio de la obra: {0}", [galeria.pagos.moneda(o.precio_venta)]),
			},
			campo_modo_pago(datos.modos_pago),
			{ fieldtype: "Data", fieldname: "referencia", label: __("Referencia (boleta, voucher, transferencia)") },
			{
				fieldtype: "Date",
				fieldname: "fecha_limite",
				label: __("Reservada hasta"),
				reqd: 1,
				default: frappe.datetime.add_days(frappe.datetime.get_today(), 7),
				description: __("Al pasar esta fecha el sistema avisa; la obra no se libera sola."),
			},
			{ fieldtype: "Small Text", fieldname: "notas", label: __("Notas") },
		],
		primary_action_label: __("Reservar"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${ARTE_API}.crear_reservacion`, { obra, ...v });
				d.hide();
				galeria.obras.reserva_lista(r.reservacion, o.titulo);
				on_done && on_done(r);
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.show();
};

galeria.obras.reserva_lista = function (reservacion, titulo) {
	const d = new frappe.ui.Dialog({
		title: __("Obra reservada"),
		fields: [{ fieldtype: "HTML", fieldname: "html" }],
		primary_action_label: __("Cerrar"),
		primary_action: () => d.hide(),
		secondary_action_label: __("Imprimir recibo"),
		secondary_action: () => galeria.obras.imprimir("Reservacion de Obra", reservacion, "Recibo de Reserva"),
	});
	d.fields_dict.html.$wrapper.html(`
		<div class="text-center" style="padding: var(--padding-md) 0">
			<div class="text-muted">${__("Reservación")}</div>
			<div class="h3" style="margin: 4px 0"><a href="/app/reservacion-de-obra/${encodeURIComponent(reservacion)}">${frappe.utils.escape_html(reservacion)}</a></div>
			<div>${frappe.utils.escape_html(titulo || "")}</div>
		</div>`);
	d.show();
};

galeria.obras.abonar = function (reservacion, saldo, on_done) {
	frappe.xcall("galeria_arte.api.facturacion.opciones_cobro").then((opciones) => {
		const d = new frappe.ui.Dialog({
			title: __("Abonar a la reserva · {0}", [reservacion]),
			fields: [
				{
					fieldtype: "Currency",
					fieldname: "monto",
					label: __("Monto del abono"),
					reqd: 1,
					description: saldo ? __("Saldo de la obra: {0}", [galeria.pagos.moneda(saldo)]) : "",
				},
				campo_modo_pago(opciones.modos_pago),
				{ fieldtype: "Data", fieldname: "referencia", label: __("Referencia") },
			],
			primary_action_label: __("Registrar abono"),
			primary_action: async (v) => {
				d.get_primary_btn().prop("disabled", true);
				try {
					const r = await frappe.xcall(`${ARTE_API}.agregar_abono`, { reservacion, ...v });
					d.hide();
					frappe.show_alert({
						message: __("Abono registrado. Saldo de la obra: {0}", [galeria.pagos.moneda(r.saldo_obra)]),
						indicator: "green",
					});
					on_done && on_done(r);
				} finally {
					d.get_primary_btn().prop("disabled", false);
				}
			},
		});
		d.show();
	});
};

galeria.obras.extender = function (reservacion, fecha_actual, on_done) {
	const d = new frappe.ui.Dialog({
		title: __("Extender la reserva · {0}", [reservacion]),
		fields: [
			{
				fieldtype: "Date",
				fieldname: "fecha_limite",
				label: __("Nueva fecha límite"),
				reqd: 1,
				default: frappe.datetime.add_days(frappe.datetime.get_today(), 7),
				description: fecha_actual ? __("Fecha actual: {0}", [frappe.datetime.str_to_user(fecha_actual)]) : "",
			},
		],
		primary_action_label: __("Extender"),
		primary_action: async (v) => {
			await frappe.xcall(`${ARTE_API}.extender_reservacion`, { reservacion, ...v });
			d.hide();
			frappe.show_alert({ message: __("Reserva extendida"), indicator: "green" });
			on_done && on_done();
		},
	});
	d.show();
};

galeria.obras.cancelar_reserva = function (reservacion, on_done) {
	const d = new frappe.ui.Dialog({
		title: __("Cancelar la reserva · {0}", [reservacion]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p>${__(
					"La obra vuelve a estar Disponible. Lo abonado queda como saldo a favor del cliente; la devolución del dinero, si aplica, se hace aparte."
				)}</p>`,
			},
			{ fieldtype: "Small Text", fieldname: "motivo", label: __("Motivo") },
		],
		primary_action_label: __("Cancelar la reserva"),
		primary_action: async (v) => {
			const r = await frappe.xcall(`${ARTE_API}.cancelar_reservacion`, { reservacion, motivo: v.motivo });
			d.hide();
			frappe.msgprint(
				__("Reserva cancelada. {0} tiene {1} de saldo a favor.", [
					r.cliente,
					galeria.pagos.moneda(r.saldo_a_favor),
				])
			);
			on_done && on_done(r);
		},
	});
	d.show();
};

// ---------------------------------------------------------------------------
// Vender
// ---------------------------------------------------------------------------

galeria.obras.vender = async function (obra, on_done) {
	const datos = await frappe.xcall(`${ARTE_API}.datos_venta`, { obra });
	const o = datos.obra;
	const res = datos.reservacion;
	const m = galeria.pagos.moneda;
	const de_reserva = res ? flt(res.disponible) : 0;
	const opciones_saldo = [datos.abonos_libres, ...datos.planes_pago];
	// Los campos disparan onchange al crearse el diálogo; el resumen real se asigna después.
	let resumen = () => {};
	let editor = null;

	const calcular = (d) => {
		const precio = flt(d.get_value("precio"));
		const de_hoy = editor ? editor.total() : 0;
		const aplicado_reserva = Math.min(de_reserva, precio);
		const recibido = flt(aplicado_reserva + de_hoy, 2);
		return { precio, de_hoy, aplicado_reserva, recibido, saldo: flt(precio - recibido, 2) };
	};

	const d = new frappe.ui.Dialog({
		title: __("Vender · {0}", [o.titulo]),
		size: "large",
		fields: [
			{
				fieldtype: "Link",
				fieldname: "cliente",
				label: __("Cliente"),
				options: "Customer",
				reqd: 1,
				default: res ? res.cliente : null,
				read_only: res ? 1 : 0,
				description: res ? __("Reservada por este cliente ({0}).", [res.name]) : "",
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Currency",
				fieldname: "precio",
				label: __("Precio final (con IVA)"),
				reqd: 1,
				default: o.precio_venta,
				onchange: () => resumen(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Currency",
				fieldname: "monto_artista",
				label: __("Monto para el artista"),
				reqd: 1,
				default: o.monto_artista,
				description: __("Queda congelado en la factura."),
				onchange: () => resumen(),
			},
			{
				fieldtype: "Section Break",
				label: res
					? __("Pago de hoy (opcional: ya hay anticipo de la reserva)")
					: __("Anticipo o pago de hoy (obligatorio)"),
			},
			{ fieldtype: "HTML", fieldname: "pagos" },
			{ fieldtype: "Section Break", label: __("Saldo restante") },
			{
				fieldtype: "Select",
				fieldname: "plan_pagos",
				label: __("El saldo se paga con"),
				options: opciones_saldo.join("\n"),
				default: datos.abonos_libres,
				onchange: () => resumen(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Date",
				fieldname: "pagar_antes_de",
				label: __("Pagar el saldo antes de"),
				default: frappe.datetime.add_days(frappe.datetime.get_today(), datos.dias_abonos_libres),
			},
			{ fieldtype: "Section Break" },
			{ fieldtype: "HTML", fieldname: "resumen" },
		],
		primary_action_label: __("Facturar venta"),
		primary_action: async (v) => {
			const c = calcular(d);
			if (c.recibido <= 0) {
				frappe.msgprint(__("Para vender la obra se necesita un anticipo: registre el pago de hoy."));
				return;
			}
			if (c.saldo < 0) {
				frappe.msgprint(__("Lo recibido ({0}) es mayor que el precio ({1}).", [m(c.recibido), m(c.precio)]));
				return;
			}
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${ARTE_API}.vender`, {
					obra,
					cliente: v.cliente,
					precio: v.precio,
					monto_artista: v.monto_artista,
					plan_pagos: c.saldo > 0 ? v.plan_pagos : null,
					pagar_antes_de: c.saldo > 0 && v.plan_pagos === datos.abonos_libres ? v.pagar_antes_de : null,
					pagos: editor.leer(),
				});
				d.hide();
				galeria.obras.venta_lista(r);
				on_done && on_done(r);
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});

	resumen = () => {
		const c = calcular(d);
		const monto = flt(d.get_value("monto_artista"));
		const gan = galeria.obras.ganancia(c.precio, monto);
		const plan = d.get_value("plan_pagos");
		const libres = plan === datos.abonos_libres;
		const hay_saldo = c.saldo > 0;
		d.set_df_property("plan_pagos", "hidden", hay_saldo ? 0 : 1);
		d.set_df_property("pagar_antes_de", "hidden", hay_saldo && libres ? 0 : 1);

		const celda = (label, valor, clase = "") =>
			`<div class="col-sm-3" style="margin-bottom: var(--margin-sm)"><div class="text-muted small">${label}</div><div class="bold ${clase}">${valor}</div></div>`;
		let html = `<div class="row">
			${celda(__("Precio"), m(c.precio))}
			${res ? celda(__("Abonado en la reserva"), m(c.aplicado_reserva)) : ""}
			${celda(__("Pago de hoy"), m(c.de_hoy))}
			${celda(__("Saldo restante"), m(Math.max(c.saldo, 0)), c.saldo > 0 ? "text-danger" : "text-success")}
		</div><div class="row">
			${celda(__("Precio sin IVA"), m(c.precio / (1 + IVA_GALERIA)))}
			${celda(__("Para el artista"), m(monto))}
			${celda(__("Ganancia de la galería"), m(gan), gan < 0 ? "text-danger" : "text-success")}
		</div>`;
		const aviso = (tipo, texto) =>
			`<div class="alert alert-${tipo} small" style="margin-bottom: var(--margin-sm)">${texto}</div>`;
		if (c.recibido <= 0) {
			html += aviso("warning", __("Falta el anticipo: registre el pago de hoy."));
		} else if (c.saldo < 0) {
			html += aviso("danger", __("Lo recibido supera el precio de la obra en {0}.", [m(-c.saldo)]));
		} else if (!hay_saldo) {
			html += aviso("success", __("La obra queda pagada por completo."));
		} else if (libres) {
			html += aviso("info", __("Quedan {0} que el cliente paga con abonos libres.", [m(c.saldo)]));
		} else {
			const n = cint((plan || "").replace(/\D/g, "")) || 1;
			html += aviso(
				"info",
				__("Quedan {0} en {1} cuotas mensuales de aproximadamente {2}; la primera vence en un mes.", [
					m(c.saldo),
					n,
					m(c.saldo / n),
				])
			);
		}
		const descuento = flt(o.precio_venta) - c.precio;
		if (descuento > 0 && monto === flt(o.monto_artista)) {
			html += aviso(
				"warning",
				__("Hay un descuento de {0} y el monto del artista no cambió: el descuento lo absorbe la galería.", [
					m(descuento),
				])
			);
		}
		if (gan < 0) html += aviso("danger", __("Con estos montos la galería pierde en esta obra."));
		d.fields_dict.resumen.$wrapper.html(html);
		// Sin anticipo o con un pago mayor al precio no se puede facturar.
		d.get_primary_btn().prop("disabled", c.recibido <= 0 || c.saldo < 0);
	};

	d.show();
	editor = galeria.pagos.editor(d.fields_dict.pagos.$wrapper, datos.modos_pago, () => resumen());
	resumen();
};

galeria.obras.venta_lista = function (r) {
	const m = galeria.pagos.moneda;
	const d = new frappe.ui.Dialog({
		title: __("Obra vendida"),
		fields: [{ fieldtype: "HTML", fieldname: "html" }],
		primary_action_label: __("Cerrar"),
		primary_action: () => d.hide(),
		secondary_action_label: __("Imprimir factura"),
		secondary_action: () => galeria.obras.imprimir("Sales Invoice", r.factura, "Factura Galería"),
	});
	const forma = r.plan_pagos
		? frappe.utils.escape_html(r.plan_pagos)
		: flt(r.pendiente) > 0
		? __("Saldo con abonos libres")
		: "";
	d.fields_dict.html.$wrapper.html(`
		<div class="text-center" style="padding: var(--padding-md) 0">
			<div class="text-muted">${__("Factura")}</div>
			<div class="h3" style="margin: 4px 0"><a href="/app/sales-invoice/${encodeURIComponent(r.factura)}">${frappe.utils.escape_html(r.factura)}</a></div>
			<div class="h4">${m(r.total)}</div>
			<div class="text-muted">${__("Pagado")}: ${m(r.pagado)} · ${__("Saldo")}: ${m(r.pendiente)}</div>
			<div class="text-muted">${forma}</div>
			${
				r.reservacion
					? `<div class="text-muted">${__("Reservación")} ${frappe.utils.escape_html(r.reservacion)} ${__("convertida en venta")}</div>`
					: ""
			}
		</div>`);
	d.show();
};

// Tarjeta con foto o, si no hay, un cuadro de color con las iniciales.
galeria.obras.html_imagen = function (imagen, texto, alto) {
	const colores = ["#4F46E5", "#0D9488", "#B45309", "#BE185D", "#2563EB", "#7C3AED", "#059669", "#C2410C"];
	const estilo = `height:${alto}px; background-size:cover; background-position:center; display:flex; align-items:center; justify-content:center; color:#fff; font-size:${Math.round(alto / 5)}px; font-weight:700; letter-spacing:1px;`;
	if (imagen) return `<div style="${estilo} background-image:url('${encodeURI(imagen)}')"></div>`;
	let h = 0;
	for (const c of texto || "") h = (h * 31 + c.charCodeAt(0)) >>> 0;
	const iniciales = (texto || "?")
		.split(/\s+/)
		.filter((p) => p.length > 2)
		.slice(0, 2)
		.map((p) => p[0].toUpperCase())
		.join("");
	return `<div style="${estilo} background:${colores[h % colores.length]}">${frappe.utils.escape_html(iniciales || "?")}</div>`;
};
