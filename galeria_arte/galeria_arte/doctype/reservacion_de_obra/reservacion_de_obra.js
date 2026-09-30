// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Reservacion de Obra", {
	refresh(frm) {
		if (frm.is_new()) return;
		const d = frm.doc;
		const recargar = () => frm.reload_doc();
		const vencida = d.estado === "Activa" && d.fecha_limite && d.fecha_limite < frappe.datetime.get_today();
		const colores = { Activa: "green", "Convertida en venta": "blue", Cancelada: "gray" };
		frm.page.set_indicator(vencida ? __("Vencida") : d.estado, vencida ? "red" : colores[d.estado] || "gray");

		frm.set_intro("");
		if (vencida) {
			frm.set_intro(
				__("La reserva venció el {0}. La obra sigue apartada: decida si se vende, se extiende o se cancela.", [
					frappe.datetime.str_to_user(d.fecha_limite),
				]),
				"red"
			);
		} else if (d.estado === "Cancelada") {
			frm.set_intro(
				__("Reserva cancelada. Lo abonado ({0}) quedó como saldo a favor del cliente.", [
					galeria.pagos.moneda(d.total_abonado),
				]),
				"orange"
			);
		}

		if (d.estado === "Activa") {
			frm.add_custom_button(__("Vender la obra"), () => galeria.obras.vender(d.obra, recargar)).addClass("btn-primary");
			frm.add_custom_button(__("Abonar"), () => galeria.obras.abonar(d.name, d.saldo_obra, recargar));
			frm.add_custom_button(__("Extender fecha"), () => galeria.obras.extender(d.name, d.fecha_limite, recargar));
			frm.add_custom_button(__("Cancelar reserva"), () => galeria.obras.cancelar_reserva(d.name, recargar));
		}
		frm.add_custom_button(__("Imprimir recibo"), () =>
			galeria.obras.imprimir("Reservacion de Obra", d.name, "Recibo de Reserva")
		);
		frm.add_custom_button(__("Venta de obras"), () => {
			frappe.route_options = { pestana: "reservas" };
			frappe.set_route("venta-obras");
		});
	},
});
