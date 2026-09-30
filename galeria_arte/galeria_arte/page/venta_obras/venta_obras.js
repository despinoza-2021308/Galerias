// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Venta de Obras: el punto de venta de arte, separado del POS de cafetería.
// Pestañas: Vender / Reservar, Reservaciones, Subastas (obras ganadas por
// cobrar) y Ventas de arte.

frappe.pages["venta-obras"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Venta de Obras"), single_column: true });
	wrapper.venta_obras = new VentaObras(page);
};

frappe.pages["venta-obras"].on_page_show = function (wrapper) {
	const vo = wrapper.venta_obras;
	if (!vo) return;
	if (frappe.route_options && frappe.route_options.pestana) {
		vo.pestana = frappe.route_options.pestana;
		frappe.route_options = null;
	}
	if (vo.visto) vo.cargar();
	vo.visto = true;
};

class VentaObras {
	constructor(page) {
		this.page = page;
		this.pestana = "vender";
		this.buscar = "";
		this.filtro_reservas = "Activa";
		this.filtro_subastas = "Adjudicada";
		this.datos = { obras: [], reservaciones: [], ventas: [], subastas: [], totales: {} };

		page.set_primary_action(__("Nueva obra"), () => frappe.new_doc("Obra de Arte"), "add");
		page.set_secondary_action(__("Actualizar"), () => this.cargar(), "refresh");
		page.add_menu_item(__("Catálogo de obras"), () => frappe.set_route("catalogo-obras"));
		page.add_menu_item(__("Cobros"), () => frappe.set_route("cobros-galeria"));
		page.add_menu_item(__("Cierre de caja"), () => frappe.new_doc("Cierre de Caja"));

		this.$totales = $(`<div class="row"></div>`).appendTo(page.main);
		this.$tabs = $(`<div class="vo-tabs"></div>`).appendTo(page.main);
		this.$cuerpo = $(`<div></div>`).appendTo(page.main);

		this.$tabs.on("click", "[data-pestana]", (e) => {
			this.pestana = $(e.currentTarget).attr("data-pestana");
			this.pintar();
		});
		this.$cuerpo.on("input", "[data-buscar]", (e) => {
			this.buscar = (e.currentTarget.value || "").toLowerCase();
			this.pintar_cuerpo(true);
		});
		this.$cuerpo.on("change", "[data-filtro-reservas]", (e) => {
			this.filtro_reservas = e.currentTarget.value;
			this.pintar_cuerpo();
		});
		this.$cuerpo.on("change", "[data-filtro-subastas]", (e) => {
			this.filtro_subastas = e.currentTarget.value;
			this.pintar_cuerpo();
		});
		this.$cuerpo.on("click", "[data-accion]", (e) => this.accion($(e.currentTarget)));
		this.cargar();
	}

	async cargar() {
		this.datos = await frappe.xcall("galeria_arte.api.arte.panel");
		this.pintar();
	}

	accion($el) {
		const accion = $el.attr("data-accion");
		const id = $el.attr("data-id");
		const recargar = () => this.cargar();
		const res = this.datos.reservaciones.find((r) => r.name === id);
		if (accion === "reservar") galeria.obras.reservar(id, recargar);
		if (accion === "vender") galeria.obras.vender(id, recargar);
		if (accion === "ver-obra") frappe.set_route("Form", "Obra de Arte", id);
		if (accion === "abonar") galeria.obras.abonar(id, res && res.saldo_obra, recargar);
		if (accion === "extender") galeria.obras.extender(id, res && res.fecha_limite, recargar);
		if (accion === "cancelar") galeria.obras.cancelar_reserva(id, recargar);
		if (accion === "recibo") galeria.obras.imprimir("Reservacion de Obra", id, "Recibo de Reserva");
		if (accion === "ver-reserva") frappe.set_route("Form", "Reservacion de Obra", id);
		if (accion === "cobrar") galeria.pagos.registrar(id, recargar);
		if (accion === "estado") galeria.pagos.estado_cuenta(id);
		if (accion === "factura") galeria.obras.imprimir("Sales Invoice", id, "Factura Galería");
		if (accion === "cobrar-subasta") galeria.eventos.cobrar_subasta($el.attr("data-evento"), id, recargar);
		if (accion === "ver-subasta") galeria.eventos.resumen(id, recargar);
	}

	pintar() {
		this.pintar_totales();
		this.pintar_tabs();
		this.pintar_cuerpo();
	}

	pintar_totales() {
		const m = galeria.pagos.moneda;
		const t = this.datos.totales;
		const tarjeta = (label, valor, sub = "", clase = "") => `
			<div class="col-sm-3" style="margin-bottom: var(--margin-sm)">
				<div class="frappe-card" style="padding: var(--padding-md); height: 100%">
					<div class="text-muted small">${label}</div>
					<div class="h4 ${clase}" style="margin: 4px 0 0">${valor}</div>
					${sub ? `<div class="text-muted small">${sub}</div>` : ""}
				</div>
			</div>`;
		this.$totales.html(
			tarjeta(__("Vendido este mes"), m(t.vendido_mes), galeria.pagos.cuantos(t.ventas_mes, __("obra facturada"), __("obras facturadas"))) +
				tarjeta(__("Reservas activas"), t.reservas_activas || 0, `${__("Anticipos")}: ${m(t.anticipos_reservas)}`) +
				tarjeta(
					__("Reservas vencidas"),
					t.reservas_vencidas || 0,
					t.reservas_vencidas ? __("Decida: vender, extender o cancelar") : "",
					t.reservas_vencidas ? "text-danger" : ""
				) +
				tarjeta(__("Saldo por cobrar"), m(t.por_cobrar), "", t.por_cobrar ? "text-danger" : "")
		);
	}

	pintar_tabs() {
		const d = this.datos;
		const t = d.totales;
		const tab = (id, texto, cuenta, alerta) =>
			`<button type="button" class="vo-tab ${this.pestana === id ? "activo" : ""}" data-pestana="${id}">${texto}
				<span class="vo-cuenta ${alerta ? "alerta" : ""}">${cuenta}</span></button>`;
		this.$tabs.html(
			tab("vender", __("Vender / Reservar"), d.obras.length) +
				tab("reservas", __("Reservaciones"), t.reservas_activas || 0, t.reservas_vencidas > 0) +
				tab("subastas", __("Subastas por cobrar"), t.subastas_por_pagar || 0, t.subastas_por_vencer > 0) +
				tab("ventas", __("Ventas de arte"), d.ventas.length)
		);
	}

	pintar_cuerpo(solo_lista) {
		if (this.pestana === "vender") return this.pintar_vender(solo_lista);
		if (this.pestana === "reservas") return this.pintar_reservas();
		if (this.pestana === "subastas") return this.pintar_subastas();
		return this.pintar_ventas();
	}

	// ------------------------------------------------------------------
	// Pestaña 1: obras disponibles
	// ------------------------------------------------------------------

	pintar_vender(solo_lista) {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		if (!solo_lista) {
			this.$cuerpo.html(`
				<div class="vo-barra">
					<input type="search" class="form-control" data-buscar placeholder="${__("Buscar por título, artista o técnica…")}" value="${esc(this.buscar)}">
				</div>
				<div class="vo-grid" data-lista></div>`);
		}
		const obras = this.datos.obras.filter(
			(o) =>
				!this.buscar ||
				[o.titulo, o.artista, o.tecnica].some((x) => (x || "").toLowerCase().includes(this.buscar))
		);
		const $lista = this.$cuerpo.find("[data-lista]");
		if (!obras.length) {
			$lista.html(
				`<div class="vo-vacio" style="grid-column: 1 / -1">${
					this.datos.obras.length ? __("Ninguna obra disponible coincide con la búsqueda.") : __("No hay obras disponibles para vender.")
				}</div>`
			);
			return;
		}
		$lista.html(
			obras
				.map((o) => {
					const medidas = [o.alto_cm, o.ancho_cm].filter((x) => flt(x) > 0).join(" × ");
					const detalle = [o.tecnica, o.anio || "", medidas ? medidas + " cm" : ""].filter(Boolean).join(" · ");
					return `
					<div class="vo-obra">
						<div style="cursor: pointer" data-accion="ver-obra" data-id="${esc(o.name)}">${galeria.obras.html_imagen(o.imagen, o.titulo, 150)}</div>
						<div class="vo-obra-cuerpo">
							<div class="vo-obra-titulo">${esc(o.titulo)}</div>
							<div>${esc(o.artista)}</div>
							<div class="vo-obra-detalle">${esc(detalle)}</div>
							<div class="vo-obra-precio">${m(o.precio_venta)}</div>
							<div class="vo-obra-acciones">
								<button class="btn btn-default" data-accion="reservar" data-id="${esc(o.name)}">${__("Reservar")}</button>
								<button class="btn btn-primary" data-accion="vender" data-id="${esc(o.name)}">${__("Vender")}</button>
							</div>
						</div>
					</div>`;
				})
				.join("")
		);
	}

	// ------------------------------------------------------------------
	// Pestaña 2: reservaciones
	// ------------------------------------------------------------------

	pintar_reservas() {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		const opciones = ["Activa", "Vencida", "Convertida en venta", "Cancelada", "Todas"];
		const f = this.filtro_reservas;
		const lista = this.datos.reservaciones.filter((r) => {
			if (f === "Todas") return true;
			if (f === "Vencida") return r.vencida;
			return r.estado === f;
		});
		const btn = (accion, id, texto, clase = "btn-default") =>
			`<button class="btn btn-xs ${clase}" data-accion="${accion}" data-id="${esc(id)}">${texto}</button>`;
		const estado = (r) => {
			if (r.vencida) return `<span class="indicator-pill red">${__("Vencida")}</span>`;
			if (r.estado === "Activa") return `<span class="indicator-pill green">${__("Activa")}</span>`;
			if (r.estado === "Convertida en venta") return `<span class="indicator-pill blue">${__("Convertida en venta")}</span>`;
			return `<span class="indicator-pill gray">${esc(r.estado)}</span>`;
		};
		const plazo = (r) => {
			if (r.estado !== "Activa") {
				return r.factura
					? `<a href="/app/sales-invoice/${encodeURIComponent(r.factura)}">${esc(r.factura)}</a>`
					: esc(r.motivo_cancelacion || "");
			}
			const fecha = frappe.datetime.str_to_user(r.fecha_limite);
			if (r.vencida) return `<span class="text-danger">${fecha} · ${__("venció hace {0} días", [-r.dias_restantes])}</span>`;
			if (r.dias_restantes === 0) return `<span class="text-warning">${fecha} · ${__("vence hoy")}</span>`;
			return `${fecha} · ${__("faltan {0} días", [r.dias_restantes])}`;
		};
		const filas = lista
			.map(
				(r) => `
			<tr>
				<td><a href="/app/reservacion-de-obra/${encodeURIComponent(r.name)}">${esc(r.name)}</a>
					<div class="text-muted small">${frappe.datetime.str_to_user(r.fecha)}</div></td>
				<td><a href="/app/obra-de-arte/${encodeURIComponent(r.obra)}">${esc(r.titulo_obra || r.obra)}</a>
					<div class="text-muted small">${esc(r.artista || "")}</div></td>
				<td>${esc(r.cliente_nombre)}</td>
				<td class="text-right">${m(r.precio_obra)}</td>
				<td class="text-right text-success">${m(r.total_abonado)}</td>
				<td class="text-right">${r.estado === "Activa" ? m(r.saldo_obra) : ""}</td>
				<td>${estado(r)}</td>
				<td>${plazo(r)}</td>
				<td class="vo-acciones-fila">
					${
						r.estado === "Activa"
							? btn("vender", r.obra, __("Vender"), "btn-primary") +
							  btn("abonar", r.name, __("Abonar")) +
							  btn("extender", r.name, __("Extender")) +
							  btn("cancelar", r.name, __("Cancelar"))
							: ""
					}
					${btn("recibo", r.name, __("Recibo"))}
				</td>
			</tr>`
			)
			.join("");
		this.$cuerpo.html(`
			<div class="vo-barra">
				<select class="form-control" data-filtro-reservas style="max-width: 240px">
					${opciones.map((o) => `<option ${o === f ? "selected" : ""}>${o}</option>`).join("")}
				</select>
			</div>
			${
				lista.length
					? `<div class="frappe-card" style="overflow-x: auto"><table class="table table-hover gal-tabla" style="margin: 0">
						<thead><tr><th>${__("Reservación")}</th><th>${__("Obra")}</th><th>${__("Cliente")}</th>
						<th class="text-right">${__("Precio")}</th><th class="text-right">${__("Abonado")}</th>
						<th class="text-right">${__("Saldo")}</th><th>${__("Estado")}</th><th>${__("Reservada hasta / cierre")}</th><th></th></tr></thead>
						<tbody>${filas}</tbody></table></div>`
					: `<div class="vo-vacio">${__("No hay reservaciones con ese filtro.")}</div>`
			}`);
	}

	// ------------------------------------------------------------------
	// Pestaña 3: obras ganadas en subasta (pago al contado en 7 días)
	// ------------------------------------------------------------------

	pintar_subastas() {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		const opciones = [
			["Adjudicada", __("Por pagar")],
			["Vencida", __("No pagaron")],
			["Pagada", __("Pagadas")],
			["", __("Todas")],
		];
		const f = this.filtro_subastas;
		const lista = this.datos.subastas.filter((x) => !f || x.resultado === f);
		const filas = lista
			.map((x) => {
				const [etiqueta, color] = galeria.eventos.RESULTADOS_SUBASTA[x.resultado] || [x.resultado, "gray"];
				let detalle = "";
				if (x.resultado === "Adjudicada") detalle = galeria.eventos.plazo_pago(x.fecha_limite_pago, x.dias_restantes);
				if (x.resultado === "Vencida") detalle = __("Venció el {0}", [frappe.datetime.str_to_user(x.fecha_limite_pago)]);
				if (x.resultado === "Pagada" && x.factura)
					detalle = `<a href="/app/sales-invoice/${encodeURIComponent(x.factura)}">${esc(x.factura)}</a>`;
				const acciones =
					x.resultado === "Adjudicada"
						? `<button class="btn btn-xs btn-primary" data-accion="cobrar-subasta" data-id="${esc(x.lote)}" data-evento="${esc(x.evento)}">${__("Cobrar")}</button>`
						: x.resultado === "Pagada" && x.factura
						? `<button class="btn btn-xs btn-default" data-accion="factura" data-id="${esc(x.factura)}">${__("Imprimir")}</button>`
						: "";
				return `<tr>
					<td><a href="/app/obra-de-arte/${encodeURIComponent(x.obra)}">${esc(x.titulo || x.obra)}</a><span class="gal-sub">${esc(x.artista || "")}</span></td>
					<td><a href="#" data-accion="ver-subasta" data-id="${esc(x.evento)}">${esc(x.subasta)}</a>
						<span class="gal-sub">${frappe.datetime.str_to_user(String(x.inicio || "").slice(0, 10))}</span></td>
					<td class="nowrap"><a href="/app/ficha-coleccionista?cliente=${encodeURIComponent(x.comprador || "")}">${esc(x.comprador_nombre || x.comprador || "")}</a></td>
					<td class="text-right">${m(x.precio_inicial)}</td>
					<td class="text-right"><b>${m(x.precio_ganador)}</b></td>
					<td><span class="indicator-pill ${color}">${etiqueta}</span>${detalle ? `<span class="gal-sub">${detalle}</span>` : ""}</td>
					<td class="vo-acciones-fila">${acciones}</td>
				</tr>`;
			})
			.join("");
		this.$cuerpo.html(`
			<div class="vo-barra">
				<select class="form-control" data-filtro-subastas style="max-width: 240px">
					${opciones.map(([v, t]) => `<option value="${v}" ${v === f ? "selected" : ""}>${t}</option>`).join("")}
				</select>
				<span class="text-muted small" style="align-self: center">${__("El ganador paga el precio completo, al contado, en 7 días. La factura se emite al cobrar.")}</span>
			</div>
			${
				lista.length
					? `<div class="frappe-card" style="overflow-x: auto"><table class="table table-hover gal-tabla" style="margin: 0">
						<thead><tr><th>${__("Obra")}</th><th>${__("Subasta")}</th><th>${__("Comprador")}</th>
						<th class="text-right">${__("Precio inicial")}</th><th class="text-right">${__("Precio ganador")}</th>
						<th>${__("Estado")}</th><th></th></tr></thead>
						<tbody>${filas}</tbody></table></div>`
					: `<div class="vo-vacio">${f === "Adjudicada" ? __("No hay obras de subasta pendientes de pago.") : __("No hay obras de subasta con ese filtro.")}</div>`
			}`);
	}

	// ------------------------------------------------------------------
	// Pestaña 4: ventas de arte
	// ------------------------------------------------------------------

	pintar_ventas() {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		const ventas = this.datos.ventas;
		if (!ventas.length) {
			this.$cuerpo.html(`<div class="vo-vacio">${__("Aún no hay ventas de obras.")}</div>`);
			return;
		}
		const btn = (accion, id, texto, clase = "btn-default") =>
			`<button class="btn btn-xs ${clase}" data-accion="${accion}" data-id="${esc(id)}">${texto}</button>`;
		const filas = ventas
			.map((v) => {
				const obras = v.obras.length
					? v.obras.map((o) => `<span class="nowrap">${esc(o.titulo)}</span><span class="gal-sub">${esc(o.artista)}</span>`).join("")
					: `<span class="text-muted">—</span>`;
				const detalle = v.galeria_evento ? __("Contado") : galeria.pagos.detalle_plan(v);
				const plan = v.galeria_evento ? __("Venta en subasta") : galeria.pagos.texto_plan(v);
				const forma = `${esc(plan)}${detalle ? `<span class="gal-sub">${esc(detalle)}</span>` : ""}`;
				return `
				<tr>
					<td><a href="/app/sales-invoice/${encodeURIComponent(v.name)}">${esc(v.name)}</a>
						<div class="text-muted small">${frappe.datetime.str_to_user(v.posting_date)}</div></td>
					<td>${obras}${v.galeria_reservacion ? `<div class="text-muted small">${__("Reserva")} ${esc(v.galeria_reservacion)}</div>` : ""}</td>
					<td class="nowrap">${esc(v.customer_name || v.customer)}</td>
					<td>${forma}</td>
					<td class="text-right">${m(v.grand_total)}</td>
					<td class="text-right text-success">${m(v.pagado)}</td>
					<td class="text-right ${flt(v.outstanding_amount) ? "text-danger" : "text-muted"}">${m(v.outstanding_amount)}</td>
					<td class="vo-acciones-fila">
						${flt(v.outstanding_amount) > 0 ? btn("cobrar", v.name, __("Cobrar"), "btn-primary") : ""}
						${btn("estado", v.name, __("Estado de cuenta"))}
						${btn("factura", v.name, __("Imprimir"))}
					</td>
				</tr>`;
			})
			.join("");
		this.$cuerpo.html(`
			<div class="frappe-card" style="overflow-x: auto"><table class="table table-hover gal-tabla" style="margin: 0">
				<thead><tr><th>${__("Factura")}</th><th>${__("Obra")}</th><th>${__("Cliente")}</th><th>${__("Plan de pago")}</th>
				<th class="text-right">${__("Total")}</th><th class="text-right">${__("Pagado")}</th>
				<th class="text-right">${__("Saldo")}</th><th></th></tr></thead>
				<tbody>${filas}</tbody></table></div>`);
	}
}
