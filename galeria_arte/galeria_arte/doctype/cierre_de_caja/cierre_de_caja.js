// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cierre de Caja", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Recalcular"), () => recalcular(frm));
		}
		frm.set_intro(
			frm.doc.docstatus === 0
				? __("Ingrese lo contado en caja por cada forma de pago y valide para cerrar el día.")
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
		frappe.model.set_value(cdt, cdn, "diferencia", flt(row.contado) - flt(row.esperado));
		const total_contado = (frm.doc.pagos || []).reduce((s, p) => s + flt(p.contado), 0);
		frm.set_value("total_contado", total_contado);
		frm.set_value("diferencia", total_contado - flt(frm.doc.total_esperado));
	},
});

function recalcular(frm) {
	if (!frm.doc.fecha || !frm.doc.cajero || frm.doc.docstatus !== 0) return;
	frm.call({ doc: frm.doc, method: "calcular" }).then(() => frm.refresh_fields());
}
