// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Liquidacion a Artista", {
	refresh(frm) {
		if (frm.is_new()) return;
		const d = frm.doc;
		const recargar = () => frm.reload_doc();
		frm.page.set_indicator(d.estado, galeria.artistas.COLORES_LIQUIDACION[d.estado] || "gray");

		if (d.estado === "Por pagar") {
			frm.add_custom_button(__("Registrar pago"), () => galeria.artistas.pagar(d.name, d.total, recargar)).addClass("btn-primary");
		}
		if (d.estado !== "Anulada") {
			frm.add_custom_button(__("Anular"), () => galeria.artistas.anular(d.name, d.estado === "Pagada", recargar));
		}
		frm.add_custom_button(__("Imprimir comprobante"), () =>
			galeria.obras.imprimir("Liquidacion a Artista", d.name, "Comprobante de Liquidación")
		);
		frm.add_custom_button(__("Pagos a artistas"), () => frappe.set_route("pagos-artistas"));
	},
});
