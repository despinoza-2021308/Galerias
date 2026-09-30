// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Artista", {
	async refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Nueva obra"), () => frappe.new_doc("Obra de Arte", { artista: frm.doc.name }));
		frm.add_custom_button(__("Ver sus obras"), () => {
			frappe.route_options = { artista: frm.doc.name };
			frappe.set_route("catalogo-obras");
		});
		const r = await frm.call("resumen");
		const resumen = r.message || {};
		frm.dashboard.clear_headline();
		for (const estado of ["Disponible", "Reservada", "Vendida", "Devuelta al artista"]) {
			if (resumen[estado]) {
				frm.dashboard.add_indicator(
					`${estado}: ${resumen[estado]}`,
					galeria.obras.COLORES_ESTADO[estado] || "gray"
				);
			}
		}
	},
});
