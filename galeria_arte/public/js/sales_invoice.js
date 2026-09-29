// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Botones de la galería en la Factura de Venta. La certificación FEL la
// sigue manejando el botón "Certifica FEL" de Brainfel.

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (!galeria.pagos.es_factura_galeria(frm.doc) || frm.doc.docstatus !== 1) return;

		const certificada = frm.doc.bfel_status === "02 Procesada" && frm.doc.bfel_uuid;
		frm.dashboard.add_indicator(
			certificada ? __("FEL: Certificada") : __("FEL: Pendiente de certificar"),
			certificada ? "green" : "orange"
		);

		if (flt(frm.doc.outstanding_amount) > 0) {
			frm.add_custom_button(
				__("Registrar pago"),
				() => galeria.pagos.registrar(frm.doc.name, () => frm.reload_doc()),
				__("Galería")
			);
		}
		frm.add_custom_button(
			__("Estado de cuenta"),
			() => galeria.pagos.estado_cuenta(frm.doc.name),
			__("Galería")
		);
	},

	naming_series(frm) {
		// Una factura nueva con la serie de la galería usa su IVA incluido y su lista de precios.
		const conf = frappe.boot.galeria;
		if (!conf || frm.doc.docstatus !== 0 || frm.doc.naming_series !== conf.serie_factura) return;
		if (conf.plantilla_impuestos && frm.doc.taxes_and_charges !== conf.plantilla_impuestos) {
			frm.set_value("taxes_and_charges", conf.plantilla_impuestos);
		}
		if (conf.lista_precios_publico && !frm.doc.selling_price_list) {
			frm.set_value("selling_price_list", conf.lista_precios_publico);
		}
	},
});
