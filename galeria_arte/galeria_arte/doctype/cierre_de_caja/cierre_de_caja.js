// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Orden fijo de las áreas en el desglose; siempre se muestran las cuatro principales.
const CIERRE_ORIGENES = ["Cafetería", "Obras de arte", "Eventos – boletos", "Eventos – alquileres"];

frappe.ui.form.on("Cierre de Caja", {
	refresh(frm) {
		pintar_desglose(frm);
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Recalcular"), () => recalcular(frm));
		}
		frm.set_intro(
			frm.doc.docstatus === 0
				? __(
						"Cuente el efectivo y escríbalo en Contado. Tarjeta, transferencia y cheque se llenan solos con lo registrado: cámbielos solo si no coinciden con los vouchers o el banco. Luego valide para cerrar el día."
				  )
				: ""
		);
	},
	onload(frm) {
		if (frm.is_new()) recalcular(frm);
	},
	fecha: recalcular,
	cajero: recalcular,
});

frappe.ui.form.on("Cierre de Caja Pago", {
	contado(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		// Si el cajero corrige una tarjeta o transferencia, se respeta al recalcular.
		if (!row.es_efectivo && !row.contado_manual && flt(row.contado) !== flt(row.esperado)) {
			frappe.model.set_value(cdt, cdn, "contado_manual", 1);
		}
		frappe.model.set_value(cdt, cdn, "diferencia", flt(row.contado) - flt(row.esperado));
		const total_contado = (frm.doc.pagos || []).reduce((s, p) => s + flt(p.contado), 0);
		frm.set_value("total_contado", total_contado);
		frm.set_value("diferencia", total_contado - flt(frm.doc.total_esperado));
		pintar_desglose(frm);
	},
});

// Tablas de "De dónde viene el dinero": resumen por área y una tabla por forma de pago.
function pintar_desglose(frm) {
	const campo = frm.fields_dict.desglose_html;
	if (!campo) return;
	const m = (v) => format_currency(v, frappe.defaults.get_default("currency") || "GTQ");
	const esc = frappe.utils.escape_html;
	const filas = frm.doc.origenes || [];
	if (!filas.length) {
		campo.$wrapper.html(`<div class="text-muted">${__("No hay cobros registrados en este día.")}</div>`);
		return;
	}
	const boletos = cint(frm.doc.boletos_vendidos);
	const etiqueta = (o) => (o === "Eventos – boletos" && boletos ? `${__(o)} <span class="text-muted">(${boletos} ${__("boletos")})</span>` : __(o));
	const extras = [...new Set(filas.filter((f) => !f.es_egreso).map((f) => f.origen))].filter((o) => !CIERRE_ORIGENES.includes(o));
	const origenes = CIERRE_ORIGENES.concat(extras);
	const celda = "padding: 4px 8px; border-bottom: 1px solid var(--border-color)";

	const por_area = origenes.map((o) => ({ o, monto: filas.filter((f) => f.origen === o).reduce((s, f) => s + flt(f.monto), 0) }));
	const total_ingresos = por_area.reduce((s, x) => s + x.monto, 0);
	let html = `<div style="font-weight: 600; margin-bottom: 4px">${__("Resumen por área (todas las formas de pago)")}</div>
		<table style="width: 100%; max-width: 560px; margin-bottom: var(--margin-lg)"><tbody>
		${por_area.map((x) => `<tr><td style="${celda}">${etiqueta(x.o)}</td><td style="${celda}; text-align: right">${m(x.monto)}</td></tr>`).join("")}
		<tr><td style="${celda}; font-weight: 600">${__("Total cobrado")}</td><td style="${celda}; text-align: right; font-weight: 600">${m(total_ingresos)}</td></tr>
		</tbody></table>`;

	const modos = [...new Set(filas.map((f) => f.modo_pago))];
	html += `<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: var(--margin-md)">`;
	for (const modo of modos) {
		const de_modo = filas.filter((f) => f.modo_pago === modo);
		const ingresos = de_modo.filter((f) => !f.es_egreso);
		const egresos = de_modo.filter((f) => f.es_egreso).reduce((s, f) => s + flt(f.monto), 0);
		const total = ingresos.reduce((s, f) => s + flt(f.monto), 0);
		const pago = (frm.doc.pagos || []).find((p) => p.modo_pago === modo) || {};
		html += `<div style="border: 1px solid var(--border-color); border-radius: var(--border-radius-lg); padding: var(--padding-sm) var(--padding-md)">
			<div style="font-weight: 600; margin-bottom: 4px">${esc(modo || __("Sin forma de pago"))}</div>
			<table style="width: 100%"><tbody>
			${origenes
				.map((o) => {
					const monto = ingresos.filter((f) => f.origen === o).reduce((s, f) => s + flt(f.monto), 0);
					return `<tr><td style="${celda}">${etiqueta(o)}</td><td style="${celda}; text-align: right">${m(monto)}</td></tr>`;
				})
				.join("")}
			<tr><td style="${celda}; font-weight: 600">${__("Total cobrado")}</td><td style="${celda}; text-align: right; font-weight: 600">${m(total)}</td></tr>
			${egresos ? `<tr><td style="${celda}">(−) ${__("Pagos a artistas")}</td><td style="${celda}; text-align: right">${m(egresos)}</td></tr>` : ""}
			<tr><td style="${celda}; font-weight: 600">${__("Esperado en caja")}</td><td style="${celda}; text-align: right; font-weight: 600">${m(total - egresos)}</td></tr>
			<tr><td style="${celda}">${pago.es_efectivo ? __("Contado") : __("Registrado")}</td><td style="${celda}; text-align: right">${m(pago.contado)}</td></tr>
			<tr><td style="padding: 4px 8px">${__("Diferencia")}</td><td style="padding: 4px 8px; text-align: right" class="${
				flt(pago.diferencia) ? "text-danger" : "text-success"
			}">${m(pago.diferencia)}</td></tr>
			</tbody></table></div>`;
	}
	html += `</div>`;
	campo.$wrapper.html(html);
}

function recalcular(frm) {
	if (!frm.doc.fecha || !frm.doc.cajero || frm.doc.docstatus !== 0) return;
	frm.call({ doc: frm.doc, method: "calcular" }).then(() => {
		frm.refresh_fields();
		pintar_desglose(frm);
	});
}
