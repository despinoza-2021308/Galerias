// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Ficha del coleccionista: todo lo de un cliente en un solo lugar
// (obras compradas, reservadas y ganadas en subasta, facturas, saldo y
// artistas de interés).

frappe.pages["ficha-coleccionista"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Ficha del Coleccionista"), single_column: true });
	wrapper.ficha = new FichaColeccionista(page);
};

frappe.pages["ficha-coleccionista"].on_page_show = function (wrapper) {
	if (wrapper.ficha) wrapper.ficha.leer_ruta();
};

class FichaColeccionista {
	constructor(page) {
		this.page = page;
		this.campo = page.add_field({
			fieldname: "cliente",
			label: __("Cliente"),
			fieldtype: "Link",
			options: "Customer",
			change: () => this.cargar(),
		});
		page.set_secondary_action(__("Actualizar"), () => this.cargar(), "refresh");
		this.$cuerpo = $(`<div></div>`).appendTo(page.main);
		this.$cuerpo.on("click", "[data-accion]", (e) => {
			const $el = $(e.currentTarget);
			const id = $el.attr("data-id");
			const accion = $el.attr("data-accion");
			const recargar = () => this.cargar(true);
			if (accion === "obra") frappe.set_route("Form", "Obra de Arte", id);
			if (accion === "estado") galeria.pagos.estado_cuenta(id);
			if (accion === "cobrar") galeria.pagos.registrar(id, recargar);
			if (accion === "vender") galeria.obras.vender(id, recargar);
			if (accion === "cancelar") galeria.obras.cancelar_reserva(id, recargar);
			if (accion === "abonar") galeria.obras.abonar(id, null, recargar);
			if (accion === "recibo") galeria.obras.imprimir("Reservacion de Obra", id, "Recibo de Reserva");
			if (accion === "cliente") frappe.set_route("Form", "Customer", id);
			if (accion === "cobrar-subasta") galeria.eventos.cobrar_subasta($el.attr("data-evento"), id, recargar);
			if (accion === "subasta") galeria.eventos.resumen(id, recargar);
		});
		this.vacio();
		this.leer_ruta();
	}

	leer_ruta() {
		const cliente =
			(frappe.route_options && frappe.route_options.cliente) || frappe.utils.get_url_arg("cliente");
		frappe.route_options = null;
		if (cliente && cliente !== this.campo.get_value()) this.campo.set_value(cliente);
	}

	vacio() {
		this.$cuerpo.html(
			`<div class="text-muted text-center" style="padding: var(--padding-xl)">${__(
				"Elija un cliente para ver su ficha."
			)}</div>`
		);
	}

	async cargar(forzar) {
		const cliente = this.campo.get_value();
		if (!cliente) return this.vacio();
		if (!forzar && cliente === this.cargado) return;
		this.cargado = cliente;
		const r = await frappe.xcall("galeria_arte.api.obras.ficha_coleccionista", { cliente });
		this.pintar(r);
	}

	pintar(r) {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		const c = r.cliente;
		const t = r.totales;
		const tarjeta = (label, valor, clase = "") => `
			<div class="col-sm-3" style="margin-bottom: var(--margin-sm)">
				<div class="frappe-card" style="padding: var(--padding-md); height: 100%">
					<div class="text-muted small">${label}</div>
					<div class="h4 ${clase}" style="margin: 4px 0 0">${valor}</div>
				</div>
			</div>`;
		const artistas = c.artistas_interes.length
			? c.artistas_interes.map((a) => `<span class="indicator-pill blue" style="margin-right: 4px">${esc(a)}</span>`).join("")
			: `<span class="text-muted">${__("Sin artistas de interés registrados")}</span>`;

		const obra = (o, extra, acciones = "") => `
			<div class="col-sm-4 col-md-3" style="margin-bottom: var(--margin-md)">
				<div class="frappe-card" style="overflow: hidden; height: 100%">
					<div style="cursor: pointer" data-accion="obra" data-id="${esc(o.name)}">${galeria.obras.html_imagen(o.imagen, o.titulo, 130)}</div>
					<div style="padding: var(--padding-sm) var(--padding-md) var(--padding-md)">
						<div class="bold">${esc(o.titulo)}</div>
						<div class="text-muted small">${esc(o.artista)}</div>
						${extra}
						${acciones ? `<div style="margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap">${acciones}</div>` : ""}
					</div>
				</div>
			</div>`;
		const btn = (accion, id, texto, clase = "btn-default") =>
			`<button class="btn btn-xs ${clase}" data-accion="${accion}" data-id="${esc(id)}">${texto}</button>`;

		const compradas = r.obras_compradas.length
			? r.obras_compradas
					.map((o) =>
						obra(
							o,
							`<div class="small">${m(o.precio_vendido)} · ${frappe.datetime.str_to_user(o.fecha_venta)}</div>`,
							btn("estado", o.factura, __("Estado de cuenta"))
						)
					)
					.join("")
			: `<div class="col-sm-12 text-muted">${__("Aún no ha comprado obras.")}</div>`;

		const reservadas = r.obras_reservadas.length
			? r.obras_reservadas
					.map((o) =>
						obra(
							o,
							`<div class="small ${o.reserva_vencida ? "text-danger" : ""}">${esc(o.reservacion || "")} · ${__("abonado")} ${m(o.anticipo)} · ${
								o.reserva_vencida ? __("venció el") : __("hasta el")
							} ${frappe.datetime.str_to_user(o.fecha_limite_reserva)}</div>`,
							btn("vender", o.name, __("Vender"), "btn-primary") +
								btn("abonar", o.reservacion, __("Abonar")) +
								btn("cancelar", o.reservacion, __("Cancelar")) +
								btn("recibo", o.reservacion, __("Recibo"))
						)
					)
					.join("")
			: `<div class="col-sm-12 text-muted">${__("No tiene obras reservadas.")}</div>`;

		const subastas = (r.subastas || []).length
			? `<div class="frappe-card" style="overflow-x: auto"><table class="table table-hover gal-tabla" style="margin: 0">
				<thead><tr><th>${__("Obra")}</th><th>${__("Subasta")}</th><th class="text-right">${__("Precio ganador")}</th>
				<th>${__("Estado")}</th><th></th></tr></thead><tbody>` +
			  r.subastas
					.map((x) => {
						const [etiqueta, color] = galeria.eventos.RESULTADOS_SUBASTA[x.resultado] || [x.resultado, "gray"];
						let detalle = "";
						if (x.resultado === "Adjudicada") detalle = galeria.eventos.plazo_pago(x.fecha_limite_pago, x.dias_restantes);
						if (x.resultado === "Vencida")
							detalle = `<span class="text-danger">${__("Ganó y no pagó antes del {0}", [frappe.datetime.str_to_user(x.fecha_limite_pago)])}</span>`;
						if (x.resultado === "Pagada" && x.factura)
							detalle = `<a href="/app/sales-invoice/${encodeURIComponent(x.factura)}">${esc(x.factura)}</a>`;
						return `<tr>
							<td><a href="#" data-accion="obra" data-id="${esc(x.obra)}">${esc(x.titulo || x.obra)}</a><span class="gal-sub">${esc(x.artista || "")}</span></td>
							<td><a href="#" data-accion="subasta" data-id="${esc(x.evento)}">${esc(x.subasta)}</a>
								<span class="gal-sub">${frappe.datetime.str_to_user(String(x.inicio || "").slice(0, 10))}</span></td>
							<td class="text-right">${m(x.precio_ganador)}</td>
							<td><span class="indicator-pill ${color}">${etiqueta}</span>${detalle ? `<span class="gal-sub">${detalle}</span>` : ""}</td>
							<td class="text-right">${
								x.resultado === "Adjudicada"
									? `<button class="btn btn-xs btn-primary" data-accion="cobrar-subasta" data-id="${esc(x.lote)}" data-evento="${esc(x.evento)}">${__("Cobrar")}</button>`
									: ""
							}</td>
						</tr>`;
					})
					.join("") +
			  `</tbody></table></div>`
			: "";

		const estados = { Paid: [__("Pagada"), "green"], Unpaid: [__("Pendiente"), "orange"], "Partly Paid": [__("Pago parcial"), "yellow"], Overdue: [__("Vencida"), "red"] };
		const facturas = r.facturas.length
			? `<div class="frappe-card" style="overflow-x: auto"><table class="table table-hover gal-tabla" style="margin: 0">
				<thead><tr><th>${__("Factura")}</th><th>${__("Fecha")}</th><th>${__("Área")}</th><th>${__("Plan")}</th>
				<th class="text-right">${__("Total")}</th><th class="text-right">${__("Pendiente")}</th><th>${__("Pago")}</th><th></th></tr></thead><tbody>` +
			  r.facturas
					.map((f) => {
						const [estado, color] = estados[f.status] || [f.status, "gray"];
						return `<tr>
							<td><a href="/app/sales-invoice/${encodeURIComponent(f.name)}">${esc(f.name)}</a></td>
							<td>${frappe.datetime.str_to_user(f.posting_date)}</td>
							<td>${esc(f.galeria_area || "")}</td>
							<td>${esc(galeria.pagos.texto_plan(f))}</td>
							<td class="text-right">${m(f.grand_total)}</td>
							<td class="text-right ${flt(f.outstanding_amount) ? "text-danger" : "text-muted"}">${m(f.outstanding_amount)}</td>
							<td><span class="indicator-pill ${color}">${estado}</span></td>
							<td class="text-right" style="white-space: nowrap">${btn("estado", f.name, __("Estado de cuenta"))}
								${flt(f.outstanding_amount) > 0 ? btn("cobrar", f.name, __("Cobrar"), "btn-primary") : ""}</td>
						</tr>`;
					})
					.join("") +
			  `</tbody></table></div>`
			: `<div class="text-muted">${__("Sin facturas de la galería.")}</div>`;

		const titulo = (texto) => `<h5 style="margin: var(--margin-lg) 0 var(--margin-sm)">${texto}</h5>`;
		this.$cuerpo.html(`
			<div class="frappe-card" style="padding: var(--padding-md); margin-bottom: var(--margin-md)">
				<div style="display: flex; justify-content: space-between; gap: var(--margin-md); flex-wrap: wrap">
					<div>
						<div class="h4" style="margin: 0">${esc(c.customer_name)}</div>
						<div class="text-muted">${esc(c.galeria_tipo_cliente || __("Sin tipo"))} · NIT ${esc(c.tax_id || "CF")}
							${c.mobile_no ? " · " + esc(c.mobile_no) : ""}${c.email_id ? " · " + esc(c.email_id) : ""}</div>
						<div style="margin-top: 8px"><span class="text-muted small">${__("Artistas de interés")}:</span> ${artistas}</div>
						${
							t.subastas_sin_pagar
								? `<div style="margin-top: 8px"><span class="indicator-pill red">${
										t.subastas_sin_pagar === 1
											? __("Ganó 1 subasta y no pagó")
											: __("Ganó {0} subastas y no pagó", [t.subastas_sin_pagar])
								  }</span></div>`
								: ""
						}
					</div>
					<div>${btn("cliente", c.name, __("Abrir cliente"))}</div>
				</div>
			</div>
			<div class="row">
				${tarjeta(__("Total comprado"), m(t.comprado))}
				${tarjeta(__("Saldo pendiente"), m(t.pendiente), t.pendiente ? "text-danger" : "")}
				${tarjeta(__("Anticipos en reservas"), m(t.anticipos_en_reservas))}
				${tarjeta(__("Saldo a favor"), m(t.saldo_a_favor), t.saldo_a_favor ? "text-success" : "")}
			</div>
			<div class="text-muted small" style="margin-top: 4px">
				${__("Arte")}: <b>${m(t.por_area["Arte"])}</b> · ${__("Eventos")}: <b>${m(t.por_area["Eventos"])}</b> · ${__("Cafetería")}: <b>${m(t.por_area["Cafetería"])}</b>
			</div>
			${subastas ? titulo(__("Subastas ganadas")) + subastas : ""}
			${titulo(__("Obras reservadas"))}<div class="row">${reservadas}</div>
			${titulo(__("Obras compradas"))}<div class="row">${compradas}</div>
			${titulo(__("Facturas"))}${facturas}`);
	}
}
