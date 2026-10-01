// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Dashboard de la galería: ventas por área, productos de cafetería, arte,
// eventos y subastas, cobros y clientes del período elegido.

frappe.pages["tablero-galeria"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Dashboard"), single_column: true });
	wrapper.tablero = new TableroGaleria(page);
};

frappe.pages["tablero-galeria"].on_page_show = function (wrapper) {
	if (wrapper.tablero && wrapper.tablero.visto) wrapper.tablero.cargar();
	if (wrapper.tablero) wrapper.tablero.visto = true;
};

const TAB_COLORES = { Arte: "#7C3AED", Eventos: "#EA580C", Cafetería: "#0D9488" };
const TAB_COLORES_CATEGORIA = ["#0D9488", "#F59E0B", "#EC4899", "#6366F1"];
const TAB_PERIODOS = ["Hoy", "Esta semana", "Este mes", "Mes anterior", "Este año", "Rango de fechas"];

// Porcentaje entero; lo que existe pero no llega a 1 % se muestra como "<1%".
function tab_pct(valor, total) {
	if (!total || !flt(valor)) return "0%";
	const p = Math.round((flt(valor) / total) * 100);
	return p === 0 ? "<1%" : `${p}%`;
}

class TableroGaleria {
	constructor(page) {
		this.page = page;
		this.graficas = [];
		const cambio = () => this.cargar();
		this.f = {
			periodo: page.add_field({
				fieldname: "periodo",
				label: __("Período"),
				fieldtype: "Select",
				options: TAB_PERIODOS.map((p) => ({ value: p, label: __(p) })),
				default: "Este mes",
				change: () => {
					const rango = this.f.periodo.get_value() === "Rango de fechas";
					this.f.desde.$wrapper.toggle(rango);
					this.f.hasta.$wrapper.toggle(rango);
					if (!rango) this.cargar();
				},
			}),
			desde: page.add_field({
				fieldname: "desde",
				label: __("Desde"),
				fieldtype: "Date",
				default: frappe.datetime.month_start(),
				change: cambio,
			}),
			hasta: page.add_field({
				fieldname: "hasta",
				label: __("Hasta"),
				fieldtype: "Date",
				default: frappe.datetime.get_today(),
				change: cambio,
			}),
		};
		this.f.desde.$wrapper.hide();
		this.f.hasta.$wrapper.hide();
		page.set_secondary_action(__("Actualizar"), cambio, "refresh");
		page.add_menu_item(__("Ventas"), () => frappe.set_route("ventas-galeria"));
		page.add_menu_item(__("Cobros"), () => frappe.set_route("cobros-galeria"));
		page.add_menu_item(__("Pagos a artistas"), () => frappe.set_route("pagos-artistas"));

		this.$cuerpo = $(`<div class="tab-gal"></div>`).appendTo(page.main);
		this.$cuerpo.on("click", "[data-ir]", (e) => {
			e.preventDefault();
			frappe.set_route(...$(e.currentTarget).attr("data-ir").split("|"));
		});
		this.$cuerpo.on("click", "[data-cliente]", (e) => {
			frappe.route_options = { cliente: $(e.currentTarget).attr("data-cliente") };
			frappe.set_route("ficha-coleccionista");
		});
		this.cargar();
	}

	rango() {
		const hoy = moment(frappe.datetime.get_today());
		const f = (m) => m.format("YYYY-MM-DD");
		switch (this.f.periodo.get_value()) {
			case "Hoy":
				return [f(hoy), f(hoy)];
			case "Esta semana":
				return [f(hoy.clone().isoWeekday(1)), f(hoy)];
			case "Mes anterior": {
				const m = hoy.clone().subtract(1, "month");
				return [f(m.clone().startOf("month")), f(m.clone().endOf("month"))];
			}
			case "Este año":
				return [f(hoy.clone().startOf("year")), f(hoy)];
			case "Rango de fechas":
				return [this.f.desde.get_value(), this.f.hasta.get_value()];
			default:
				return [f(hoy.clone().startOf("month")), f(hoy)];
		}
	}

	async cargar() {
		const [desde, hasta] = this.rango();
		if (!desde || !hasta) return;
		this.datos = await frappe.xcall("galeria_arte.api.tablero.datos", { desde, hasta });
		this.pintar();
	}

	// ------------------------------------------------------------------
	// Pintado
	// ------------------------------------------------------------------

	pintar() {
		const d = this.datos;
		const fecha = (x) => frappe.datetime.str_to_user(x);
		const periodo =
			d.desde === d.hasta ? fecha(d.desde) : `${fecha(d.desde)} ${__("al")} ${fecha(d.hasta)}`;
		// Las gráficas anteriores se liberan (se ajustan solas al ancho mientras existen).
		this.graficas.forEach((g) => g.destroy && g.destroy());
		this.graficas = [];
		this.$cuerpo.html(`
			<div class="tab-periodo text-muted">${periodo} · ${__("comparado con")} ${fecha(d.anterior.desde)} ${__("al")} ${fecha(
			d.anterior.hasta
		)}</div>
			${this.html_resumen()}
			${this.seccion(__("Ventas por área"), `
				<div class="tab-fila tab-fila-1-2">
					<div class="tab-caja"><div class="tab-caja-titulo">${__("Reparto")}</div><div data-grafica="areas"></div>${this.html_leyenda_areas()}</div>
					<div class="tab-caja"><div class="tab-caja-titulo">${__("Ventas por {0}", [__(d.areas.escala)])}</div><div data-grafica="serie"></div></div>
				</div>`)}
			${this.html_productos()}
			${this.html_arte()}
			${this.html_eventos()}
			${this.html_cobros()}
			${this.html_clientes()}`);
		this.graficas_areas();
		this.graficas_productos();
		this.graficas_cobros();
	}

	seccion(titulo, cuerpo, sub = "") {
		return `<div class="tab-seccion"><div class="tab-seccion-titulo">${titulo}${sub ? `<span class="text-muted">${sub}</span>` : ""}</div>${cuerpo}</div>`;
	}

	tarjeta(label, valor, sub = "", clase = "", ir = "") {
		return `<div class="tab-tarjeta ${ir ? "tab-clic" : ""}" ${ir ? `data-ir="${ir}"` : ""}>
			<div class="tab-tarjeta-label">${label}</div>
			<div class="tab-tarjeta-valor ${clase}">${valor}</div>
			${sub ? `<div class="tab-tarjeta-sub">${sub}</div>` : ""}
		</div>`;
	}

	dato(label, valor, clase = "") {
		return `<div class="tab-dato"><div class="tab-dato-label">${label}</div><div class="tab-dato-valor ${clase}">${valor}</div></div>`;
	}

	vacio(texto) {
		return `<div class="tab-vacio">${texto}</div>`;
	}

	// Barra horizontal proporcional para las tablas de ranking.
	barra(valor, maximo, color = "#2563EB") {
		const pct = maximo > 0 ? Math.max(2, Math.round((valor / maximo) * 100)) : 0;
		return `<div class="tab-barra"><div style="width:${pct}%; background:${color}"></div></div>`;
	}

	html_resumen() {
		const r = this.datos.resumen;
		const m = galeria.pagos.moneda;
		let cambio = __("Sin ventas en el período anterior");
		if (r.cambio !== null) {
			const sube = r.cambio >= 0;
			// Contra un período casi sin ventas el % se dispara: se muestra acotado.
			const pct = Math.abs(r.cambio) > 999 ? __("más de 999") : Math.abs(r.cambio);
			cambio = `<span class="${sube ? "text-success" : "text-danger"}">${sube ? "▲" : "▼"} ${pct}%</span> ${__(
				"vs. período anterior"
			)}`;
		}
		const g = r.ganancia_por_area;
		return `<div class="tab-tarjetas">
			${this.tarjeta(__("Ventas del período"), m(r.ventas), cambio, "", "ventas-galeria")}
			${this.tarjeta(
				__("Facturas"),
				r.facturas,
				r.facturas ? `${__("Ticket promedio")}: ${m(r.ticket_promedio)}` : "",
				"",
				"ventas-galeria"
			)}
			${this.tarjeta(__("Cobrado en el período"), m(r.cobrado), __("Dinero que entró"), "text-success", "cobros-galeria")}
			${this.tarjeta(
				__("Saldo por cobrar"),
				m(r.por_cobrar),
				flt(r.vencido) ? `<span class="text-danger">${__("Vencido")}: ${m(r.vencido)}</span>` : __("Nada vencido"),
				flt(r.por_cobrar) ? "text-danger" : "",
				"cobros-galeria"
			)}
			${this.tarjeta(
				__("Por pagar a artistas"),
				m(r.por_pagar_artistas),
				galeria.pagos.cuantos(r.obras_por_liquidar, __("obra por liquidar"), __("obras por liquidar")) +
					(r.liquidaciones_por_pagar ? ` · ${galeria.pagos.cuantos(r.liquidaciones_por_pagar, __("liquidación"), __("liquidaciones"))}` : ""),
				"",
				"pagos-artistas"
			)}
			${this.tarjeta(
				__("Ganancia estimada (sin IVA)"),
				m(r.ganancia),
				`${__("Arte")} ${m(g["Arte"])} · ${__("Eventos")} ${m(g["Eventos"])} · ${__("Cafetería")} ${m(g["Cafetería"])}`,
				flt(r.ganancia) < 0 ? "text-danger" : "text-success"
			)}
		</div>
		<div class="tab-nota text-muted">${__(
			"Ganancia estimada: en arte es el precio sin IVA menos lo del artista; en cafetería y eventos es la venta sin IVA, porque no se registra el costo de los productos."
		)}</div>`;
	}

	html_leyenda_areas() {
		const t = this.datos.areas.totales;
		const total = Object.values(t).reduce((s, v) => s + flt(v), 0);
		const m = galeria.pagos.moneda;
		return `<div class="tab-leyenda">${Object.keys(TAB_COLORES)
			.map(
				(a) => `<div><span class="tab-muestra" style="background:${TAB_COLORES[a]}"></span>${__(a)}
					<b>${m(t[a])}</b><span class="text-muted">${tab_pct(t[a], total)}</span></div>`
			)
			.join("")}</div>`;
	}

	html_leyenda_categorias() {
		const cats = this.datos.productos.por_categoria;
		const total = cats.reduce((s, c) => s + flt(c.ingreso), 0);
		const m = galeria.pagos.moneda;
		if (!total) return "";
		return `<div class="tab-leyenda">${cats
			.map(
				(c, i) => `<div><span class="tab-muestra" style="background:${TAB_COLORES_CATEGORIA[i % TAB_COLORES_CATEGORIA.length]}"></span>${frappe.utils.escape_html(
					c.grupo
				)} <span class="text-muted">(${c.cantidad})</span><b>${m(c.ingreso)}</b><span class="text-muted">${tab_pct(c.ingreso, total)}</span></div>`
			)
			.join("")}</div>`;
	}

	html_productos() {
		const p = this.datos.productos;
		const m = galeria.pagos.moneda;
		const esc = frappe.utils.escape_html;
		const max = Math.max(...p.top.map((x) => x.cantidad), 0);
		const top = p.top.length
			? `<table class="tab-tabla"><thead><tr><th>#</th><th>${__("Producto")}</th><th class="text-right">${__("Cantidad")}</th>
				<th class="tab-col-barra"></th><th class="text-right">${__("Ingreso")}</th></tr></thead><tbody>
				${p.top
					.map(
						(x, i) => `<tr><td class="text-muted">${i + 1}</td>
						<td>${esc(x.nombre)}<span class="tab-sub">${esc(x.grupo)}</span></td>
						<td class="text-right"><b>${x.cantidad}</b></td>
						<td class="tab-col-barra">${this.barra(x.cantidad, max, TAB_COLORES["Cafetería"])}</td>
						<td class="text-right">${m(x.ingreso)}</td></tr>`
					)
					.join("")}</tbody></table>`
			: this.vacio(__("No hubo ventas de cafetería en el período."));
		const sin_ventas = p.sin_ventas.length
			? `<div class="tab-chips">${p.sin_ventas
					.map((x) => `<span class="tab-chip" title="${esc(x.grupo)}">${esc(x.nombre)}</span>`)
					.join("")}</div>`
			: `<div class="text-success small">${__("Todos los productos tuvieron ventas.")}</div>`;
		const listas = p.por_lista.length
			? p.por_lista.map((l) => `<span>${__("Precio")} ${esc(l.lista)}: <b>${m(l.total)}</b></span>`).join(" · ")
			: "";
		return this.seccion(
			__("Cafetería"),
			`<div class="tab-datos">
				${this.dato(__("Vendido"), m(p.ingreso))}
				${this.dato(__("Tickets"), p.tickets)}
				${this.dato(__("Unidades"), p.unidades)}
				${this.dato(__("Productos distintos"), p.total_productos)}
			</div>
			<div class="tab-fila tab-fila-2-1">
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Productos más vendidos")}</div>${top}</div>
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Por categoría")}</div><div data-grafica="categorias"></div>
					${this.html_leyenda_categorias()}
					${listas ? `<div class="tab-nota text-muted">${listas}</div>` : ""}</div>
			</div>
			<div class="tab-fila tab-fila-1-1">
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Ventas por día de la semana")}</div><div data-grafica="dias"></div></div>
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Ventas por hora")}</div><div data-grafica="horas"></div></div>
			</div>
			<div class="tab-caja"><div class="tab-caja-titulo">${__("Productos sin ventas en el período")}
				<span class="text-muted">(${p.sin_ventas.length})</span></div>${sin_ventas}</div>`
		);
	}

	html_arte() {
		const a = this.datos.arte;
		const m = galeria.pagos.moneda;
		const esc = frappe.utils.escape_html;
		const max = Math.max(...a.por_artista.map((x) => x.monto), 0);
		const artistas = a.por_artista.length
			? `<table class="tab-tabla"><thead><tr><th>${__("Artista")}</th><th class="text-right">${__("Obras")}</th>
				<th class="tab-col-barra"></th><th class="text-right">${__("Vendido")}</th><th class="text-right">${__("Para el artista")}</th></tr></thead><tbody>
				${a.por_artista
					.map(
						(x) => `<tr><td>${esc(x.artista)}</td><td class="text-right">${x.obras}</td>
						<td class="tab-col-barra">${this.barra(x.monto, max, TAB_COLORES["Arte"])}</td>
						<td class="text-right"><b>${m(x.monto)}</b></td><td class="text-right">${m(x.para_artista)}</td></tr>`
					)
					.join("")}</tbody></table>`
			: this.vacio(__("No se vendieron obras en el período."));
		const total_canal = a.canales.reduce((s, c) => s + c.obras, 0);
		const colores_canal = { Directa: "#7C3AED", "Desde reserva": "#C084FC", Subasta: "#0891B2" };
		const canales = total_canal
			? `<div class="tab-apilada">${a.canales
					.filter((c) => c.obras)
					.map((c) => `<div style="width:${(c.obras / total_canal) * 100}%; background:${colores_canal[c.canal]}"></div>`)
					.join("")}</div>
				<div class="tab-leyenda">${a.canales
					.map(
						(c) => `<div><span class="tab-muestra" style="background:${colores_canal[c.canal]}"></span>${__(c.canal)}
						<b>${c.obras}</b><span class="text-muted">${m(c.monto)}</span></div>`
					)
					.join("")}</div>`
			: this.vacio(__("Sin ventas de obras."));
		const inventario = a.inventario
			.map(
				(i) => `<div class="tab-inv"><span class="indicator-pill ${galeria.obras.COLORES_ESTADO[i.estado] || "gray"}">${__(i.estado)}</span>
				<b>${i.obras}</b><span class="text-muted">${m(i.valor)}</span></div>`
			)
			.join("");
		return this.seccion(
			__("Arte"),
			`<div class="tab-datos">
				${this.dato(__("Obras vendidas"), a.vendidas)}
				${this.dato(__("Vendido"), m(a.monto))}
				${this.dato(__("Para los artistas"), m(a.para_artistas))}
				${this.dato(__("Precio promedio"), a.vendidas ? m(a.ticket_promedio) : "—")}
				${this.dato(
					__("Días promedio hasta venderse"),
					a.dias_promedio_venta === null ? "—" : galeria.pagos.cuantos(a.dias_promedio_venta, __("día"), __("días"))
				)}
			</div>
			<div class="tab-fila tab-fila-2-1">
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Ventas por artista")}</div>${artistas}</div>
				<div class="tab-caja">
					<div class="tab-caja-titulo">${__("Cómo se vendieron")}</div>${canales}
					<div class="tab-caja-titulo" style="margin-top: var(--margin-lg)">${__("Obras en la galería")}</div>
					<div class="tab-inventario tab-clic" data-ir="catalogo-obras">${inventario}</div>
				</div>
			</div>`
		);
	}

	html_eventos() {
		const e = this.datos.eventos;
		const m = galeria.pagos.moneda;
		const esc = frappe.utils.escape_html;
		const s = e.subastas;
		const cenas = e.cenas.length
			? `<table class="tab-tabla"><thead><tr><th>${__("Cena")}</th><th class="text-right">${__("Lugares")}</th>
				<th class="tab-col-barra">${__("Ocupación")}</th><th class="text-right">${__("Ingreso")}</th></tr></thead><tbody>
				${e.cenas
					.map(
						(c) => `<tr><td>${esc(c.nombre)}<span class="tab-sub">${frappe.datetime.str_to_user(String(c.inicio).slice(0, 10))}</span></td>
						<td class="text-right">${c.vendidos}/${c.cupo}</td>
						<td class="tab-col-barra">${this.barra(c.ocupacion, 100, TAB_COLORES["Eventos"])}<span class="tab-sub">${c.ocupacion}%</span></td>
						<td class="text-right">${m(c.ingreso)}</td></tr>`
					)
					.join("")}</tbody></table>`
			: this.vacio(__("No hubo cenas en el período."));
		const alq = e.alquileres.por_estado;
		const estados_alq = Object.keys(alq).length
			? Object.keys(alq)
					.map((k) => `<span class="indicator-pill ${galeria.eventos.COLORES_ESTADO[k] || "gray"}">${__(k)}: ${alq[k]}</span>`)
					.join(" ")
			: `<span class="text-muted">${__("Sin alquileres")}</span>`;
		const subastas = s.ofrecidas
			? `<div class="tab-datos tab-datos-compactos">
					${this.dato(__("Obras ofrecidas"), s.ofrecidas)}
					${this.dato(__("Vendidas"), s.vendidas)}
					${this.dato(__("Total ganador"), m(s.total_ganador))}
					${this.dato(__("Sobre el precio inicial"), s.alza === null ? "—" : `${s.alza > 0 ? "+" : ""}${s.alza}%`, s.alza > 0 ? "text-success" : "")}
				</div>
				<div class="small text-muted">${[
					s.no_vendidas ? galeria.pagos.cuantos(s.no_vendidas, __("no vendida"), __("no vendidas")) : "",
					s.pendientes ? galeria.pagos.cuantos(s.pendientes, __("sin resultado"), __("sin resultado")) : "",
				]
					.filter(Boolean)
					.join(" · ")}</div>
				${
					s.no_pagaron
						? `<div class="small text-danger">${
								s.no_pagaron === 1 ? __("1 ganador no pagó a tiempo") : __("{0} ganadores no pagaron a tiempo", [s.no_pagaron])
						  }</div>`
						: ""
				}`
			: this.vacio(__("No hubo subastas en el período."));
		return this.seccion(
			__("Eventos y subastas"),
			`<div class="tab-datos">
				${this.dato(__("Eventos"), e.total)}
				${this.dato(__("Exposiciones"), e.por_tipo["Exposición"])}
				${this.dato(__("Cenas"), e.por_tipo["Cena"])}
				${this.dato(__("Subastas"), e.por_tipo["Subasta"])}
				${this.dato(__("Alquileres"), e.por_tipo["Alquiler"])}
				${this.dato(__("Ingresos por boletos y alquileres"), m(e.ingreso_eventos))}
			</div>
			<div class="tab-fila tab-fila-2-1">
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Ocupación de las cenas")}</div>${cenas}</div>
				<div class="tab-caja">
					<div class="tab-caja-titulo">${__("Subastas")}</div>${subastas}
					<div class="tab-caja-titulo" style="margin-top: var(--margin-lg)">${__("Alquileres")}</div>
					<div>${estados_alq}</div>
					<div class="small text-muted" style="margin-top: 6px">${__("Facturado")}: ${m(e.alquileres.ingreso)}</div>
				</div>
			</div>`,
			` · ${__("por fecha del evento")}`
		);
	}

	html_cobros() {
		const c = this.datos.cobros;
		const m = galeria.pagos.moneda;
		const esc = frappe.utils.escape_html;
		const proximas = c.proximas.length
			? `<table class="tab-tabla"><thead><tr><th>${__("Vence")}</th><th>${__("Cliente")}</th><th class="text-right">${__("Monto")}</th></tr></thead><tbody>
				${c.proximas
					.map(
						(x) => `<tr class="tab-clic" data-ir="Form|Sales Invoice|${esc(x.factura)}"><td>${frappe.datetime.str_to_user(x.vence)}</td>
						<td>${esc(x.cliente)}<span class="tab-sub">${esc(x.factura)}${x.cuota ? ` · ${__("cuota {0} de {1}", [x.cuota, x.cuotas])}` : ""}</span></td>
						<td class="text-right">${m(x.monto)}</td></tr>`
					)
					.join("")}</tbody></table>`
			: this.vacio(__("Nada vence en los próximos 7 días."));
		const deudores = c.deudores.length
			? `<table class="tab-tabla"><tbody>${c.deudores
					.map(
						(x) => `<tr class="tab-clic" data-cliente="${esc(x.cliente)}"><td>${esc(x.nombre)}
						<span class="tab-sub">${galeria.pagos.cuantos(x.facturas, __("factura"), __("facturas"))}</span></td>
						<td class="text-right text-danger">${m(x.saldo)}</td></tr>`
					)
					.join("")}</tbody></table>`
			: this.vacio(__("Nadie tiene saldo pendiente."));
		return this.seccion(
			__("Cobros"),
			`<div class="tab-fila tab-fila-1-1">
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Cobrado por forma de pago")}</div><div data-grafica="formas"></div></div>
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Antigüedad del saldo por cobrar")}</div>${this.html_antiguedad()}</div>
			</div>
			<div class="tab-fila tab-fila-1-1">
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Vence en los próximos 7 días")}</div>${proximas}</div>
				<div class="tab-caja"><div class="tab-caja-titulo">${__("Clientes con más saldo pendiente")}</div>${deudores}</div>
			</div>`
		);
	}

	html_antiguedad() {
		const c = this.datos.cobros;
		const m = galeria.pagos.moneda;
		const colores = { "Al día": "#16A34A", "1 a 30 días": "#F59E0B", "31 a 60 días": "#EA580C", "Más de 60 días": "#DC2626" };
		const total = c.antiguedad.reduce((s, x) => s + flt(x.monto), 0);
		if (!total) return this.vacio(__("No hay saldo por cobrar."));
		return `<div class="tab-apilada">${c.antiguedad
			.filter((x) => flt(x.monto) > 0)
			.map((x) => `<div style="width:${(flt(x.monto) / total) * 100}%; background:${colores[x.tramo]}"></div>`)
			.join("")}</div>
			<div class="tab-leyenda">${c.antiguedad
				.map(
					(x) => `<div><span class="tab-muestra" style="background:${colores[x.tramo]}"></span>${
						x.tramo === "Al día" ? __("Al día") : __("Vencido {0}", [__(x.tramo)])
					}<b class="${x.tramo !== "Al día" && flt(x.monto) ? "text-danger" : ""}">${m(x.monto)}</b>
					<span class="text-muted">${tab_pct(x.monto, total)}</span></div>`
				)
				.join("")}</div>`;
	}

	html_clientes() {
		const lista = this.datos.clientes;
		const m = galeria.pagos.moneda;
		const esc = frappe.utils.escape_html;
		const max = Math.max(...lista.map((x) => x.total), 0);
		const tabla = lista.length
			? `<table class="tab-tabla"><thead><tr><th>#</th><th>${__("Cliente")}</th><th>${__("Áreas")}</th>
				<th class="tab-col-barra"></th><th class="text-right">${__("Comprado")}</th></tr></thead><tbody>
				${lista
					.map(
						(x, i) => `<tr class="tab-clic" data-cliente="${esc(x.cliente)}"><td class="text-muted">${i + 1}</td>
						<td>${esc(x.nombre)}<span class="tab-sub">${esc(x.tipo || __("Sin tipo"))} · ${galeria.pagos.cuantos(
							x.facturas,
							__("factura"),
							__("facturas")
						)}</span></td>
						<td>${x.areas.map((a) => `<span class="tab-muestra" title="${esc(a)}" style="background:${TAB_COLORES[a] || "#9CA3AF"}"></span>`).join("")}</td>
						<td class="tab-col-barra">${this.barra(x.total, max)}</td>
						<td class="text-right"><b>${m(x.total)}</b></td></tr>`
					)
					.join("")}</tbody></table>`
			: this.vacio(__("No hay compras de clientes registrados en el período."));
		return this.seccion(__("Mejores clientes"), `<div class="tab-caja">${tabla}</div>`, ` · ${__("sin Consumidor Final")}`);
	}

	// ------------------------------------------------------------------
	// Gráficas (Frappe Charts)
	// ------------------------------------------------------------------

	grafica(nombre, opciones, hay_datos = true) {
		const $el = this.$cuerpo.find(`[data-grafica="${nombre}"]`);
		if (!$el.length) return;
		if (!hay_datos) {
			$el.html(this.vacio(__("Sin datos en el período.")));
			return;
		}
		const m = galeria.pagos.moneda;
		this.graficas.push(
			new frappe.Chart($el[0], {
				height: 220,
				tooltipOptions: { formatTooltipY: (v) => (opciones.no_moneda ? v : m(v)) },
				axisOptions: { xIsSeries: 1, shortenYAxisNumbers: 1 },
				...opciones,
			})
		);
	}

	graficas_areas() {
		const a = this.datos.areas;
		const areas = Object.keys(TAB_COLORES);
		const total = areas.reduce((s, x) => s + flt(a.totales[x]), 0);
		this.grafica(
			"areas",
			{
				type: "donut",
				data: { labels: areas.map((x) => __(x)), datasets: [{ values: areas.map((x) => flt(a.totales[x])) }] },
				colors: areas.map((x) => TAB_COLORES[x]),
				maxSlices: 3,
				height: 180,
				showLegend: 0,
			},
			total > 0
		);
		this.grafica(
			"serie",
			{
				type: "bar",
				data: {
					labels: a.etiquetas,
					datasets: areas.map((x) => ({ name: __(x), values: a.series[x] })),
				},
				colors: areas.map((x) => TAB_COLORES[x]),
				barOptions: { stacked: 1, spaceRatio: 0.4 },
			},
			total > 0
		);
	}

	graficas_productos() {
		const p = this.datos.productos;
		const cats = p.por_categoria;
		this.grafica(
			"categorias",
			{
				type: "donut",
				data: { labels: cats.map((c) => c.grupo), datasets: [{ values: cats.map((c) => c.ingreso) }] },
				colors: TAB_COLORES_CATEGORIA,
				height: 180,
				showLegend: 0,
			},
			cats.some((c) => c.ingreso > 0)
		);
		this.grafica(
			"dias",
			{
				type: "bar",
				data: { labels: p.por_dia.etiquetas.map((x) => __(x)), datasets: [{ name: __("Ventas"), values: p.por_dia.valores }] },
				colors: [TAB_COLORES["Cafetería"]],
				axisOptions: { shortenYAxisNumbers: 1 },
			},
			p.por_dia.valores.some((v) => v > 0)
		);
		this.grafica(
			"horas",
			{
				type: "bar",
				data: { labels: p.por_hora.etiquetas, datasets: [{ name: __("Ventas"), values: p.por_hora.valores }] },
				colors: ["#14B8A6"],
			},
			p.por_hora.valores.some((v) => v > 0)
		);
	}

	graficas_cobros() {
		const c = this.datos.cobros;
		this.grafica(
			"formas",
			{
				type: "bar",
				data: { labels: c.formas_pago.map((f) => f.modo), datasets: [{ name: __("Cobrado"), values: c.formas_pago.map((f) => f.total) }] },
				colors: ["#2563EB"],
				axisOptions: { shortenYAxisNumbers: 1 },
			},
			c.formas_pago.length > 0
		);
	}
}
