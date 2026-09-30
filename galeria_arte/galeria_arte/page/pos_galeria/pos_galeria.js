// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// POS de cafetería: productos por categoría, precios por lista, cobro mixto
// y factura de la galería en pocos toques.

frappe.pages["pos-galeria"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("POS Cafetería"), single_column: true });
	wrapper.pos = new PosGaleria(page);
};

const POS_API = "galeria_arte.api.pos";
const POS_COLORES = ["#4F46E5", "#0D9488", "#B45309", "#BE185D", "#2563EB", "#7C3AED", "#059669", "#C2410C"];

class PosGaleria {
	constructor(page) {
		this.page = page;
		this.carrito = {}; // item_code -> cantidad
		this.productos = [];
		this.categoria = "";
		this.busqueda = "";
		page.add_menu_item(__("Ventas de la galería"), () => frappe.set_route("ventas-galeria"));
		page.add_menu_item(__("Cierre de caja"), () => frappe.new_doc("Cierre de Caja"));
		this.iniciar();
	}

	async iniciar() {
		this.conf = await frappe.xcall(`${POS_API}.datos_pos`);
		this.lista = this.conf.lista_precios;
		this.cliente = this.conf.cliente;
		this.armar();
		await this.cargar_productos();
	}

	m(valor) {
		return format_currency(valor || 0, "GTQ");
	}

	armar() {
		const esc = frappe.utils.escape_html;
		const chips_cat = ["", ...this.conf.categorias]
			.map((c) => `<div class="pos-gal-chip ${c === "" ? "activo" : ""}" data-categoria="${esc(c)}">${c ? esc(c) : __("Todos")}</div>`)
			.join("");
		const chips_lista = this.conf.listas_precios
			.map((l) => `<div class="pos-gal-chip ${l === this.lista ? "activo" : ""}" data-lista="${esc(l)}">${esc(l)}</div>`)
			.join("");

		this.$root = $(`
			<div class="pos-gal">
				<div class="pos-gal-panel">
					<div class="pos-gal-barra">
						<div class="pos-gal-chips" data-grupo="categorias">${chips_cat}</div>
						<input type="search" class="form-control pos-gal-buscar" placeholder="${__("Buscar producto…")}">
					</div>
					<div class="pos-gal-barra">
						<span class="pos-gal-etiqueta">${__("Lista de precios")}</span>
						<div class="pos-gal-chips" data-grupo="listas">${chips_lista}</div>
					</div>
					<div class="pos-gal-productos"></div>
				</div>
				<div class="pos-gal-panel pos-gal-pedido">
					<div class="pos-gal-cliente">
						<div class="pos-gal-cliente-campo" style="flex: 1"></div>
						<button class="btn btn-default" data-accion="nuevo-cliente" title="${__("Cliente nuevo")}" style="height: 32px">+ ${__("Cliente")}</button>
					</div>
					<div class="pos-gal-lineas"></div>
					<div class="pos-gal-total"><span>${__("TOTAL")}</span><span data-total></span></div>
					<div class="pos-gal-iva" data-iva></div>
					<div class="pos-gal-acciones">
						<button class="btn btn-default" data-accion="vaciar">${__("Vaciar")}</button>
						<button class="btn btn-primary" data-accion="cobrar">${__("COBRAR")}</button>
					</div>
				</div>
				<div class="pos-gal-barra-movil">
					<button type="button" class="pos-gal-barra-total" data-accion="ver-pedido">
						<span data-movil-cantidad></span><span data-movil-total></span>
					</button>
					<button type="button" class="btn btn-primary" data-accion="cobrar">${__("COBRAR")}</button>
				</div>
			</div>`).appendTo(this.page.main);

		this.campo_cliente = frappe.ui.form.make_control({
			parent: this.$root.find(".pos-gal-cliente-campo"),
			df: {
				fieldtype: "Link",
				options: "Customer",
				label: __("Cliente"),
				fieldname: "cliente",
				change: () => {
					this.cliente = this.campo_cliente.get_value() || this.conf.cliente;
				},
			},
			render_input: true,
		});
		this.campo_cliente.set_value(this.cliente);

		this.$root.on("click", "[data-categoria]", (e) => {
			this.categoria = $(e.currentTarget).attr("data-categoria");
			this.marcar_chip(e.currentTarget);
			this.pintar_productos();
		});
		this.$root.on("click", "[data-lista]", async (e) => {
			this.lista = $(e.currentTarget).attr("data-lista");
			this.marcar_chip(e.currentTarget);
			await this.cargar_productos();
		});
		this.$root.on("input", ".pos-gal-buscar", (e) => {
			this.busqueda = (e.currentTarget.value || "").toLowerCase();
			this.pintar_productos();
		});
		this.$root.on("click", ".pos-gal-producto", (e) => this.sumar($(e.currentTarget).attr("data-item"), 1));
		this.$root.on("click", "[data-mas]", (e) => this.sumar($(e.currentTarget).attr("data-mas"), 1));
		this.$root.on("click", "[data-menos]", (e) => this.sumar($(e.currentTarget).attr("data-menos"), -1));
		this.$root.on("click", "[data-quitar]", (e) => this.sumar($(e.currentTarget).attr("data-quitar"), -Infinity));
		this.$root.on("click", "[data-accion=ver-pedido]", () =>
			this.$root.find(".pos-gal-pedido")[0].scrollIntoView({ behavior: "smooth", block: "start" })
		);
		this.$root.on("click", "[data-accion=vaciar]", () => this.vaciar());
		this.$root.on("click", "[data-accion=cobrar]", () => this.cobrar());
		this.$root.on("click", "[data-accion=nuevo-cliente]", () => this.nuevo_cliente());
	}

	marcar_chip(el) {
		$(el).siblings().removeClass("activo");
		$(el).addClass("activo");
	}

	async cargar_productos() {
		this.productos = await frappe.xcall(`${POS_API}.productos`, { lista_precios: this.lista });
		this.por_codigo = Object.fromEntries(this.productos.map((p) => [p.item_code, p]));
		// Un producto sin precio en la lista nueva sale del pedido.
		for (const codigo of Object.keys(this.carrito)) {
			if (!this.por_codigo[codigo]) delete this.carrito[codigo];
		}
		this.pintar_productos();
		this.pintar_pedido();
	}

	color(texto) {
		let h = 0;
		for (const c of texto) h = (h * 31 + c.charCodeAt(0)) >>> 0;
		return POS_COLORES[h % POS_COLORES.length];
	}

	iniciales(nombre) {
		return nombre
			.split(/\s+/)
			.filter((p) => p.length > 2 || /^[A-ZÁÉÍÓÚ]/.test(p))
			.slice(0, 2)
			.map((p) => p[0].toUpperCase())
			.join("");
	}

	pintar_productos() {
		const esc = frappe.utils.escape_html;
		const visibles = this.productos.filter(
			(p) =>
				(!this.categoria || p.item_group === this.categoria) &&
				(!this.busqueda || p.item_name.toLowerCase().includes(this.busqueda))
		);
		const $grid = this.$root.find(".pos-gal-productos");
		if (!visibles.length) {
			$grid.html(`<div class="pos-gal-vacio" style="grid-column: 1 / -1">${__("No hay productos con ese filtro.")}</div>`);
			return;
		}
		$grid.html(
			visibles
				.map((p) => {
					const cant = this.carrito[p.item_code];
					const foto = p.image
						? `<div class="pos-gal-foto" style="background-image: url('${encodeURI(p.image)}')"></div>`
						: `<div class="pos-gal-foto" style="background: ${this.color(p.item_group)}">${esc(this.iniciales(p.item_name))}</div>`;
					return `
					<button type="button" class="pos-gal-producto" data-item="${esc(p.item_code)}">
						${cant ? `<div class="pos-gal-cant">${cant}</div>` : ""}
						${foto}
						<div class="pos-gal-info">
							<div class="pos-gal-nombre">${esc(p.item_name)}</div>
							<div class="pos-gal-precio">${this.m(p.precio)}</div>
						</div>
					</button>`;
				})
				.join("")
		);
	}

	sumar(codigo, delta) {
		const nueva = (this.carrito[codigo] || 0) + delta;
		if (nueva > 0) this.carrito[codigo] = nueva;
		else delete this.carrito[codigo];
		this.pintar_productos();
		this.pintar_pedido();
	}

	lineas() {
		return Object.entries(this.carrito)
			.filter(([codigo]) => this.por_codigo[codigo])
			.map(([codigo, qty]) => ({ ...this.por_codigo[codigo], qty, total: qty * this.por_codigo[codigo].precio }));
	}

	total() {
		return flt(this.lineas().reduce((s, l) => s + l.total, 0), 2);
	}

	pintar_pedido() {
		const esc = frappe.utils.escape_html;
		const lineas = this.lineas();
		const $lineas = this.$root.find(".pos-gal-lineas");
		if (!lineas.length) {
			$lineas.html(`<div class="pos-gal-vacio">${__("Toque un producto para agregarlo al pedido.")}</div>`);
		} else {
			$lineas.html(
				lineas
					.map(
						(l) => `
					<div class="pos-gal-linea">
						<div class="pos-gal-linea-nombre">${esc(l.item_name)}</div>
						<div class="pos-gal-linea-total">${this.m(l.total)}</div>
						<div class="pos-gal-linea-precio">${this.m(l.precio)} ${__("c/u")}</div>
						<div class="pos-gal-qty">
							<button type="button" data-menos="${esc(l.item_code)}" aria-label="${__("Quitar uno")}">−</button>
							<span>${l.qty}</span>
							<button type="button" data-mas="${esc(l.item_code)}" aria-label="${__("Agregar uno")}">+</button>
							<button type="button" data-quitar="${esc(l.item_code)}" aria-label="${__("Quitar del pedido")}">×</button>
						</div>
					</div>`
					)
					.join("")
			);
		}
		const total = this.total();
		this.$root.find("[data-total]").text(this.m(total));
		this.$root.find("[data-iva]").text(total ? __("IVA incluido {0}", [this.m(total - total / 1.12)]) : "");
		const unidades = lineas.reduce((n, l) => n + l.qty, 0);
		this.$root.find("[data-movil-cantidad]").text(galeria.pagos.cuantos(unidades, __("producto"), __("productos")));
		this.$root.find("[data-movil-total]").text(this.m(total));
		this.$root.find(".pos-gal-barra-movil").toggleClass("visible", lineas.length > 0);
		this.$root.find("[data-accion=cobrar]").prop("disabled", !lineas.length);
		this.$root.find("[data-accion=vaciar]").prop("disabled", !lineas.length);
	}

	vaciar() {
		this.carrito = {};
		this.pintar_productos();
		this.pintar_pedido();
	}

	nuevo_cliente() {
		const d = new frappe.ui.Dialog({
			title: __("Cliente nuevo"),
			fields: [
				{ fieldtype: "Data", fieldname: "nombre", label: __("Nombre"), reqd: 1 },
				{ fieldtype: "Data", fieldname: "nit", label: __("NIT"), description: __("Déjelo vacío para Consumidor Final (CF).") },
			],
			primary_action_label: __("Crear"),
			primary_action: async (v) => {
				const c = await frappe.xcall(`${POS_API}.crear_cliente`, v);
				d.hide();
				this.cliente = c.name;
				this.campo_cliente.set_value(c.name);
				frappe.show_alert({
					message: c.existente ? __("Ya existía un cliente con ese NIT: {0}", [c.customer_name]) : __("Cliente creado"),
					indicator: c.existente ? "orange" : "green",
				});
			},
		});
		d.show();
	}

	// ------------------------------------------------------------------
	// Cobro
	// ------------------------------------------------------------------

	cobrar() {
		const total = this.total();
		if (!total) return;
		const esc = frappe.utils.escape_html;
		const modos = this.conf.modos_pago;
		const efectivo = modos.includes("Efectivo") ? "Efectivo" : modos[0];
		const rapidos = modos
			.map((mo) => `<button type="button" class="btn btn-default" data-rapido="${esc(mo)}">${esc(mo)}</button>`)
			.join("");

		const d = new frappe.ui.Dialog({
			title: __("Cobrar"),
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "html" }],
			primary_action_label: __("Confirmar venta"),
			primary_action: () => confirmar(),
		});
		const $w = d.fields_dict.html.$wrapper;
		$w.html(`
			<div class="pos-gal-cobro-total">
				<div class="text-muted">${__("Total a cobrar")}</div>
				<div class="monto">${this.m(total)}</div>
			</div>
			<div class="text-muted small" style="margin-bottom: 6px">${__("Pago completo con una forma de pago")}</div>
			<div class="pos-gal-rapidos">${rapidos}</div>
			<div class="text-muted small" style="margin-bottom: 6px">${__("Detalle de pagos (combine varias formas de pago)")}</div>
			<div data-pagos></div>
			<button type="button" class="btn btn-xs btn-default" data-agregar>+ ${__("Agregar forma de pago")}</button>
			<div class="form-group" data-bloque-recibido style="margin-top: var(--margin-md); max-width: 260px">
				<label class="control-label">${__("Efectivo recibido (para calcular el vuelto)")}</label>
				<input type="number" min="0" step="0.01" inputmode="decimal" class="form-control" data-recibido>
			</div>
			<div class="pos-gal-resumen">
				<div><div class="text-muted small">${__("Pagado")}</div><div class="valor" data-pagado></div></div>
				<div><div class="text-muted small">${__("Falta")}</div><div class="valor" data-falta></div></div>
				<div data-bloque-vuelto><div class="text-muted small">${__("Vuelto")}</div><div class="valor" data-vuelto></div></div>
			</div>`);

		const fila = (modo, monto) => `
			<div class="pos-gal-pago">
				<select class="form-control" data-modo>${modos
					.map((mo) => `<option ${mo === modo ? "selected" : ""}>${esc(mo)}</option>`)
					.join("")}</select>
				<input type="number" min="0" step="0.01" inputmode="decimal" class="form-control" data-monto value="${monto || ""}" placeholder="${__("Monto")}">
				<input type="text" class="form-control" data-ref placeholder="${__("Referencia")}">
				<button type="button" class="btn btn-default" data-borrar aria-label="${__("Quitar pago")}">×</button>
			</div>`;
		const $pagos = $w.find("[data-pagos]");

		const leer = () =>
			$pagos
				.find(".pos-gal-pago")
				.map((_, el) => ({
					modo_pago: $(el).find("[data-modo]").val(),
					monto: flt($(el).find("[data-monto]").val()),
					referencia: $(el).find("[data-ref]").val() || null,
				}))
				.get();

		const resumen = () => {
			const pagos = leer();
			const pagado = flt(pagos.reduce((s, p) => s + p.monto, 0), 2);
			const falta = flt(total - pagado, 2);
			const en_efectivo = flt(pagos.filter((p) => p.modo_pago === efectivo).reduce((s, p) => s + p.monto, 0), 2);
			// El efectivo recibido y el vuelto solo aplican si algún pago es en efectivo.
			const hay_efectivo = pagos.some((p) => p.modo_pago === efectivo);
			$w.find("[data-bloque-recibido], [data-bloque-vuelto]").toggle(hay_efectivo);
			$w.find(".pos-gal-resumen").toggleClass("sin-vuelto", !hay_efectivo);
			if (!hay_efectivo) $w.find("[data-recibido]").val("");
			const recibido = hay_efectivo ? flt($w.find("[data-recibido]").val()) : 0;
			const vuelto = recibido > 0 ? flt(recibido - en_efectivo, 2) : 0;
			$w.find("[data-pagado]").text(this.m(pagado));
			$w.find("[data-falta]")
				.text(falta < 0 ? __("Sobra {0}", [this.m(-falta)]) : this.m(falta))
				.toggleClass("text-danger", falta !== 0);
			$w.find("[data-vuelto]")
				.text(vuelto < 0 ? __("Falta efectivo") : this.m(vuelto))
				.toggleClass("text-danger", vuelto < 0);
			d.get_primary_btn().prop("disabled", falta !== 0 || vuelto < 0);
		};

		const pago_completo = (modo) => {
			$pagos.html(fila(modo, total));
			resumen();
		};

		$w.on("click", "[data-rapido]", (e) => pago_completo($(e.currentTarget).attr("data-rapido")));
		$w.on("click", "[data-agregar]", () => {
			const falta = flt(total - leer().reduce((s, p) => s + p.monto, 0), 2);
			const usados = leer().map((p) => p.modo_pago);
			const modo = modos.find((mo) => !usados.includes(mo)) || modos[0];
			$pagos.append(fila(modo, falta > 0 ? falta : ""));
			resumen();
		});
		$w.on("click", "[data-borrar]", (e) => {
			$(e.currentTarget).closest(".pos-gal-pago").remove();
			resumen();
		});
		$w.on("input change", "[data-monto], [data-modo], [data-recibido]", resumen);

		const confirmar = async () => {
			const pagos = leer().filter((p) => p.monto > 0);
			d.get_primary_btn().prop("disabled", true);
			try {
				const r = await frappe.xcall(`${POS_API}.vender`, {
					items: this.lineas().map((l) => ({ item_code: l.item_code, qty: l.qty })),
					pagos,
					cliente: this.cliente,
					lista_precios: this.lista,
				});
				const en_efectivo = pagos.filter((p) => p.modo_pago === efectivo).reduce((s, p) => s + p.monto, 0);
				const recibido = en_efectivo > 0 ? flt($w.find("[data-recibido]").val()) : 0;
				d.hide();
				this.venta_lista(r, recibido > 0 ? flt(recibido - en_efectivo, 2) : 0);
			} catch (err) {
				resumen();
			}
		};

		pago_completo(efectivo);
		d.show();
	}

	venta_lista(r, vuelto) {
		this.vaciar();
		this.cliente = this.conf.cliente;
		this.campo_cliente.set_value(this.cliente);
		const imprimir = () => {
			const url =
				"/printview?doctype=Sales%20Invoice&name=" +
				encodeURIComponent(r.factura) +
				"&format=" +
				encodeURIComponent(r.formato_ticket) +
				"&no_letterhead=1&trigger_print=1";
			window.open(url, "_blank");
		};
		const d = new frappe.ui.Dialog({
			title: __("Venta registrada"),
			fields: [{ fieldtype: "HTML", fieldname: "html" }],
			primary_action_label: __("Nueva venta"),
			primary_action: () => d.hide(),
			secondary_action_label: __("Imprimir ticket"),
			secondary_action: imprimir,
		});
		d.fields_dict.html.$wrapper.html(`
			<div class="text-center" style="padding: var(--padding-md) 0">
				<div class="text-muted">${__("Factura")}</div>
				<div class="h3" style="margin: 4px 0"><a href="/app/sales-invoice/${encodeURIComponent(r.factura)}" target="_blank">${frappe.utils.escape_html(r.factura)}</a></div>
				<div class="h4">${this.m(r.total)}</div>
				${vuelto > 0 ? `<div class="h3 text-success" style="margin-top: var(--margin-md)">${__("Vuelto: {0}", [this.m(vuelto)])}</div>` : ""}
				<div style="margin-top: var(--margin-md)"><span class="indicator-pill ${r.fel === "Certificada" ? "green" : "orange"}">FEL: ${r.fel}</span></div>
			</div>`);
		d.show();
	}
}
