// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Catálogo visual de obras: tarjetas con foto, estado, precio y acciones
// de reservar y vender.

frappe.pages["catalogo-obras"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Catálogo de Obras"), single_column: true });
	wrapper.catalogo = new CatalogoObras(page);
};

frappe.pages["catalogo-obras"].on_page_show = function (wrapper) {
	// Permite llegar con un filtro, p. ej. desde la ficha del artista.
	if (wrapper.catalogo && frappe.route_options) {
		wrapper.catalogo.aplicar_opciones(frappe.route_options);
		frappe.route_options = null;
	} else if (wrapper.catalogo && wrapper.catalogo.listo) {
		// La primera vez ya cargó el constructor; después se refresca al volver a la página.
		if (wrapper.catalogo.visto) wrapper.catalogo.cargar();
		wrapper.catalogo.visto = true;
	}
};

const CAT_ESTADOS = ["Disponible", "Reservada", "En subasta", "Vendida", "Devuelta al artista"];

class CatalogoObras {
	constructor(page) {
		this.page = page;
		this.estado = "";
		const cambio = () => this.cargar();
		this.f = {
			buscar: page.add_field({ fieldname: "buscar", label: __("Buscar"), fieldtype: "Data", change: cambio }),
			artista: page.add_field({
				fieldname: "artista",
				label: __("Artista"),
				fieldtype: "Link",
				options: "Artista",
				change: cambio,
			}),
			precio_min: page.add_field({
				fieldname: "precio_min",
				label: __("Precio desde"),
				fieldtype: "Currency",
				change: cambio,
			}),
			precio_max: page.add_field({
				fieldname: "precio_max",
				label: __("Precio hasta"),
				fieldtype: "Currency",
				change: cambio,
			}),
		};
		page.set_primary_action(__("Nueva obra"), () => frappe.new_doc("Obra de Arte"), "add");
		page.set_secondary_action(__("Actualizar"), () => this.cargar(), "refresh");
		page.add_menu_item(__("Venta de obras"), () => frappe.set_route("venta-obras"));
		page.add_menu_item(__("Artistas"), () => frappe.set_route("List", "Artista"));
		page.add_menu_item(__("Lista de obras"), () => frappe.set_route("List", "Obra de Arte"));

		this.$conteo = $(`<div class="cat-obras-conteo"></div>`).appendTo(page.main);
		this.$grid = $(`<div class="cat-obras-grid"></div>`).appendTo(page.main);

		this.$conteo.on("click", "[data-estado]", (e) => {
			this.estado = $(e.currentTarget).attr("data-estado");
			this.cargar();
		});
		this.$grid.on("click", "[data-accion]", (e) => {
			const $el = $(e.currentTarget);
			const obra = $el.attr("data-obra");
			const accion = $el.attr("data-accion");
			const recargar = () => this.cargar();
			if (accion === "ver") frappe.set_route("Form", "Obra de Arte", obra);
			if (accion === "reservar") galeria.obras.reservar(obra, recargar);
			if (accion === "vender") galeria.obras.vender(obra, recargar);
			if (accion === "cancelar") galeria.obras.cancelar_reserva($el.attr("data-reserva"), recargar);
			if (accion === "subasta") galeria.eventos.resumen($el.attr("data-subasta"), recargar);
		});

		this.listo = true;
		if (frappe.route_options) {
			this.aplicar_opciones(frappe.route_options);
			frappe.route_options = null;
		} else {
			this.cargar();
		}
	}

	async aplicar_opciones(opciones) {
		if (opciones.artista !== undefined) await this.f.artista.set_value(opciones.artista);
		if (opciones.estado !== undefined) this.estado = opciones.estado;
		this.cargar();
	}

	async cargar() {
		const v = (k) => this.f[k].get_value() || null;
		const r = await frappe.xcall("galeria_arte.api.obras.catalogo", {
			artista: v("artista"),
			estado: this.estado || null,
			precio_min: v("precio_min"),
			precio_max: v("precio_max"),
			buscar: v("buscar"),
		});
		this.pintar_conteo(r.conteo);
		this.pintar_obras(r.obras);
	}

	pintar_conteo(conteo) {
		const total = CAT_ESTADOS.reduce((s, e) => s + (conteo[e] || 0), 0);
		const chip = (estado, etiqueta, cantidad, extra = "") =>
			`<div class="cat-obras-chip ${this.estado === estado ? "activo" : ""} ${extra}" data-estado="${estado}">${etiqueta} · ${cantidad}</div>`;
		let html = chip("", __("Todas"), total);
		for (const e of CAT_ESTADOS) html += chip(e, e, conteo[e] || 0);
		if (conteo["Reserva vencida"]) {
			html += chip("Reserva vencida", __("Reservas vencidas"), conteo["Reserva vencida"], "alerta");
		}
		this.$conteo.html(html);
	}

	pintar_obras(obras) {
		if (!obras.length) {
			this.$grid.html(
				`<div class="cat-obras-vacio" style="grid-column: 1 / -1">${__("No hay obras con esos filtros.")}</div>`
			);
			return;
		}
		const esc = frappe.utils.escape_html;
		const m = galeria.pagos.moneda;
		this.$grid.html(
			obras
				.map((o) => {
					const medidas = [o.alto_cm, o.ancho_cm].filter((x) => flt(x) > 0).join(" × ");
					const detalle = [o.tecnica, o.anio || "", medidas ? medidas + " cm" : ""].filter(Boolean).join(" · ");
					const color = galeria.obras.COLORES_ESTADO[o.estado] || "gray";
					let nota = "";
					if (o.estado === "Reservada") {
						nota = `<div class="cat-obra-nota ${o.reserva_vencida ? "text-danger" : "text-muted"}">
							${esc(o.reservada_por || "")} · ${
							o.reserva_vencida ? __("reserva vencida el") : __("hasta el")
						} ${frappe.datetime.str_to_user(o.fecha_limite_reserva)} · ${__("abonado")} ${m(o.anticipo)}</div>`;
					} else if (o.estado === "Vendida") {
						nota = `<div class="cat-obra-nota text-muted">${__("Vendida a")} ${esc(o.cliente || "")}</div>`;
					} else if (o.estado === "En subasta") {
						nota = `<div class="cat-obra-nota text-muted">${__("En la subasta")} ${esc(o.subasta || "")}</div>`;
					}
					const b = (accion, texto, clase = "btn-default") =>
						`<button class="btn btn-sm ${clase}" data-accion="${accion}" data-obra="${esc(o.name)}">${texto}</button>`;
					let acciones = b("ver", __("Ver"));
					if (o.estado === "En subasta" && o.subasta) {
						acciones += `<button class="btn btn-sm btn-default" data-accion="subasta" data-obra="${esc(o.name)}" data-subasta="${esc(o.subasta)}">${__("Ver subasta")}</button>`;
					}
					if (o.estado === "Disponible") acciones += b("reservar", __("Reservar")) + b("vender", __("Vender"), "btn-primary");
					if (o.estado === "Reservada") {
						acciones +=
							`<button class="btn btn-sm btn-default" data-accion="cancelar" data-obra="${esc(o.name)}" data-reserva="${esc(o.reservacion || "")}">${__("Cancelar reserva")}</button>` +
							b("vender", __("Vender"), "btn-primary");
					}
					const apagada = o.estado === "Vendida" || o.estado === "Devuelta al artista";
					return `
					<div class="cat-obra ${apagada ? "apagada" : ""}">
						<div class="cat-obra-foto" data-accion="ver" data-obra="${esc(o.name)}">
							${galeria.obras.html_imagen(o.imagen, o.titulo, 190)}
							<span class="cat-obra-estado indicator-pill ${color}">${esc(o.estado)}</span>
						</div>
						<div class="cat-obra-cuerpo">
							<div class="cat-obra-titulo" data-accion="ver" data-obra="${esc(o.name)}">${esc(o.titulo)}</div>
							<div class="cat-obra-artista">${esc(o.artista)}</div>
							<div class="cat-obra-detalle">${esc(detalle)}</div>
							<div class="cat-obra-precio">${m(o.precio_venta)}</div>
							${nota}
							<div class="cat-obra-acciones">${acciones}</div>
						</div>
					</div>`;
				})
				.join("")
		);
	}
}
