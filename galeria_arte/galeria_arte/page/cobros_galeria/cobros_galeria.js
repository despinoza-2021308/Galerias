// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Cobros: facturas de la galería con saldo pendiente, cuotas vencidas y
// registro de pagos (mixtos y abonos).

frappe.pages["cobros-galeria"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Cobros"), single_column: true });
	new CobrosGaleria(page);
};

class CobrosGaleria {
	constructor(page) {
		this.page = page;
		this.filtros = {
			cliente: page.add_field({
				fieldname: "cliente",
				label: __("Cliente"),
				fieldtype: "Link",
				options: "Customer",
				change: () => this.cargar(),
			}),
			area: page.add_field({
				fieldname: "area",
				label: __("Área"),
				fieldtype: "Select",
				options: ["", "Arte", "Eventos", "Cafetería"],
				change: () => this.cargar(),
			}),
			vencidas: page.add_field({
				fieldname: "vencidas",
				label: __("Solo vencidas"),
				fieldtype: "Check",
				change: () => this.cargar(),
			}),
		};
		page.set_primary_action(__("Actualizar"), () => this.cargar(), "refresh");
		page.add_menu_item(__("Cierre de caja"), () => frappe.new_doc("Cierre de Caja"));
		page.add_menu_item(__("Reporte de cuentas por cobrar"), () =>
			frappe.set_route("query-report", "Accounts Receivable")
		);

		this.$resumen = $(`<div class="row" style="margin-bottom: var(--margin-lg)"></div>`).appendTo(page.main);
		this.$tabla = $(`<div></div>`).appendTo(page.main);
		this.$tabla.on("click", "[data-cobrar]", (e) =>
			galeria.pagos.registrar($(e.currentTarget).attr("data-cobrar"), () => this.cargar())
		);
		this.$tabla.on("click", "[data-estado]", (e) =>
			galeria.pagos.estado_cuenta($(e.currentTarget).attr("data-estado"))
		);
		this.cargar();
	}

	async cargar() {
		const f = this.filtros;
		const facturas = await frappe.xcall("galeria_arte.api.facturacion.facturas_pendientes", {
			cliente: f.cliente.get_value() || null,
			area: f.area.get_value() || null,
			vencidas: f.vencidas.get_value() ? 1 : 0,
		});
		this.pintar_resumen(facturas);
		this.pintar_tabla(facturas);
	}

	pintar_resumen(facturas) {
		const m = galeria.pagos.moneda;
		const pendiente = facturas.reduce((s, x) => s + flt(x.outstanding_amount), 0);
		const vencido = facturas.filter((x) => x.vencida).reduce((s, x) => s + flt(x.proximo_monto), 0);
		const tarjeta = (label, valor, clase) => `
			<div class="col-sm-4">
				<div class="frappe-card" style="padding: var(--padding-md)">
					<div class="text-muted small">${label}</div>
					<div class="h4 ${clase || ""}" style="margin: 4px 0 0">${valor}</div>
				</div>
			</div>`;
		this.$resumen.html(
			tarjeta(__("Saldo pendiente total"), m(pendiente), "text-danger") +
				tarjeta(__("Cuotas vencidas"), m(vencido), vencido ? "text-danger" : "") +
				tarjeta(__("Facturas con saldo"), facturas.length)
		);
	}

	pintar_tabla(facturas) {
		if (!facturas.length) {
			this.$tabla.html(
				`<div class="text-muted text-center" style="padding: var(--padding-xl)">${__(
					"No hay facturas pendientes de cobro."
				)}</div>`
			);
			return;
		}
		const m = galeria.pagos.moneda;
		const esc = frappe.utils.escape_html;
		const filas = facturas
			.map(
				(x) => `
			<tr>
				<td><a href="/app/sales-invoice/${encodeURIComponent(x.name)}">${x.name}</a>
					<div class="text-muted small">${frappe.datetime.str_to_user(x.posting_date)}</div></td>
				<td class="nowrap">${esc(x.customer_name || x.customer)}</td>
				<td>${esc(x.galeria_area || "")}</td>
				<td>${esc(galeria.pagos.texto_plan(x))}</td>
				<td class="text-right">${m(x.grand_total)}</td>
				<td class="text-right text-success">${m(x.pagado)}</td>
				<td class="text-right text-danger bold">${m(x.outstanding_amount)}</td>
				<td class="${x.vencida ? "text-danger" : ""}">${frappe.datetime.str_to_user(x.proximo_vencimiento)}
					<div class="small">${m(x.proximo_monto)}${x.vencida ? " · " + __("Vencida") : ""}</div></td>
				<td><span class="indicator-pill ${x.fel === "Certificada" ? "green" : "orange"}" title="FEL: ${x.fel}">${x.fel === "Certificada" ? __("Certificada") : __("Sin certificar")}</span></td>
				<td class="text-right" style="white-space: nowrap">
					<button class="btn btn-xs btn-default" data-estado="${x.name}">${__("Ver")}</button>
					<button class="btn btn-xs btn-primary" data-cobrar="${x.name}">${__("Cobrar")}</button>
				</td>
			</tr>`
			)
			.join("");
		this.$tabla.html(`
			<div class="frappe-card" style="overflow-x: auto">
				<table class="table table-hover gal-tabla" style="margin: 0">
					<thead><tr>
						<th>${__("Factura")}</th><th>${__("Cliente")}</th><th>${__("Área")}</th><th>${__("Plan")}</th>
						<th class="text-right">${__("Total")}</th><th class="text-right">${__("Pagado")}</th>
						<th class="text-right">${__("Pendiente")}</th><th>${__("Próximo vencimiento")}</th>
						<th>${__("FEL")}</th><th></th>
					</tr></thead>
					<tbody>${filas}</tbody>
				</table>
			</div>`);
	}
}
