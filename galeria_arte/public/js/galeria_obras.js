// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Acciones sobre una obra de arte: reservar, vender, cancelar reserva.
// Se usan desde la ficha de la obra y desde el catálogo.

frappe.provide("galeria.obras");

const OBRAS_API = "galeria_arte.api.obras";
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

// ---------------------------------------------------------------------------
// Reservar
// ---------------------------------------------------------------------------

galeria.obras.reservar = async function (obra, on_done) {
	const datos = await frappe.xcall(`${OBRAS_API}.datos_venta`, { obra });
	const o = datos.obra;
	const d = new frappe.ui.Dialog({
		title: __("Reservar · {0}", [o.titulo]),
		fields: [
			{ fieldtype: "Link", fieldname: "cliente", label: __("Cliente"), options: "Customer", reqd: 1 },
			{
				fieldtype: "Currency",
				fieldname: "anticipo",
				label: __("Anticipo"),
				reqd: 1,
				description: __("Precio de la obra: {0}", [galeria.pagos.moneda(o.precio_venta)]),
			},
			{
				fieldtype: "Select",
				fieldname: "modo_pago",
				label: __("Forma de pago"),
				options: datos.modos_pago.join("\n"),
				default: datos.modos_pago.includes("Efectivo") ? "Efectivo" : datos.modos_pago[0],
				reqd: 1,
			},
			{ fieldtype: "Data", fieldname: "referencia", label: __("Referencia (boleta, voucher, transferencia)") },
			{
				fieldtype: "Date",
				fieldname: "fecha_limite",
				label: __("Reservada hasta"),
				reqd: 1,
				default: frappe.datetime.add_days(frappe.datetime.get_today(), 7),
				description: __("Al pasar esta fecha el sistema avisa; la obra no se libera sola."),
			},
		],
		primary_action_label: __("Reservar"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				await frappe.xcall(`${OBRAS_API}.reservar`, { obra, ...v });
				d.hide();
				frappe.show_alert({ message: __("Obra reservada"), indicator: "green" });
				on_done && on_done();
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.show();
};

galeria.obras.cancelar_reserva = function (obra, on_done) {
	frappe.confirm(
		__("¿Cancelar la reserva? La obra vuelve a estar Disponible y el anticipo queda como saldo a favor del cliente."),
		async () => {
			const r = await frappe.xcall(`${OBRAS_API}.cancelar_reserva`, { obra });
			frappe.msgprint(
				__("Reserva cancelada. {0} tiene {1} de saldo a favor.", [
					r.cliente,
					galeria.pagos.moneda(r.saldo_a_favor),
				])
			);
			on_done && on_done();
		}
	);
};

// ---------------------------------------------------------------------------
// Vender
// ---------------------------------------------------------------------------

galeria.obras.vender = async function (obra, on_done) {
	const datos = await frappe.xcall(`${OBRAS_API}.datos_venta`, { obra });
	const o = datos.obra;
	const m = galeria.pagos.moneda;
	const reservada = o.estado === "Reservada";
	// Los campos disparan onchange al crearse el diálogo; el resumen real se asigna después.
	let resumen = () => {};

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
				default: o.reservada_por,
				read_only: reservada ? 1 : 0,
				description: reservada ? __("La obra está reservada por este cliente.") : "",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Select",
				fieldname: "plan_pagos",
				label: __("Forma de venta"),
				options: ["Contado", ...datos.planes_pago].join("\n"),
				default: "Contado",
				onchange: () => resumen(),
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
			{ fieldtype: "Section Break" },
			{ fieldtype: "HTML", fieldname: "resumen" },
			{
				fieldtype: "Table",
				fieldname: "pagos",
				label: __("Pago de hoy (opcional; puede combinar formas de pago)"),
				in_place_edit: true,
				data: [],
				fields: [
					{
						fieldtype: "Select",
						fieldname: "modo_pago",
						label: __("Forma de pago"),
						options: datos.modos_pago.join("\n"),
						in_list_view: 1,
						columns: 3,
					},
					{ fieldtype: "Currency", fieldname: "monto", label: __("Monto"), in_list_view: 1, columns: 3 },
					{ fieldtype: "Data", fieldname: "referencia", label: __("Referencia"), in_list_view: 1, columns: 4 },
				],
			},
		],
		primary_action_label: __("Facturar venta"),
		primary_action: async (v) => {
			const pagos = (v.pagos || []).filter((p) => p.modo_pago && flt(p.monto) > 0);
			const saldo = flt(flt(v.precio) - Math.min(datos.anticipo_disponible, flt(v.precio)), 2);
			const pagado = flt(pagos.reduce((s, p) => s + flt(p.monto), 0), 2);
			if (pagado > saldo) {
				frappe.msgprint(__("El pago de hoy ({0}) supera el saldo de la obra ({1}).", [m(pagado), m(saldo)]));
				return;
			}
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${OBRAS_API}.vender`, {
					obra,
					cliente: v.cliente,
					precio: v.precio,
					monto_artista: v.monto_artista,
					plan_pagos: v.plan_pagos === "Contado" ? null : v.plan_pagos,
					pagos,
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
		const precio = flt(d.get_value("precio"));
		const monto = flt(d.get_value("monto_artista"));
		const gan = galeria.obras.ganancia(precio, monto);
		const anticipo = Math.min(datos.anticipo_disponible, precio);
		const descuento = flt(o.precio_venta) - precio;
		const celda = (label, valor, clase = "") =>
			`<div class="col-sm-3"><div class="text-muted small">${label}</div><div class="bold ${clase}">${valor}</div></div>`;
		let html = `<div class="row" style="margin-bottom: var(--margin-md)">
			${celda(__("Precio sin IVA"), m(precio / (1 + IVA_GALERIA)))}
			${celda(__("Para el artista"), m(monto))}
			${celda(__("Ganancia de la galería"), m(gan), gan < 0 ? "text-danger" : "text-success")}
			${celda(anticipo > 0 ? __("Saldo tras el anticipo") : __("Total a cobrar"), m(precio - anticipo))}
		</div>`;
		if (anticipo > 0) {
			html += `<div class="alert alert-info small" style="margin-bottom: var(--margin-sm)">${__(
				"Se aplica el anticipo de la reserva: {0}.",
				[m(anticipo)]
			)}</div>`;
		}
		if (descuento > 0 && monto === flt(o.monto_artista)) {
			html += `<div class="alert alert-warning small" style="margin-bottom: var(--margin-sm)">${__(
				"Hay un descuento de {0} y el monto del artista no cambió: el descuento lo absorbe la galería.",
				[m(descuento)]
			)}</div>`;
		}
		if (gan < 0) {
			html += `<div class="alert alert-danger small" style="margin-bottom: var(--margin-sm)">${__(
				"Con estos montos la galería pierde en esta obra."
			)}</div>`;
		}
		d.fields_dict.resumen.$wrapper.html(html);
	};

	d.show();
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
		secondary_action: () => {
			window.open(
				"/printview?doctype=Sales%20Invoice&name=" +
					encodeURIComponent(r.factura) +
					"&format=" +
					encodeURIComponent("Factura Galería") +
					"&no_letterhead=1&trigger_print=1",
				"_blank"
			);
		},
	});
	d.fields_dict.html.$wrapper.html(`
		<div class="text-center" style="padding: var(--padding-md) 0">
			<div class="text-muted">${__("Factura")}</div>
			<div class="h3" style="margin: 4px 0"><a href="/app/sales-invoice/${encodeURIComponent(r.factura)}">${frappe.utils.escape_html(r.factura)}</a></div>
			<div class="h4">${m(r.total)}</div>
			<div class="text-muted">${__("Pagado")}: ${m(r.pagado)} · ${__("Pendiente")}: ${m(r.pendiente)}</div>
			${r.plan_pagos ? `<div class="text-muted">${frappe.utils.escape_html(r.plan_pagos)}</div>` : ""}
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
