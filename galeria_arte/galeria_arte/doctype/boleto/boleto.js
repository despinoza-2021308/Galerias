// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Boleto", {
	refresh(frm) {
		const colores = { Válido: "green", Usado: "blue", Anulado: "red" };
		frm.page.set_indicator(frm.doc.estado, colores[frm.doc.estado] || "gray");
		if (frm.is_new()) return;
		frm.add_custom_button(__("Ver boleto"), () => window.open(galeria.boletos.url(frm.doc.codigo), "_blank"));
		frm.add_custom_button(__("Imprimir"), () => galeria.boletos.imprimir([frm.doc.name]));
		if (frm.doc.estado === "Válido") {
			frm.add_custom_button(__("Enviar por correo"), () => galeria.boletos.enviar([frm.doc.name], frm.doc.correo), __("Más"));
		}
	},
});
