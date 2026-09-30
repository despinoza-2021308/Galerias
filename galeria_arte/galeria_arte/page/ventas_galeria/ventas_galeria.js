// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Ventas de la Galería: solo facturas de la serie de la galería, con filtros,
// totales y acciones (ver, cobrar, imprimir, estado de cuenta).

frappe.pages["ventas-galeria"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Ventas de la Galería"),
		single_column: true,
	});
	new VentasGaleria(page);
};

const ESTADOS = {
	Paid: [__("Pagada"), "green"],
	Unpaid: [__("Pendiente"), "orange"],
	"Partly Paid": [__("Pago parcial"), "yellow"],
	Overdue: [__("Vencida"), "red"],
};

class VentasGaleria {
	constructor(page) {
		this.page = page;
		const cambio = () => this.cargar();
		this.f = {
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
			area: page.add_field({
				fieldname: "area",
				label: __("Área"),
				fieldtype: "Select",
				options: ["", "Arte", "Eventos", "Cafetería"],
				change: cambio,
			}),
			cliente: page.add_field({
				fieldname: "cliente",
				label: __("Cliente"),
				fieldtype: "Link",
				options: "Customer",
				change: cambio,
			}),
			estado_pago: page.add_field({
				fieldname: "estado_pago",
				label: __("Estado de pago"),
				fieldtype: "Select",
				options: ["", "Pagada", "Pendiente", "Vencida"],
				change: cambio,
			}),
			fel: page.add_field({
				fieldname: "fel",
				label: __("FEL"),
				fieldtype: "Select",
				options: ["", "Certificada", "Pendiente de certificar"],
				change: cambio,
			}),
		};
		page.set_primary_action(__("Nueva factura"), () => this.nueva_factura(), "add");
		page.set_secondary_action(__("Actualizar"), () => this.cargar(), "refresh");
		page.add_menu_item(__("Cobros"), () => frappe.set_route("cobros-galeria"));
		page.add_menu_item(__("Cierre de caja"), () => frappe.new_doc("Cierre de Caja"));

		this.$totales = $(`<div class="row" style="margin-bottom: var(--margin-md)"></div>`).appendTo(page.main);
		this.$areas = $(`<div style="margin-bottom: var(--margin-lg)"></div>`).appendTo(page.main);
		this.$tabla = $(`<div></div>`).appendTo(page.main);

		this.$tabla.on("click", "[data-accion]", (e) => {
			const $b = $(e.currentTarget);
			const factura = $b.attr("data-factura");
			const accion = $b.attr("data-accion");
			if (accion === "ver") frappe.set_route("Form", "Sales Invoice", factura);
			if (accion === "cobrar") galeria.pagos.registrar(factura, () => this.cargar());
			if (accion === "estado") galeria.pagos.estado_cuenta(factura);
			if (accion === "imprimir") this.imprimir(factura);
		});
		this.cargar();
	}

	nueva_factura() {
		const conf = frappe.boot.galeria || {};
		frappe.new_doc("Sales Invoice", { naming_series: conf.serie_factura });
	}

	imprimir(factura) {
		const url =
			"/printview?doctype=Sales%20Invoice&name=" +
			encodeURIComponent(factura) +
			"&format=" +
			encodeURIComponent("Factura Galería") +
			"&no_letterhead=1&trigger_print=1";
		window.open(url, "_blank");
	}

	async cargar() {
		const v = (k) => this.f[k].get_value() || null;
		const r = await frappe.xcall("galeria_arte.api.facturacion.ventas", {
			desde: v("desde"),
			hasta: v("hasta"),
			area: v("area"),
			cliente: v("cliente"),
			estado_pago: v("estado_pago"),
			fel: v("fel"),
		});
		this.pintar_totales(r);
		this.pintar_tabla(r.facturas);
	}

	pintar_totales(r) {
		const m = galeria.pagos.moneda;
		const t = r.totales;
		const tarjeta = (label, valor, sub, clase) => `
			<div class="col-sm-3" style="margin-bottom: var(--margin-sm)">
				<div class="frappe-card" style="padding: var(--padding-md); height: 100%">
					<div class="text-muted small">${label}</div>
					<div class="h4 ${clase || ""}" style="margin: 4px 0 0">${valor}</div>
					${sub ? `<div class="text-muted small">${sub}</div>` : ""}
				</div>
			</div>`;
		const rango =
			frappe.datetime.str_to_user(r.desde) + " – " + frappe.datetime.str_to_user(r.hasta);
		this.$totales.html(
			tarjeta(__("Vendido hoy"), m(t.hoy)) +
				tarjeta(__("Vendido este mes"), m(t.mes)) +
				tarjeta(__("Vendido en el período"), m(t.rango), rango + " · " + r.facturas.length + " " + __("facturas")) +
				tarjeta(__("Pendiente de cobro (período)"), m(t.pendiente_rango), "", t.pendiente_rango ? "text-danger" : "")
		);
		const total = t.rango || 1;
		const colores = { Arte: "var(--purple-500)", Eventos: "var(--blue-500)", "Cafetería": "var(--orange-500)" };
		let barras = "";
		let leyenda = "";
		for (const [area, monto] of Object.entries(t.por_area)) {
			const pct = (flt(monto) / total) * 100;
			if (pct > 0) barras += `<div title="${area}" style="width:${pct}%; background:${colores[area]}"></div>`;
			leyenda += `<span style="margin-right: var(--margin-lg); white-space: nowrap">
				<span style="display:inline-block; width:10px; height:10px; border-radius:2px; background:${colores[area]}; margin-right:6px"></span>
				${area}: <b>${m(monto)}</b> <span class="text-muted">(${pct.toFixed(0)}%)</span></span>`;
		}
		if (t.sin_area) {
			leyenda += `<span class="text-muted" style="white-space: nowrap">${__("Sin área")}: ${m(t.sin_area)}</span>`;
		}
		this.$areas.html(`
			<div class="frappe-card" style="padding: var(--padding-md)">
				<div class="text-muted small" style="margin-bottom: 6px">${__("Ventas por área en el período")}</div>
				<div style="display:flex; height:10px; border-radius:5px; overflow:hidden; background: var(--gray-200); margin-bottom: 8px">${barras}</div>
				<div class="small">${leyenda}</div>
			</div>`);
	}

	pintar_tabla(facturas) {
		if (!facturas.length) {
			this.$tabla.html(
				`<div class="text-muted text-center" style="padding: var(--padding-xl)">${__(
					"No hay ventas de la galería con estos filtros."
				)}</div>`
			);
			return;
		}
		const m = galeria.pagos.moneda;
		const esc = frappe.utils.escape_html;
		const btn = (accion, factura, texto, clase = "btn-default") =>
			`<button class="btn btn-xs ${clase}" data-accion="${accion}" data-factura="${esc(factura)}">${texto}</button>`;
		const filas = facturas
			.map((x) => {
				const [estado, color] = ESTADOS[x.status] || [x.status, "gray"];
				return `
				<tr>
					<td><a href="/app/sales-invoice/${encodeURIComponent(x.name)}">${esc(x.name)}</a></td>
					<td class="nowrap">${frappe.datetime.str_to_user(x.posting_date)}</td>
					<td class="nowrap">${esc(x.customer_name || x.customer)}</td>
					<td>${esc(x.galeria_area || "")}</td>
					<td class="text-right">${m(x.grand_total)}</td>
					<td class="text-right text-success">${m(x.pagado)}</td>
					<td class="text-right ${flt(x.outstanding_amount) ? "text-danger" : "text-muted"}">${m(x.outstanding_amount)}</td>
					<td><span class="indicator-pill ${color}">${estado}</span></td>
					<td><span class="indicator-pill ${x.fel === "Certificada" ? "green" : "orange"}" title="FEL: ${x.fel}">${x.fel === "Certificada" ? __("Certificada") : __("Sin certificar")}</span></td>
					<td class="text-right" style="white-space: nowrap">
						${btn("estado", x.name, __("Estado de cuenta"))}
						${btn("imprimir", x.name, __("Imprimir"))}
						${flt(x.outstanding_amount) > 0 ? btn("cobrar", x.name, __("Cobrar"), "btn-primary") : ""}
					</td>
				</tr>`;
			})
			.join("");
		this.$tabla.html(`
			<div class="frappe-card" style="overflow-x: auto">
				<table class="table table-hover gal-tabla" style="margin: 0">
					<thead><tr>
						<th>${__("Factura")}</th><th>${__("Fecha")}</th><th>${__("Cliente")}</th><th>${__("Área")}</th>
						<th class="text-right">${__("Total")}</th><th class="text-right">${__("Pagado")}</th>
						<th class="text-right">${__("Pendiente")}</th><th>${__("Pago")}</th><th>${__("FEL")}</th><th></th>
					</tr></thead>
					<tbody>${filas}</tbody>
				</table>
			</div>`);
	}
}
