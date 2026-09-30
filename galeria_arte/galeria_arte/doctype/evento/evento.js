// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Evento", {
	setup(frm) {
		frm.set_query("obra", "lotes", () => ({ filters: { estado: "Disponible" } }));
	},

	refresh(frm) {
		const d = frm.doc;
		preparar_lotes(frm);
		if (frm.is_new()) return;
		const recargar = () => frm.reload_doc();
		frm.page.set_indicator(d.estado, galeria.eventos.COLORES_ESTADO[d.estado] || "gray");
		mostrar_aviso(frm);

		if (d.tipo !== "Alquiler" && d.estado === "Planificado") {
			frm.add_custom_button(__("Publicar"), () => galeria.eventos.publicar(d.name, recargar)).addClass("btn-primary");
		}
		if (d.tipo === "Subasta" && ["Planificado", "Publicado"].includes(d.estado)) {
			frm.add_custom_button(__("Agregar obra"), () => galeria.eventos.agregar_obra(d.name, recargar));
		}
		if (d.tipo === "Subasta" && d.estado === "Realizado") {
			frm.add_custom_button(__("Resultados y cobros"), () => galeria.eventos.resumen(d.name, recargar)).addClass("btn-primary");
		}
		if (d.tipo === "Cena" && d.estado === "Publicado" && cint(d.cupo) > cint(d.lugares_vendidos)) {
			frm.add_custom_button(__("Vender boletos"), () => galeria.eventos.vender_boletos(d.name, recargar)).addClass("btn-primary");
		}
		if (d.tipo === "Alquiler" && d.estado === "Tentativo") {
			frm.add_custom_button(__("Confirmar con anticipo"), () => galeria.eventos.confirmar(d.name, d.total_alquiler, recargar)).addClass(
				"btn-primary"
			);
		}
		if (d.tipo === "Alquiler" && d.estado === "Confirmado") {
			frm.add_custom_button(__("Registrar abono"), () => galeria.eventos.abonar(d.name, d.saldo, recargar)).addClass("btn-primary");
		}
		if ((d.tipo !== "Alquiler" && ["Planificado", "Publicado"].includes(d.estado)) || (d.tipo === "Alquiler" && d.estado === "Liquidado")) {
			frm.add_custom_button(__("Marcar realizado"), () => galeria.eventos.realizado(d.name, recargar), __("Más"));
		}
		if (!["Cancelado", "Vencido", "Realizado", "Liquidado"].includes(d.estado)) {
			frm.add_custom_button(
				__("Cancelar evento"),
				() =>
					galeria.eventos.cancelar(
						d.name,
						{ tipo: d.tipo, vendidos: d.lugares_vendidos, abonado: d.total_abonado },
						recargar
					),
				__("Más")
			);
		}
		frm.add_custom_button(__("Ver en el calendario"), () => frappe.set_route("calendario-galeria"), __("Más"));
	},

	sala: poner_precio,
	todo_el_espacio: poner_precio,
	estado: preparar_lotes,
});

frappe.ui.form.on("Evento Lote", {
	async obra(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.obra || flt(row.precio_inicial)) return;
		const r = await frappe.db.get_value("Obra de Arte", row.obra, "precio_venta");
		if (r.message) frappe.model.set_value(cdt, cdn, "precio_inicial", r.message.precio_venta);
	},
});

// Subasta: las obras se agregan antes del evento; el precio ganador y el
// comprador se registran cuando ya se realizó.
function preparar_lotes(frm) {
	const grid = frm.fields_dict.lotes && frm.fields_dict.lotes.grid;
	if (!grid) return;
	const antes = frm.is_new() || ["Planificado", "Publicado"].includes(frm.doc.estado);
	const realizada = frm.doc.estado === "Realizado";
	grid.update_docfield_property("obra", "read_only", antes ? 0 : 1);
	grid.update_docfield_property("precio_inicial", "read_only", antes ? 0 : 1);
	for (const campo of ["precio_ganador", "comprador", "sin_venta"]) {
		grid.update_docfield_property(campo, "read_only", realizada ? 0 : 1);
	}
	grid.cannot_add_rows = !antes;
	grid.cannot_delete_rows = !antes;
	grid.refresh();
}

// Alquiler: el precio base sale de la sala (o de todo el espacio) si aún no tiene uno.
async function poner_precio(frm) {
	if (frm.doc.tipo !== "Alquiler" || frm.doc.factura) return;
	const datos = await frappe.xcall("galeria_arte.api.eventos.datos_formulario");
	const precio = frm.doc.todo_el_espacio
		? datos.precio_todo
		: flt((datos.salas.find((s) => s.name === frm.doc.sala) || {}).precio_alquiler);
	if (precio) frm.set_value("precio_alquiler", precio);
}

function mostrar_aviso(frm) {
	const d = frm.doc;
	const m = galeria.pagos.moneda;
	frm.set_intro("");
	if (d.tipo === "Alquiler" && d.estado === "Tentativo" && d.vence_tentativa) {
		frm.set_intro(__("Apartado hasta el {0}. Si no deja anticipo, la fecha se libera.", [frappe.datetime.str_to_user(d.vence_tentativa)]), "orange");
	} else if (d.tipo === "Alquiler" && d.estado === "Confirmado" && flt(d.saldo) > 0) {
		frm.set_intro(__("Saldo pendiente de {0}: debe pagarse antes del evento.", [m(d.saldo)]), "red");
	} else if (d.tipo === "Cena") {
		frm.set_intro(__("{0} de {1} lugares vendidos.", [cint(d.lugares_vendidos), cint(d.cupo)]), "blue");
	} else if (d.tipo === "Subasta") {
		const lotes = d.lotes || [];
		const cuenta = (r) => lotes.filter((l) => l.resultado === r).length;
		if (d.estado === "Realizado") {
			const partes = [__("{0} de {1} obras vendidas", [cuenta("Adjudicada") + cuenta("Pagada"), lotes.length])];
			if (cuenta("Adjudicada")) partes.push(__("{0} por pagar", [cuenta("Adjudicada")]));
			if (cuenta("Pendiente")) partes.push(__("falta el resultado de {0}", [cuenta("Pendiente")]));
			frm.set_intro(
				partes.join(" · ") + ". " + __("El comprador paga al contado en 7 días; cobre desde «Resultados y cobros»."),
				cuenta("Pendiente") || cuenta("Adjudicada") ? "orange" : "green"
			);
		} else if (!["Cancelado", "Vencido"].includes(d.estado)) {
			frm.set_intro(
				__("Agregue las obras con su precio inicial. Al terminar, marque la subasta como realizada y registre el precio ganador y el comprador."),
				"blue"
			);
		}
	} else if (d.tipo === "Exposición") {
		frm.set_intro(__("La exposición ocupa la sala mientras dure: no se pueden programar otros eventos en ella."), "blue");
	}
}
