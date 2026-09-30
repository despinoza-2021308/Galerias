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

// Texto corto del plan de pago de una factura para las tablas:
// "3 de 9 cuotas pagadas", "Abonos libres" o "Contado".
galeria.pagos.texto_plan = function (f) {
	const c = f.cuotas;
	if (c && c.total) {
		return __("{0} de {1} cuotas pagadas", [c.pagadas, c.total]);
	}
	if (flt(f.outstanding_amount) > 0) return __("Abonos libres");
	return __("Contado");
};

// Detalle debajo del plan: próxima cuota o fecha límite de los abonos.
galeria.pagos.detalle_plan = function (f) {
	const c = f.cuotas;
	if (c && c.proxima_vence) {
		return __("Próxima: {0} · {1}", [frappe.datetime.str_to_user(c.proxima_vence), galeria.pagos.moneda(c.proximo_monto)]);
	}
	if (!(c && c.total) && flt(f.outstanding_amount) > 0 && f.due_date) {
		return __("Pagar antes del {0}", [frappe.datetime.str_to_user(f.due_date)]);
	}
	return "";
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
	const m = galeria.pagos.moneda;
	const pendiente = flt(estado.pendiente);
	const sugerido = estado.proxima ? Math.min(flt(estado.proxima.monto), pendiente) : pendiente;
	let editor = null;

	const d = new frappe.ui.Dialog({
		title: __("Registrar pago · {0}", [factura]),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "resumen" },
			{ fieldtype: "Section Break", label: __("Pago de hoy") },
			{ fieldtype: "HTML", fieldname: "rapidos" },
			{ fieldtype: "HTML", fieldname: "pagos" },
			{ fieldtype: "HTML", fieldname: "total" },
		],
		primary_action_label: __("Registrar pago"),
		primary_action: async () => {
			const pagos = editor.leer();
			const total = editor.total();
			if (!pagos.length) {
				frappe.msgprint(__("Ingrese al menos un pago."));
				return;
			}
			if (total > flt(pendiente, 2)) {
				frappe.msgprint(__("El total ({0}) supera el saldo pendiente ({1}).", [m(total), m(pendiente)]));
				return;
			}
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${API}.registrar_pagos`, { factura, pagos });
				d.hide();
				frappe.show_alert({
					message: __("Pago registrado. Saldo pendiente: {0}", [m(r.pendiente)]),
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

	d.fields_dict.resumen.$wrapper.html(galeria.pagos.html_resumen(estado));
	const rapidos = [];
	if (estado.proxima) {
		rapidos.push(`<button type="button" class="btn btn-default" data-monto-rapido="${sugerido}">
			${__("Próxima cuota")} · ${m(sugerido)}</button>`);
	}
	rapidos.push(`<button type="button" class="btn btn-default" data-monto-rapido="${pendiente}">
		${__("Todo el saldo")} · ${m(pendiente)}</button>`);
	d.fields_dict.rapidos.$wrapper.html(`<div class="gal-rapidos">${rapidos.join("")}</div>`);

	const actualizar = () => {
		const total = editor ? editor.total() : 0;
		const queda = flt(pendiente - total, 2);
		d.fields_dict.total.$wrapper.html(`
			<div class="gal-total-pago">
				<span>${__("Pago de hoy")}: <b>${m(total)}</b></span>
				<span class="${queda < 0 ? "text-danger" : ""}">${
					queda < 0 ? __("Supera el saldo por {0}", [m(-queda)]) : __("Quedará pendiente: {0}", [m(queda)])
				}</span>
			</div>`);
		d.get_primary_btn().prop("disabled", total <= 0 || queda < 0);
	};

	d.show();
	editor = galeria.pagos.editor(d.fields_dict.pagos.$wrapper, opciones.modos_pago, actualizar);
	editor.poner([{ monto: sugerido }]);
	d.fields_dict.rapidos.$wrapper.on("click", "[data-monto-rapido]", (e) => {
		editor.poner([{ monto: flt($(e.currentTarget).attr("data-monto-rapido")) }]);
	});
	actualizar();
};

// Diálogo de solo lectura con cuotas y pagos.
galeria.pagos.estado_cuenta = async function (factura) {
	const estado = await frappe.xcall(`${API}.estado_factura`, { factura });
	const d = new frappe.ui.Dialog({
		title: __("Estado de cuenta · {0}", [factura]),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "html" }],
	});
	d.fields_dict.html.$wrapper.html(galeria.pagos.html_resumen(estado) + galeria.pagos.html_pagos(estado));
	d.show();
};

galeria.pagos.COLORES_CUOTA = { Pagada: "green", Próxima: "blue", Vencida: "red", Pendiente: "gray" };

galeria.pagos.html_resumen = function (e) {
	const m = galeria.pagos.moneda;
	const esc = frappe.utils.escape_html;
	const dato = (label, valor, clase = "") =>
		`<div><div class="gal-dato-label">${label}</div><div class="gal-dato-valor ${clase}">${valor}</div></div>`;
	let html = `
		<div class="gal-resumen">
			<div>
				<div class="gal-dato-label">${__("Cliente")}</div>
				<div class="gal-dato-valor">${esc(e.cliente || "")}</div>
				<span class="indicator-pill ${e.fel === "Certificada" ? "green" : "orange"}" style="margin-top: 6px">FEL: ${e.fel}</span>
			</div>
			${dato(__("Total"), m(e.total))}
			${dato(__("Pagado"), m(e.pagado), "text-success")}
			${dato(__("Pendiente"), m(e.pendiente), flt(e.pendiente) > 0 ? "text-danger" : "")}
		</div>`;

	// Desglose de lo pagado: anticipo y pagos posteriores.
	const partes = [];
	if (flt(e.anticipo) > 0) partes.push(`${__("Anticipo")}: <b>${m(e.anticipo)}</b>`);
	const despues = flt(e.pagado) - flt(e.anticipo);
	if (flt(e.anticipo) > 0 && despues > 0.005) partes.push(`${__("Pagos posteriores")}: <b>${m(despues)}</b>`);
	if (!e.cuotas.length && flt(e.pendiente) > 0 && e.vence) {
		partes.push(`${__("Abonos libres, pagar antes del")} <b>${frappe.datetime.str_to_user(e.vence)}</b>`);
	}
	if (partes.length) html += `<div class="gal-desglose">${partes.map((p) => `<span>${p}</span>`).join("")}</div>`;

	if (e.cuotas.length) {
		const faltan = e.cuotas_total - e.cuotas_pagadas;
		const pct = e.cuotas_total ? Math.round((e.cuotas_pagadas / e.cuotas_total) * 100) : 0;
		html += `
			<div class="gal-progreso">
				<div class="gal-progreso-texto">
					<span><b>${__("{0} de {1} cuotas pagadas", [e.cuotas_pagadas, e.cuotas_total])}</b>${
			faltan ? ` · ${faltan === 1 ? __("falta 1") : __("faltan {0}", [faltan])}` : ` · ${__("completo")}`
		}</span>
					<span class="text-muted">${esc(e.plan_pagos || "")}${
			flt(e.anticipo) > 0 ? ` · ${__("calculadas sobre el saldo después del anticipo")}` : ""
		}</span>
				</div>
				<div class="gal-progreso-barra"><div style="width: ${pct}%"></div></div>
			</div>
			<table class="gal-cuotas">
				<thead><tr><th>${__("Cuota")}</th><th>${__("Vence")}</th><th class="text-right">${__("Monto")}</th>
					<th class="text-right">${__("Pagado")}</th><th class="text-right">${__("Pendiente")}</th><th>${__("Estado")}</th></tr></thead>
				<tbody>${e.cuotas
					.map(
						(c) => `<tr class="${{ Pagada: "pagada", Próxima: "proxima", Vencida: "vencida" }[c.estado] || ""}">
						<td>${esc(c.cuota || "")}</td>
						<td>${frappe.datetime.str_to_user(c.vence)}</td>
						<td class="text-right">${m(c.monto)}</td>
						<td class="text-right">${m(c.pagado)}</td>
						<td class="text-right">${flt(c.pendiente) > 0 ? m(c.pendiente) : "—"}</td>
						<td><span class="indicator-pill ${galeria.pagos.COLORES_CUOTA[c.estado] || "gray"}">${c.estado === "Pagada" ? "✓ " : ""}${esc(c.estado)}</span></td>
					</tr>`
					)
					.join("")}</tbody>
			</table>`;
	}
	return html;
};

galeria.pagos.html_pagos = function (e) {
	if (!(e.pagos || []).length) return `<p class="text-muted">${__("Sin pagos registrados.")}</p>`;
	const esc = frappe.utils.escape_html;
	return `<div class="gal-dato-label" style="margin-bottom: 4px">${__("Pagos recibidos")}</div>
		<table class="gal-cuotas"><thead><tr><th>${__("Fecha")}</th><th>${__("Tipo")}</th><th>${__("Forma de pago")}</th>
		<th>${__("Aplicado a")}</th><th class="text-right">${__("Monto")}</th><th>${__("Pago")}</th></tr></thead><tbody>${e.pagos
			.map(
				(p) => `<tr>
			<td>${frappe.datetime.str_to_user(p.posting_date)}</td>
			<td>${p.tipo === "Anticipo" ? `<span class="indicator-pill blue">${__("Anticipo")}</span>` : __("Pago")}</td>
			<td>${esc(p.mode_of_payment || "")}</td>
			<td>${esc(p.cuota || (p.tipo === "Anticipo" ? __("Antes de las cuotas") : __("Saldo")))}</td>
			<td class="text-right">${galeria.pagos.moneda(p.monto)}</td>
			<td><a href="/app/payment-entry/${encodeURIComponent(p.name)}">${esc(p.name)}</a></td></tr>`
			)
			.join("")}</tbody></table>`;
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
