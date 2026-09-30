// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Obra de Arte", {
	refresh(frm) {
		if (frm.is_new()) return;
		const estado = frm.doc.estado;
		const recargar = () => frm.reload_doc();

		frm.page.set_indicator(estado, galeria.obras.COLORES_ESTADO[estado] || "gray");
		mostrar_aviso(frm);

		if (estado === "Disponible") {
			frm.add_custom_button(__("Vender"), () => galeria.obras.vender(frm.doc.name, recargar)).addClass("btn-primary");
			frm.add_custom_button(__("Reservar"), () => galeria.obras.reservar(frm.doc.name, recargar));
			frm.add_custom_button(
				__("Devolver al artista"),
				() =>
					frappe.confirm(__("¿Registrar que la obra se devolvió al artista?"), async () => {
						await frappe.xcall("galeria_arte.api.obras.devolver_al_artista", { obra: frm.doc.name });
						recargar();
					}),
				__("Más")
			);
		}
		if (estado === "Reservada") {
			frm.add_custom_button(__("Vender"), () => galeria.obras.vender(frm.doc.name, recargar)).addClass("btn-primary");
			frm.add_custom_button(__("Cancelar reserva"), () => galeria.obras.cancelar_reserva(frm.doc.name, recargar));
		}
		if (estado === "Vendida" && frm.doc.factura) {
			frm.add_custom_button(__("Estado de cuenta"), () => galeria.pagos.estado_cuenta(frm.doc.factura));
			frm.add_custom_button(__("Ver factura"), () => frappe.set_route("Form", "Sales Invoice", frm.doc.factura));
		}
		if (estado === "Devuelta al artista") {
			frm.add_custom_button(__("Volver a ingresar"), async () => {
				await frappe.xcall("galeria_arte.api.obras.reingresar", { obra: frm.doc.name });
				recargar();
			});
		}
		if (estado !== "Vendida") {
			frm.add_custom_button(__("Clientes interesados"), () => clientes_interesados(frm), __("Más"));
		}
		frm.add_custom_button(__("Ver en el catálogo"), () => frappe.set_route("catalogo-obras"), __("Más"));

		// Vendida: el precio y el monto del artista quedaron congelados en la factura.
		frm.toggle_enable(["precio_venta", "monto_artista"], estado !== "Vendida");
	},

	precio_venta: calcular_ganancia,
	monto_artista: calcular_ganancia,
});

function calcular_ganancia(frm) {
	frm.set_value("ganancia_galeria", galeria.obras.ganancia(frm.doc.precio_venta, frm.doc.monto_artista));
}

function mostrar_aviso(frm) {
	const d = frm.doc;
	const m = galeria.pagos.moneda;
	frm.set_intro("");
	if (d.estado === "Reservada") {
		const vencida = d.fecha_limite_reserva && d.fecha_limite_reserva < frappe.datetime.get_today();
		frm.set_intro(
			vencida
				? __("La reserva de {0} venció el {1} (anticipo {2}). Decida si se vende o se cancela la reserva.", [
						d.reservada_por,
						frappe.datetime.str_to_user(d.fecha_limite_reserva),
						m(d.anticipo),
				  ])
				: __("Reservada por {0} hasta el {1} (anticipo {2}).", [
						d.reservada_por,
						frappe.datetime.str_to_user(d.fecha_limite_reserva),
						m(d.anticipo),
				  ]),
			vencida ? "red" : "yellow"
		);
	} else if (d.estado === "Vendida") {
		frm.set_intro(
			__("Vendida a {0} el {1} en {2}. Para el artista: {3}.", [
				d.cliente,
				frappe.datetime.str_to_user(d.fecha_venta),
				m(d.precio_vendido),
				m(d.monto_artista_venta),
			]),
			"green"
		);
	} else if (
		d.estado === "Disponible" &&
		d.fecha_limite_consignacion &&
		d.fecha_limite_consignacion < frappe.datetime.get_today()
	) {
		frm.set_intro(
			__("La consignación venció el {0}.", [frappe.datetime.str_to_user(d.fecha_limite_consignacion)]),
			"orange"
		);
	}
}

async function clientes_interesados(frm) {
	const lista = await frappe.xcall("galeria_arte.api.obras.interesados", { artista: frm.doc.artista });
	const esc = frappe.utils.escape_html;
	const filas = lista
		.map(
			(c) => `<tr><td><a href="/app/ficha-coleccionista?cliente=${encodeURIComponent(c.name)}">${esc(c.customer_name)}</a></td>
				<td>${esc(c.tipo || "")}</td><td>${esc(c.mobile_no || "")}</td><td>${esc(c.email_id || "")}</td></tr>`
		)
		.join("");
	frappe.msgprint({
		title: __("Clientes interesados en {0}", [frm.doc.artista]),
		wide: true,
		message: lista.length
			? `<table class="table table-bordered table-sm"><thead><tr><th>${__("Cliente")}</th><th>${__("Tipo")}</th>
				<th>${__("Teléfono")}</th><th>${__("Correo")}</th></tr></thead><tbody>${filas}</tbody></table>`
			: __("Ningún cliente tiene a este artista entre sus artistas de interés."),
	});
}
