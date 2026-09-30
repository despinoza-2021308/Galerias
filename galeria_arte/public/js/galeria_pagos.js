// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Diálogos de cobro de la galería: pagos mixtos, abonos y estado de cuenta.
// Se usan desde la factura, la pantalla de Cobros y el POS.

frappe.provide("galeria.pagos");

const API = "galeria_arte.api.facturacion";

galeria.pagos.es_factura_galeria = function (doc) {
	const prefijo = frappe.boot.galeria && frappe.boot.galeria.prefijo;
	return !!(prefijo && doc && doc.name && doc.name.startsWith(prefijo));
};

// "1 obra" / "3 obras"
galeria.pagos.cuantos = function (n, singular, plural) {
	return `${n || 0} ${cint(n) === 1 ? singular : plural}`;
};

galeria.pagos.moneda = function (valor) {
	return format_currency(valor || 0, "GTQ");
};

// Diálogo para registrar uno o varios pagos contra una factura.
galeria.pagos.registrar = async function (factura, on_done) {
	const [estado, opciones] = await Promise.all([
		frappe.xcall(`${API}.estado_factura`, { factura }),
		frappe.xcall(`${API}.opciones_cobro`),
	]);
	if (flt(estado.pendiente) <= 0) {
		frappe.msgprint(__("La factura {0} ya está pagada.", [factura]));
		return;
	}
	const proxima = (estado.cuotas || []).find((c) => flt(c.pendiente) > 0);
	const sugerido = proxima ? flt(proxima.pendiente) : flt(estado.pendiente);
	const modo_default = opciones.modos_pago.includes("Efectivo") ? "Efectivo" : opciones.modos_pago[0];

	const d = new frappe.ui.Dialog({
		title: __("Registrar pago · {0}", [factura]),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "resumen" },
			{
				fieldtype: "Table",
				fieldname: "pagos",
				label: __("Pagos (puede combinar varias formas de pago)"),
				cannot_add_rows: false,
				in_place_edit: true,
				data: [{ modo_pago: modo_default, monto: sugerido }],
				fields: [
					{
						fieldtype: "Select",
						fieldname: "modo_pago",
						label: __("Forma de pago"),
						options: opciones.modos_pago.join("\n"),
						in_list_view: 1,
						reqd: 1,
						columns: 3,
					},
					{
						fieldtype: "Currency",
						fieldname: "monto",
						label: __("Monto"),
						in_list_view: 1,
						reqd: 1,
						columns: 3,
					},
					{
						fieldtype: "Data",
						fieldname: "referencia",
						label: __("Referencia (boleta, voucher, transferencia)"),
						in_list_view: 1,
						columns: 4,
					},
				],
			},
		],
		primary_action_label: __("Registrar pago"),
		primary_action: async (values) => {
			const pagos = (values.pagos || []).filter((p) => flt(p.monto) > 0);
			const total = pagos.reduce((s, p) => s + flt(p.monto), 0);
			if (!pagos.length) {
				frappe.msgprint(__("Ingrese al menos un pago."));
				return;
			}
			if (flt(total, 2) > flt(estado.pendiente, 2)) {
				frappe.msgprint(
					__("El total ({0}) supera el saldo pendiente ({1}).", [
						galeria.pagos.moneda(total),
						galeria.pagos.moneda(estado.pendiente),
					])
				);
				return;
			}
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${API}.registrar_pagos`, { factura, pagos });
				d.hide();
				frappe.show_alert({
					message: __("Pago registrado. Saldo pendiente: {0}", [galeria.pagos.moneda(r.pendiente)]),
					indicator: "green",
				});
				on_done && on_done(r);
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.fields_dict.resumen.$wrapper.html(galeria.pagos.html_resumen(estado));
	d.show();
};

// Diálogo de solo lectura con cuotas y pagos.
galeria.pagos.estado_cuenta = async function (factura) {
	const estado = await frappe.xcall(`${API}.estado_factura`, { factura });
	const d = new frappe.ui.Dialog({
		title: __("Estado de cuenta · {0}", [factura]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "html" }],
	});
	d.fields_dict.html.$wrapper.html(
		galeria.pagos.html_resumen(estado) + galeria.pagos.html_pagos(estado)
	);
	d.show();
};

galeria.pagos.html_resumen = function (e) {
	const m = galeria.pagos.moneda;
	const fel_color = e.fel === "Certificada" ? "green" : "orange";
	let html = `
		<div class="row" style="margin-bottom: var(--margin-md)">
			<div class="col-sm-6">
				<div class="text-muted small">${__("Cliente")}</div>
				<div class="bold">${frappe.utils.escape_html(e.cliente || "")}</div>
				<span class="indicator-pill ${fel_color}" style="margin-top: 6px">FEL: ${e.fel}</span>
			</div>
			<div class="col-sm-2"><div class="text-muted small">${__("Total")}</div><div class="bold">${m(e.total)}</div></div>
			<div class="col-sm-2"><div class="text-muted small">${__("Pagado")}</div><div class="bold text-success">${m(e.pagado)}</div></div>
			<div class="col-sm-2"><div class="text-muted small">${__("Pendiente")}</div><div class="bold text-danger">${m(e.pendiente)}</div></div>
		</div>`;
	if ((e.cuotas || []).length) {
		html += `<div class="text-muted small" style="margin-bottom: 4px">${__("Plan de pagos")}: ${frappe.utils.escape_html(e.plan_pagos)}</div>
			<table class="table table-bordered table-sm small">
				<thead><tr><th>${__("Cuota")}</th><th>${__("Vence")}</th><th class="text-right">${__("Monto")}</th>
				<th class="text-right">${__("Pagado")}</th><th class="text-right">${__("Pendiente")}</th></tr></thead><tbody>`;
		const hoy = frappe.datetime.get_today();
		for (const c of e.cuotas) {
			const vencida = flt(c.pendiente) > 0 && c.vence < hoy;
			html += `<tr class="${vencida ? "text-danger" : ""}">
				<td>${frappe.utils.escape_html(c.cuota || "")}</td>
				<td>${frappe.datetime.str_to_user(c.vence)}${vencida ? " · " + __("Vencida") : ""}</td>
				<td class="text-right">${m(c.monto)}</td><td class="text-right">${m(c.pagado)}</td>
				<td class="text-right">${m(c.pendiente)}</td></tr>`;
		}
		html += `</tbody></table>`;
	}
	return html;
};

galeria.pagos.html_pagos = function (e) {
	if (!(e.pagos || []).length) return `<p class="text-muted">${__("Sin pagos registrados.")}</p>`;
	let html = `<div class="text-muted small" style="margin-bottom: 4px">${__("Pagos recibidos")}</div>
		<table class="table table-bordered table-sm small"><thead><tr><th>${__("Pago")}</th><th>${__("Fecha")}</th>
		<th>${__("Forma de pago")}</th><th>${__("Cuota")}</th><th class="text-right">${__("Monto")}</th></tr></thead><tbody>`;
	for (const p of e.pagos) {
		html += `<tr><td><a href="/app/payment-entry/${encodeURIComponent(p.name)}">${p.name}</a></td>
			<td>${frappe.datetime.str_to_user(p.posting_date)}</td><td>${frappe.utils.escape_html(p.mode_of_payment || "")}</td>
			<td>${frappe.utils.escape_html(p.cuota || "")}</td><td class="text-right">${galeria.pagos.moneda(p.monto)}</td></tr>`;
	}
	return html + `</tbody></table>`;
};

// Editor de pagos para diálogos: filas de forma de pago, monto y referencia.
// Devuelve { leer(), total(), poner(filas) } y avisa cada cambio con on_change.
galeria.pagos.editor = function ($wrapper, modos, on_change) {
	const esc = frappe.utils.escape_html;
	const $filas = $(`<div></div>`).appendTo($wrapper);
	const $agregar = $(
		`<button type="button" class="btn btn-xs btn-default" style="margin-top: 4px">+ ${__("Agregar forma de pago")}</button>`
	).appendTo($wrapper);
	const fila = (modo, monto) => `
		<div class="gal-fila-pago" style="display: grid; grid-template-columns: minmax(120px, 1.2fr) minmax(90px, 0.8fr) minmax(100px, 1fr) 38px; gap: 6px; margin-bottom: 6px">
			<select class="form-control" data-modo>${modos
				.map((mo) => `<option ${mo === modo ? "selected" : ""}>${esc(mo)}</option>`)
				.join("")}</select>
			<input type="number" min="0" step="0.01" inputmode="decimal" class="form-control" data-monto value="${monto || ""}" placeholder="${__("Monto")}">
			<input type="text" class="form-control" data-ref placeholder="${__("Referencia")}">
			<button type="button" class="btn btn-default" data-borrar aria-label="${__("Quitar pago")}">×</button>
		</div>`;
	const leer = () =>
		$filas
			.find(".gal-fila-pago")
			.map((_, el) => ({
				modo_pago: $(el).find("[data-modo]").val(),
				monto: flt($(el).find("[data-monto]").val()),
				referencia: $(el).find("[data-ref]").val() || null,
			}))
			.get()
			.filter((p) => p.monto > 0);
	const total = () => flt(leer().reduce((s, p) => s + p.monto, 0), 2);
	const avisar = () => on_change && on_change();
	const defecto = modos.includes("Efectivo") ? "Efectivo" : modos[0];

	$agregar.on("click", () => {
		const usados = leer().map((p) => p.modo_pago);
		$filas.append(fila(modos.find((mo) => !usados.includes(mo)) || defecto, ""));
		avisar();
	});
	$filas.on("click", "[data-borrar]", (e) => {
		$(e.currentTarget).closest(".gal-fila-pago").remove();
		avisar();
	});
	$filas.on("input change", "[data-monto], [data-modo]", avisar);

	const poner = (filas) => {
		$filas.html((filas || []).map((f) => fila(f.modo_pago || defecto, f.monto)).join(""));
		avisar();
	};
	$filas.html(fila(defecto, ""));
	return { leer, total, poner };
};
