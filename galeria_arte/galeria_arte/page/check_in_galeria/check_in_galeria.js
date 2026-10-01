// Copyright (c) 2026, despinoza-2021308 and contributors
// For license information, please see license.txt

// Check-in de las cenas: lee el QR del boleto con la cámara del celular (o el
// código escrito a mano) y lo marca como usado.

frappe.pages["check-in-galeria"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Check-in"), single_column: true });
	wrapper.checkin = new CheckIn(page);
};

frappe.pages["check-in-galeria"].on_page_show = function (wrapper) {
	const ci = wrapper.checkin;
	if (!ci) return;
	const evento = (frappe.route_options && frappe.route_options.evento) || frappe.utils.get_url_arg("evento");
	frappe.route_options = null;
	ci.cargar_eventos(evento);
};

frappe.pages["check-in-galeria"].on_page_hide = function (wrapper) {
	if (wrapper.checkin) wrapper.checkin.detener();
};

class CheckIn {
	constructor(page) {
		this.page = page;
		this.ultimo = { texto: null, cuando: 0 };
		this.campo = page.add_field({
			fieldname: "evento",
			label: __("Cena"),
			fieldtype: "Select",
			change: () => this.actualizar(),
		});
		page.set_secondary_action(__("Actualizar"), () => this.actualizar(), "refresh");

		this.$cuerpo = $(`<div class="ci-gal">
			<div class="ci-evento"></div>
			<div class="ci-resultado"></div>
			<div class="ci-camara"></div>
			<div class="ci-botones">
				<button type="button" class="btn btn-primary" data-camara>${__("Escanear con la cámara")}</button>
			</div>
			<div class="ci-manual">
				<input type="text" class="form-control" placeholder="${__("O escriba el número del boleto o pegue su código")}">
				<button type="button" class="btn btn-default">${__("Registrar")}</button>
			</div>
			<div class="ci-recientes"></div>
		</div>`).appendTo(page.main);
		this.$evento = this.$cuerpo.find(".ci-evento");
		this.$resultado = this.$cuerpo.find(".ci-resultado");
		this.$camara = this.$cuerpo.find(".ci-camara");
		this.$recientes = this.$cuerpo.find(".ci-recientes");
		this.$boton_camara = this.$cuerpo.find("[data-camara]");

		this.$boton_camara.on("click", () => (this.escaneando ? this.detener() : this.escanear()));
		const $input = this.$cuerpo.find(".ci-manual input");
		const manual = () => {
			const texto = $input.val().trim();
			if (texto) this.registrar(texto);
			$input.val("").trigger("focus");
		};
		this.$cuerpo.find(".ci-manual button").on("click", manual);
		// Solo Enter registra; el resto de teclas se escriben normal (un handler de
		// jQuery que devuelve false bloquearía la escritura).
		$input.on("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				manual();
			}
		});
	}

	async cargar_eventos(preferido) {
		const cenas = await frappe.xcall("galeria_arte.api.boletos.cenas_para_checkin");
		if (preferido && !cenas.some((c) => c.name === preferido)) {
			const r = await frappe.db.get_value("Evento", preferido, ["nombre", "inicio"]);
			if (r.message && r.message.nombre) cenas.unshift({ name: preferido, nombre: r.message.nombre, inicio: r.message.inicio });
		}
		const opciones = cenas.map((c) => ({
			value: c.name,
			label: `${c.nombre} · ${frappe.datetime.str_to_user(String(c.inicio).slice(0, 10))}`,
		}));
		this.campo.df.options = opciones;
		this.campo.refresh();
		const hoy = frappe.datetime.get_today();
		const elegido =
			preferido || (cenas.find((c) => String(c.inicio).slice(0, 10) === hoy) || cenas[0] || {}).name || "";
		this.campo.set_value(elegido);
		if (!cenas.length) {
			this.$evento.html(`<div class="text-muted">${__("No hay cenas próximas con boletos.")}</div>`);
		}
		this.actualizar();
	}

	async actualizar() {
		const evento = this.campo.get_value();
		if (!evento) return;
		const r = await frappe.xcall("galeria_arte.api.boletos.estado_checkin", { evento });
		const pct = r.total ? Math.round((r.llegaron / r.total) * 100) : 0;
		const esc = frappe.utils.escape_html;
		this.$evento.html(`
			<div class="ci-evento-nombre">${esc(r.nombre)}</div>
			<div class="text-muted">${galeria.eventos.rango(r.inicio, r.fin)} · ${esc(r.lugar || "")}</div>
			<div class="ci-contador"><b>${r.llegaron}</b><span class="text-muted">${__("de {0} han llegado", [r.total])}</span></div>
			<div class="ci-barra"><div style="width: ${pct}%"></div></div>`);
		this.$recientes.html(
			r.recientes.length
				? `<div class="text-muted" style="border: none"><b>${__("Últimos en llegar")}</b></div>` +
						r.recientes
							.map((x) => `<div><span>${esc(x.asistente)}</span><span class="text-muted">${String(x.ingreso || "").slice(11, 16)}</span></div>`)
							.join("")
				: `<div class="text-muted" style="border: none">${__("Todavía no ha llegado nadie.")}</div>`
		);
	}

	escanear() {
		this.$camara.empty();
		this.scanner = new frappe.ui.Scanner({
			container: this.$camara,
			multiple: true,
			on_scan: (r) => this.registrar(r.decodedText),
		});
		this.scanner.scan();
		this.escaneando = true;
		this.$boton_camara.text(__("Detener cámara")).removeClass("btn-primary").addClass("btn-default");
	}

	detener() {
		if (this.scanner) this.scanner.stop_scan();
		this.scanner = null;
		this.escaneando = false;
		this.$boton_camara.text(__("Escanear con la cámara")).removeClass("btn-default").addClass("btn-primary");
	}

	async registrar(texto) {
		// La cámara lee el mismo QR varias veces seguidas: se ignora unos segundos.
		const ahora = Date.now();
		if (texto === this.ultimo.texto && ahora - this.ultimo.cuando < 4000) return;
		this.ultimo = { texto, cuando: ahora };
		const r = await frappe.xcall("galeria_arte.api.boletos.registrar_ingreso", {
			codigo: texto,
			evento: this.campo.get_value() || null,
		});
		const esc = frappe.utils.escape_html;
		this.$resultado
			.removeClass("ok no")
			.addClass(r.ok ? "ok" : "no")
			.html(
				r.ok
					? `<div class="ci-resultado-titulo">✓ ${__("Bienvenido(a)")}</div><div class="ci-resultado-sub">${esc(r.asistente)}</div>`
					: `<div class="ci-resultado-titulo">✕ ${__("No puede ingresar")}</div><div class="ci-resultado-sub">${esc(r.motivo)}${
							r.asistente ? `<br>${esc(r.asistente)}` : ""
					  }</div>`
			)
			.show();
		if (navigator.vibrate) navigator.vibrate(r.ok ? 120 : [80, 60, 80]);
		clearTimeout(this.ocultar);
		this.ocultar = setTimeout(() => this.$resultado.fadeOut(300), 5000);
		this.actualizar();
	}
}
