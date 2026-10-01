// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Pago a artistas: liquidar obras vendidas, pagar y anular liquidaciones.
// Se usan desde Pagos a Artistas, la ficha del artista y la de la liquidación.

frappe.provide("galeria.artistas");

const LIQ_API = "galeria_arte.api.liquidaciones";

galeria.artistas.COLORES_PAGO = {
	"Por liquidar": "green",
	"En espera del cliente": "orange",
	"En liquidación": "yellow",
	"Pagado al artista": "blue",
	"Sin pago al artista": "gray",
};

galeria.artistas.COLORES_LIQUIDACION = { "Por pagar": "orange", Pagada: "green", Anulada: "gray" };

// Elegir las obras listas de un artista y liquidarlas (pagando ahora o después).
// solo_obras: si viene, solo esas obras quedan marcadas al abrir.
galeria.artistas.liquidar = async function (artista, on_done, solo_obras = null) {
	const [obras, opciones] = await Promise.all([
		frappe.xcall(`${LIQ_API}.por_liquidar`, { artista }),
		frappe.xcall("galeria_arte.api.facturacion.opciones_cobro"),
	]);
	if (!obras.length) {
		frappe.msgprint(
			__("{0} no tiene obras listas para liquidar. Una obra se puede liquidar cuando el cliente terminó de pagarla.", [artista])
		);
		return;
	}
	const m = galeria.pagos.moneda;
	const esc = frappe.utils.escape_html;
	// Transferencia primero: es la forma habitual de pagarle a un artista.
	const modo_defecto = opciones.modos_pago.find((x) => /transfer/i.test(x)) || opciones.modos_pago[0];

	const d = new frappe.ui.Dialog({
		title: __("Liquidar a {0}", [artista]),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "obras" },
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Check",
				fieldname: "pagar",
				label: __("Registrar el pago ahora"),
				default: 1,
				description: __("Si no, la liquidación queda 'Por pagar' y se paga después."),
			},
			{
				fieldtype: "Select",
				fieldname: "modo_pago",
				label: __("Forma de pago"),
				options: opciones.modos_pago.join("\n"),
				default: modo_defecto,
				depends_on: "eval:doc.pagar",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Data",
				fieldname: "referencia",
				label: __("Referencia (transferencia, cheque, boleta)"),
				depends_on: "eval:doc.pagar",
			},
			{ fieldtype: "Small Text", fieldname: "notas", label: __("Notas") },
		],
		primary_action_label: __("Liquidar"),
		primary_action: async (v) => {
			const elegidas = seleccion();
			if (!elegidas.length) {
				frappe.msgprint(__("Elija al menos una obra."));
				return;
			}
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${LIQ_API}.crear_liquidacion`, {
					artista,
					obras: elegidas,
					pagar: v.pagar ? 1 : 0,
					modo_pago: v.pagar ? v.modo_pago : null,
					referencia: v.pagar ? v.referencia : null,
					notas: v.notas,
				});
				d.hide();
				galeria.artistas.liquidacion_lista(r);
				on_done && on_done(r);
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});

	const $w = d.fields_dict.obras.$wrapper;
	$w.html(`
		<div class="text-muted small" style="margin-bottom: 6px">${__("Obras vendidas y ya cobradas por completo al cliente")}</div>
		<table class="table table-bordered table-sm" style="margin-bottom: 8px">
			<thead><tr><th style="width: 32px"></th><th>${__("Obra")}</th><th>${__("Factura")}</th><th>${__("Vendida el")}</th>
				<th class="text-right">${__("Precio vendido")}</th><th class="text-right">${__("Para el artista")}</th></tr></thead>
			<tbody>${obras
				.map(
					(o) => `<tr>
					<td><input type="checkbox" data-obra="${esc(o.name)}" data-monto="${flt(o.monto_artista)}" ${
						!solo_obras || solo_obras.includes(o.name) ? "checked" : ""
					} aria-label="${esc(o.titulo)}"></td>
					<td>${esc(o.titulo)}<div class="text-muted small">${esc(o.cliente_nombre || o.cliente || "")}</div></td>
					<td>${esc(o.factura || "")}</td>
					<td>${frappe.datetime.str_to_user(o.fecha_venta)}</td>
					<td class="text-right">${m(o.precio_vendido)}</td>
					<td class="text-right bold">${m(o.monto_artista)}</td></tr>`
				)
				.join("")}</tbody>
		</table>
		<div class="text-right"><span class="text-muted">${__("Total a pagar al artista")}:</span>
			<span class="h4" data-total style="margin-left: 8px"></span></div>`);
	const seleccion = () =>
		$w
			.find("input[data-obra]:checked")
			.map((_, el) => $(el).attr("data-obra"))
			.get();
	const total = () => {
		let t = 0;
		$w.find("input[data-obra]:checked").each((_, el) => (t += flt($(el).attr("data-monto"))));
		$w.find("[data-total]").text(m(t));
		d.get_primary_btn().prop("disabled", t <= 0);
	};
	$w.on("change", "input[data-obra]", total);
	d.show();
	total();
};

// Al terminar de cobrar una obra: avisa que ya se le puede pagar al artista.
// obras: [{obra, titulo, artista, monto_artista}]
galeria.artistas.ofrecer_liquidar = function (obras, on_done) {
	if (!obras || !obras.length) return;
	const m = galeria.pagos.moneda;
	const esc = frappe.utils.escape_html;
	const d = new frappe.ui.Dialog({
		title: obras.length === 1 ? __("Obra pagada por completo") : __("Obras pagadas por completo"),
		fields: [{ fieldtype: "HTML", fieldname: "html" }],
	});
	d.fields_dict.html.$wrapper.html(`
		<p>${__("El cliente terminó de pagar. Ya se le puede pagar al artista:")}</p>
		<table class="table table-sm gal-tabla" style="margin: 0">
			<tbody>${obras
				.map(
					(o, i) => `<tr><td>${esc(o.titulo)}<span class="gal-sub">${esc(o.artista)}</span></td>
					<td class="text-right">${__("Para el artista")}<span class="gal-sub"><b>${m(o.monto_artista)}</b></span></td>
					<td class="text-right"><button type="button" class="btn btn-primary btn-sm" data-liquidar="${i}">${__("Liquidar al artista")}</button></td></tr>`
				)
				.join("")}</tbody>
		</table>`);
	d.fields_dict.html.$wrapper.on("click", "[data-liquidar]", (e) => {
		const o = obras[cint($(e.currentTarget).attr("data-liquidar"))];
		d.hide();
		galeria.artistas.liquidar(o.artista, on_done, [o.obra]);
	});
	d.show();
};

galeria.artistas.liquidacion_lista = function (r) {
	const pagada = r.estado === "Pagada";
	const d = new frappe.ui.Dialog({
		title: pagada ? __("Artista pagado") : __("Liquidación creada"),
		fields: [{ fieldtype: "HTML", fieldname: "html" }],
		primary_action_label: __("Cerrar"),
		primary_action: () => d.hide(),
		secondary_action_label: __("Imprimir comprobante"),
		secondary_action: () => galeria.obras.imprimir("Liquidacion a Artista", r.liquidacion, "Comprobante de Liquidación"),
	});
	d.fields_dict.html.$wrapper.html(`
		<div class="text-center" style="padding: var(--padding-md) 0">
			<div class="text-muted">${__("Liquidación")}</div>
			<div class="h3" style="margin: 4px 0"><a href="/app/liquidacion-a-artista/${encodeURIComponent(r.liquidacion)}">${frappe.utils.escape_html(r.liquidacion)}</a></div>
			<div class="h4">${galeria.pagos.moneda(r.total)}</div>
			<span class="indicator-pill ${galeria.artistas.COLORES_LIQUIDACION[r.estado] || "gray"}">${frappe.utils.escape_html(r.estado)}</span>
		</div>`);
	d.show();
};

galeria.artistas.pagar = async function (liquidacion, total, on_done) {
	const opciones = await frappe.xcall("galeria_arte.api.facturacion.opciones_cobro");
	const d = new frappe.ui.Dialog({
		title: __("Pagar la liquidación · {0}", [liquidacion]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<div class="text-center" style="margin-bottom: var(--margin-md)"><div class="text-muted">${__(
					"Total a pagar al artista"
				)}</div><div class="h3">${galeria.pagos.moneda(total)}</div></div>`,
			},
			{
				fieldtype: "Select",
				fieldname: "modo_pago",
				label: __("Forma de pago"),
				options: opciones.modos_pago.join("\n"),
				default: opciones.modos_pago.find((x) => /transfer/i.test(x)) || opciones.modos_pago[0],
				reqd: 1,
			},
			{ fieldtype: "Data", fieldname: "referencia", label: __("Referencia (transferencia, cheque, boleta)") },
		],
		primary_action_label: __("Registrar pago"),
		primary_action: async (v) => {
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${LIQ_API}.pagar_liquidacion`, { liquidacion, ...v });
				d.hide();
				frappe.show_alert({ message: __("Pago al artista registrado"), indicator: "green" });
				on_done && on_done(r);
			} catch (e) {
				// El servidor ya mostró el mensaje de error.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});
	d.show();
};

galeria.artistas.anular = function (liquidacion, pagada, on_done) {
	const d = new frappe.ui.Dialog({
		title: __("Anular la liquidación · {0}", [liquidacion]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p>${
					pagada
						? __("Se anulan el pago y la deuda registrados, y las obras vuelven a quedar por liquidar. Recuperar el dinero ya entregado al artista se gestiona aparte.")
						: __("Se anula la deuda registrada y las obras vuelven a quedar por liquidar.")
				}</p>`,
			},
			{ fieldtype: "Small Text", fieldname: "motivo", label: __("Motivo"), reqd: 1 },
		],
		primary_action_label: __("Anular liquidación"),
		primary_action: async (v) => {
			const r = await frappe.xcall(`${LIQ_API}.anular_liquidacion`, { liquidacion, motivo: v.motivo });
			d.hide();
			frappe.show_alert({ message: __("Liquidación anulada"), indicator: "orange" });
			on_done && on_done(r);
		},
	});
	d.show();
};
