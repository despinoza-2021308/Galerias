// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Pagos a Artistas: qué se le debe a cada artista por sus obras vendidas,
// liquidaciones y detalle por obra.

frappe.pages["pagos-artistas"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Pagos a Artistas"), single_column: true });
	wrapper.pagos_artistas = new PagosArtistas(page);
};

frappe.pages["pagos-artistas"].on_page_show = function (wrapper) {
	const pa = wrapper.pagos_artistas;
	if (!pa) return;
	if (pa.visto) pa.cargar();
	pa.visto = true;
};

class PagosArtistas {
	constructor(page) {
		this.page = page;
		this.pestana = "artistas";
		this.filtro_liq = "Todas";
		this.filtro_obras = "Todas";
		this.datos = { artistas: [], liquidaciones: [], obras: [], totales: {} };

		page.set_secondary_action(__("Actualizar"), () => this.cargar(), "refresh");
		page.add_menu_item(__("Artistas"), () => frappe.set_route("List", "Artista"));
		page.add_menu_item(__("Venta de obras"), () => frappe.set_route("venta-obras"));
		page.add_menu_item(__("Cuentas por pagar"), () => frappe.set_route("query-report", "Accounts Payable"));

		this.$totales = $(`<div class="row"></div>`).appendTo(page.main);
		this.$tabs = $(`<div class="pa-tabs"></div>`).appendTo(page.main);
		this.$cuerpo = $(`<div></div>`).appendTo(page.main);

		this.$tabs.on("click", "[data-pestana]", (e) => {
			this.pestana = $(e.currentTarget).attr("data-pestana");
			this.pintar();
		});
		this.$cuerpo.on("change", "[data-filtro-liq]", (e) => {
			this.filtro_liq = e.currentTarget.value;
			this.pintar_cuerpo();
		});
		this.$cuerpo.on("change", "[data-filtro-obras]", (e) => {
			this.filtro_obras = e.currentTarget.value;
			this.pintar_cuerpo();
		});
		this.$cuerpo.on("click", "[data-accion]", (e) => this.accion($(e.currentTarget)));
		this.cargar();
	}

	async cargar() {
		this.datos = await frappe.xcall("galeria_arte.api.liquidaciones.resumen");
		this.pintar();
	}

	accion($el) {
		const accion = $el.attr("data-accion");
		const id = $el.attr("data-id");
		const recargar = () => this.cargar();
		const liq = this.datos.liquidaciones.find((l) => l.name === id);
		if (accion === "liquidar") galeria.artistas.liquidar(id, recargar);
		if (accion === "artista") frappe.set_route("Form", "Artista", id);
		if (accion === "pagar") galeria.artistas.pagar(id, liq && liq.total, recargar);
		if (accion === "anular") galeria.artistas.anular(id, liq && liq.estado === "Pagada", recargar);
		if (accion === "comprobante") galeria.obras.imprimir("Liquidacion a Artista", id, "Comprobante de Liquidación");
		if (accion === "obra") frappe.set_route("Form", "Obra de Arte", id);
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
			tarjeta(
				__("Listo para liquidar"),
				m(t.por_liquidar),
				galeria.pagos.cuantos(t.obras_por_liquidar, __("obra ya cobrada al cliente"), __("obras ya cobradas al cliente")),
				t.por_liquidar ? "text-success" : ""
			) +
				tarjeta(__("Liquidaciones por pagar"), m(t.por_pagar), __("Deuda ya registrada con artistas"), t.por_pagar ? "text-danger" : "") +
				tarjeta(__("En espera del cliente"), m(t.en_espera), galeria.pagos.cuantos(t.obras_en_espera, __("obra que el cliente aún está pagando"), __("obras que el cliente aún está pagando"))) +
				tarjeta(__("Pagado este mes"), m(t.pagado_mes))
		);
	}

	pintar_tabs() {
		const d = this.datos;
		const por_pagar = d.liquidaciones.filter((l) => l.estado === "Por pagar").length;
		const tab = (id, texto, cuenta, alerta) =>
			`<button type="button" class="pa-tab ${this.pestana === id ? "activo" : ""}" data-pestana="${id}">${texto}
				<span class="pa-cuenta ${alerta ? "alerta" : ""}">${cuenta}</span></button>`;
		this.$tabs.html(
			tab("artistas", __("Por artista"), d.artistas.length) +
				tab("liquidaciones", __("Liquidaciones"), d.liquidaciones.length, por_pagar > 0) +
				tab("obras", __("Obras vendidas"), d.obras.length)
		);
	}

	pintar_cuerpo() {
		if (this.pestana === "artistas") return this.pintar_artistas();
		if (this.pestana === "liquidaciones") return this.pintar_liquidaciones();
		return this.pintar_obras();
	}

	btn(accion, id, texto, clase = "btn-default") {
		return `<button class="btn btn-xs ${clase}" data-accion="${accion}" data-id="${frappe.utils.escape_html(id)}">${texto}</button>`;
	}

	tabla(encabezados, filas) {
		return `<div class="frappe-card" style="overflow-x: auto"><table class="table table-hover gal-tabla" style="margin: 0">
			<thead><tr>${encabezados}</tr></thead><tbody>${filas}</tbody></table></div>`;
	}

	// ------------------------------------------------------------------
	// Por artista
	// ------------------------------------------------------------------

	pintar_artistas() {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		const artistas = this.datos.artistas;
		if (!artistas.length) {
			this.$cuerpo.html(`<div class="pa-vacio">${__("Aún no hay obras vendidas ni pagos a artistas.")}</div>`);
			return;
		}
		const filas = artistas
			.map(
				(a) => `
			<tr>
				<td><a href="/app/artista/${encodeURIComponent(a.artista)}">${esc(a.artista)}</a>
					<div class="text-muted small">${galeria.pagos.cuantos(a.vendidas, __("obra vendida"), __("obras vendidas"))}</div></td>
				<td class="text-right ${a.monto_listas ? "text-success bold" : "text-muted"}">${m(a.monto_listas)}
					<div class="text-muted small">${galeria.pagos.cuantos(a.listas, __("obra"), __("obras"))}</div></td>
				<td class="text-right ${a.por_pagar ? "text-danger" : "text-muted"}">${m(a.por_pagar)}</td>
				<td class="text-right text-muted">${m(a.monto_espera)}
					<div class="small">${galeria.pagos.cuantos(a.espera, __("obra"), __("obras"))}</div></td>
				<td class="text-right">${m(a.pagado)}</td>
				<td class="pa-acciones-fila">${a.listas ? this.btn("liquidar", a.artista, __("Liquidar"), "btn-primary") : ""}</td>
			</tr>`
			)
			.join("");
		this.$cuerpo.html(
			this.tabla(
				`<th>${__("Artista")}</th><th class="text-right">${__("Listo para liquidar")}</th>
				<th class="text-right">${__("Liquidaciones por pagar")}</th><th class="text-right">${__("En espera del cliente")}</th>
				<th class="text-right">${__("Pagado")}</th><th></th>`,
				filas
			)
		);
	}

	// ------------------------------------------------------------------
	// Liquidaciones
	// ------------------------------------------------------------------

	pintar_liquidaciones() {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		const f = this.filtro_liq;
		const opciones = ["Todas", "Por pagar", "Pagada", "Anulada"];
		const lista = this.datos.liquidaciones.filter((l) => f === "Todas" || l.estado === f);
		const filas = lista
			.map((l) => {
				const pago =
					l.estado === "Pagada"
						? `${esc(l.modo_pago || "")}${l.referencia ? " · " + esc(l.referencia) : ""}
							<div class="text-muted small">${frappe.datetime.str_to_user(l.fecha_pago)}</div>`
						: l.estado === "Anulada"
						? `<span class="text-muted">${esc(l.motivo_anulacion || "")}</span>`
						: `<span class="text-muted">${__("Sin pagar")}</span>`;
				return `
				<tr>
					<td><a href="/app/liquidacion-a-artista/${encodeURIComponent(l.name)}">${esc(l.name)}</a>
						<div class="text-muted small">${frappe.datetime.str_to_user(l.fecha)}</div></td>
					<td>${esc(l.artista)}</td>
					<td class="text-right">${l.num_obras}</td>
					<td class="text-right bold">${m(l.total)}</td>
					<td><span class="indicator-pill ${galeria.artistas.COLORES_LIQUIDACION[l.estado] || "gray"}">${esc(l.estado)}</span></td>
					<td>${pago}</td>
					<td class="pa-acciones-fila">
						${l.estado === "Por pagar" ? this.btn("pagar", l.name, __("Pagar"), "btn-primary") : ""}
						${this.btn("comprobante", l.name, __("Comprobante"))}
						${l.estado !== "Anulada" ? this.btn("anular", l.name, __("Anular")) : ""}
					</td>
				</tr>`;
			})
			.join("");
		this.$cuerpo.html(`
			<div style="margin-bottom: var(--margin-md)">
				<select class="form-control" data-filtro-liq style="max-width: 220px; height: 38px">
					${opciones.map((o) => `<option ${o === f ? "selected" : ""}>${o}</option>`).join("")}
				</select>
			</div>
			${
				lista.length
					? this.tabla(
							`<th>${__("Liquidación")}</th><th>${__("Artista")}</th><th class="text-right">${__("Obras")}</th>
							<th class="text-right">${__("Total")}</th><th>${__("Estado")}</th><th>${__("Pago")}</th><th></th>`,
							filas
					  )
					: `<div class="pa-vacio">${__("No hay liquidaciones con ese filtro.")}</div>`
			}`);
	}

	// ------------------------------------------------------------------
	// Obras vendidas
	// ------------------------------------------------------------------

	pintar_obras() {
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		const f = this.filtro_obras;
		const opciones = ["Todas", "Por liquidar", "En espera del cliente", "En liquidación", "Pagado al artista"];
		const lista = this.datos.obras.filter((o) => f === "Todas" || o.estado_pago === f);
		const filas = lista
			.map(
				(o) => `
			<tr>
				<td><a href="/app/obra-de-arte/${encodeURIComponent(o.name)}">${esc(o.titulo)}</a>
					<div class="text-muted small">${esc(o.artista)}</div></td>
				<td>${esc(o.cliente_nombre || o.cliente || "")}
					<div class="text-muted small">${frappe.datetime.str_to_user(o.fecha_venta)}</div></td>
				<td><a href="/app/sales-invoice/${encodeURIComponent(o.factura || "")}">${esc(o.factura || "")}</a></td>
				<td class="text-right">${m(o.precio_vendido)}</td>
				<td class="text-right bold">${m(o.monto_artista)}</td>
				<td class="text-right ${flt(o.saldo_cliente) > 0 ? "text-danger" : "text-muted"}">${m(o.saldo_cliente)}</td>
				<td><span class="indicator-pill ${galeria.artistas.COLORES_PAGO[o.estado_pago] || "gray"}">${esc(o.estado_pago)}</span>
					${o.liquidacion ? `<div class="small"><a href="/app/liquidacion-a-artista/${encodeURIComponent(o.liquidacion)}">${esc(o.liquidacion)}</a></div>` : ""}</td>
			</tr>`
			)
			.join("");
		this.$cuerpo.html(`
			<div style="margin-bottom: var(--margin-md)">
				<select class="form-control" data-filtro-obras style="max-width: 240px; height: 38px">
					${opciones.map((o) => `<option ${o === f ? "selected" : ""}>${o}</option>`).join("")}
				</select>
			</div>
			${
				lista.length
					? this.tabla(
							`<th>${__("Obra")}</th><th>${__("Cliente")}</th><th>${__("Factura")}</th>
							<th class="text-right">${__("Precio vendido")}</th><th class="text-right">${__("Para el artista")}</th>
							<th class="text-right">${__("Saldo del cliente")}</th><th>${__("Pago al artista")}</th>`,
							filas
					  )
					: `<div class="pa-vacio">${__("No hay obras vendidas con ese filtro.")}</div>`
			}`);
	}
}
