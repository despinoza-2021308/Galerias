# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Eventos de la galería y calendario de salas.

- Exposición, Cena y Subasta los organiza la galería (Planificado → Publicado
  → Realizado / Cancelado). Todos los eventos ocupan su sala, también las
  exposiciones mientras duran.
- Los boletos de cena se pagan al reservar y descuentan el cupo.
- Alquiler (lo pide un cliente): Tentativo (vence si no deja anticipo) →
  Confirmado con anticipo → abonos hasta completar → Liquidado (factura pagada)
  → Realizado. El saldo se paga antes del evento.
- Subasta: se agregan las obras con su precio inicial (quedan En subasta).
  Al terminar se registra el precio ganador y el comprador; el comprador paga
  al contado en 7 días y en ese momento se emite la factura. Si no paga, la
  obra vuelve a estar disponible.
"""

import frappe
from frappe import _
from datetime import datetime

from frappe.utils import add_days, cint, flt, formatdate, get_datetime, getdate, now_datetime, nowdate

from galeria_arte.api.facturacion import (
	_cargar,
	crear_factura,
	get_config,
	opciones_cobro,
	pago_sin_aplicar,
	recibir_anticipo,
)
from galeria_arte.galeria_arte.doctype.evento.evento import (
	ADJUDICADA,
	ALQUILER,
	CENA,
	DIAS_PAGO_SUBASTA,
	EXPOSICION,
	INACTIVOS,
	PAGADA,
	PENDIENTE,
	SUBASTA,
	VENCIDA,
)

AREA = "Eventos"
GRUPO_ALQUILER = "Alquiler de Espacio"
ARTICULO_ALQUILER = "ALQ-ESPACIO"
ARTICULO_CARGO = "ALQ-CARGO"
UOM = "Unidad(es)"

COLORES = {EXPOSICION: "#7C3AED", CENA: "#EA580C", SUBASTA: "#0891B2", ALQUILER: "#2563EB"}


def _evento(evento: str, permiso: str = "write"):
	doc = frappe.get_doc("Evento", evento)
	doc.check_permission(permiso)
	return doc


# ---------------------------------------------------------------------------
# Estados de los eventos de la galería
# ---------------------------------------------------------------------------


@frappe.whitelist()
def publicar(evento: str) -> dict:
	ev = _evento(evento)
	if ev.tipo == ALQUILER or ev.estado != "Planificado":
		frappe.throw(_("Solo se publica un evento de la galería que está Planificado."))
	ev.estado = "Publicado"
	ev.save()
	return {"evento": ev.name, "estado": ev.estado}


@frappe.whitelist()
def marcar_realizado(evento: str) -> dict:
	ev = _evento(evento)
	if ev.tipo == ALQUILER and ev.estado != "Liquidado":
		frappe.throw(_("El alquiler debe estar liquidado (saldo pagado) antes de marcarlo como realizado."))
	if ev.tipo != ALQUILER and ev.estado not in ("Planificado", "Publicado"):
		frappe.throw(_("El evento no se puede marcar como realizado (estado: {0}).").format(ev.estado))
	if ev.tipo == SUBASTA and not ev.lotes:
		frappe.throw(_("Agregue al menos una obra a la subasta."))
	ev.estado = "Realizado"
	ev.save()
	return {"evento": ev.name, "estado": ev.estado}


@frappe.whitelist()
def cancelar(evento: str, motivo: str | None = None) -> dict:
	ev = _evento(evento)
	if ev.estado in ("Cancelado", "Vencido", "Realizado"):
		frappe.throw(_("El evento ya está {0}.").format(ev.estado.lower()))
	if ev.factura and frappe.db.get_value("Sales Invoice", ev.factura, "docstatus") == 1:
		frappe.throw(_("El alquiler ya se facturó en {0}; anule primero esa factura.").format(ev.factura))
	ev.estado = "Cancelado"
	ev.motivo_cancelacion = motivo
	ev.save()
	if ev.tipo == CENA:
		from galeria_arte.api.boletos import anular_boletos

		anular_boletos({"evento": ev.name})
	return {
		"evento": ev.name,
		"estado": ev.estado,
		"boletos_vendidos": ev.lugares_vendidos if ev.tipo == CENA else 0,
		"saldo_a_favor": ev.total_abonado if ev.tipo == ALQUILER else 0,
		"cliente": ev.cliente,
	}


# ---------------------------------------------------------------------------
# Boletos de cena (se pagan al reservar)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def vender_boletos(
	evento: str,
	cantidad: int,
	pagos,
	cliente: str | None = None,
	asistentes=None,
	correo: str | None = None,
	whatsapp: str | None = None,
) -> dict:
	"""asistentes: [{nombre, correo?, whatsapp?}], uno por lugar (cada uno recibe su boleto con QR).
	correo / whatsapp: del comprador, recibe todos los boletos."""
	from galeria_arte.api.boletos import crear_boletos, enviar_correos, hay_cuenta_de_correo
	from galeria_arte.galeria_arte.doctype.boleto.boleto import normalizar_whatsapp

	ev = _evento(evento)
	if ev.tipo != CENA:
		frappe.throw(_("Solo las cenas venden boletos."))
	if ev.estado != "Publicado":
		frappe.throw(_("Publique la cena para vender boletos (estado: {0}).").format(ev.estado))
	if get_datetime(ev.fin) < now_datetime():
		frappe.throw(_("La cena ya pasó."))
	cantidad = cint(cantidad)
	if cantidad <= 0:
		frappe.throw(_("Indique cuántos lugares."))
	disponibles = cint(ev.cupo) - cint(ev.lugares_vendidos)
	if cantidad > disponibles:
		frappe.throw(_("Solo quedan {0} lugares.").format(disponibles))

	asistentes = [
		{
			"nombre": (a.get("nombre") or "").strip(),
			"correo": (a.get("correo") or "").strip() or None,
			"whatsapp": (a.get("whatsapp") or "").strip() or None,
		}
		for a in (_cargar(asistentes) or [])
	]
	if asistentes and len(asistentes) != cantidad:
		frappe.throw(_("Indique el nombre de cada asistente ({0} lugares).").format(cantidad))
	if any(not a["nombre"] for a in asistentes):
		frappe.throw(_("Cada boleto lleva el nombre del asistente: complete todos los nombres."))
	for a in asistentes + [{"correo": correo}]:
		if a.get("correo"):
			frappe.utils.validate_email_address(a["correo"], throw=True)

	total = flt(cantidad * flt(ev.precio_boleto), 2)
	pagos = [p for p in (_cargar(pagos) or []) if flt(p.get("monto")) > 0]
	pagado = flt(sum(flt(p["monto"]) for p in pagos), 2)
	if abs(pagado - total) > 0.005:
		frappe.throw(_("Los boletos se pagan al reservar: los pagos (Q{0}) deben sumar Q{1}.").format(pagado, total))

	estado = crear_factura(
		items=[{"item_code": ev.articulo_boleto, "qty": cantidad, "rate": ev.precio_boleto}],
		cliente=cliente,
		area=AREA,
		pagos=pagos,
		campos={"galeria_evento": ev.name},
	)
	comprador = frappe.db.get_value("Sales Invoice", estado["factura"], "customer")
	ev.reload()
	ev.append(
		"asistentes",
		{
			"cliente": comprador,
			"nombre": estado["cliente"],
			"lugares": cantidad,
			"factura": estado["factura"],
			"fecha": nowdate(),
		},
	)
	ev.save()
	# Sin nombres (ventas antiguas o rápidas), cada boleto lleva el del comprador.
	asistentes = asistentes or [{"nombre": estado["cliente"], "correo": None} for _i in range(cantidad)]
	boletos = crear_boletos(ev, estado["factura"], comprador, asistentes)
	correos = []
	if correo or any(a.get("correo") for a in asistentes):
		try:
			correos = enviar_correos(boletos, correo)
		except Exception:
			# La venta ya está hecha: un problema con el correo no la deshace.
			frappe.log_error(title="Boletos: no se pudo preparar el correo")
	estado.update(
		{
			"evento": ev.name,
			"lugares_vendidos": ev.lugares_vendidos,
			"cupo": ev.cupo,
			"boletos": boletos,
			"correos": correos,
			"hay_cuenta_de_correo": hay_cuenta_de_correo(),
			"whatsapp_comprador": normalizar_whatsapp(whatsapp),
		}
	)
	return estado


# ---------------------------------------------------------------------------
# Alquiler del espacio
# ---------------------------------------------------------------------------


@frappe.whitelist()
def confirmar_alquiler(evento: str, anticipo: float, modo_pago: str, referencia: str | None = None) -> dict:
	ev = _evento(evento)
	if ev.tipo != ALQUILER or ev.estado != "Tentativo":
		frappe.throw(_("Solo se confirma un alquiler Tentativo."))
	anticipo = flt(anticipo)
	if anticipo <= 0:
		frappe.throw(_("Para confirmar el alquiler se necesita un anticipo."))
	if anticipo > flt(ev.total_alquiler):
		frappe.throw(_("El anticipo no puede ser mayor que el total del alquiler."))
	_abonar(ev, anticipo, modo_pago, referencia, "Anticipo")
	ev.estado = "Confirmado"
	ev.vence_tentativa = None
	ev.save()
	return _liquidar_si_corresponde(ev)


@frappe.whitelist()
def abonar_alquiler(evento: str, monto: float, modo_pago: str, referencia: str | None = None) -> dict:
	ev = _evento(evento)
	if ev.tipo != ALQUILER or ev.estado != "Confirmado":
		frappe.throw(_("Solo se abona a un alquiler Confirmado."))
	monto = flt(monto)
	if monto <= 0:
		frappe.throw(_("El abono debe ser mayor a cero."))
	if monto > flt(ev.saldo) + 0.005:
		frappe.throw(_("El abono supera el saldo del alquiler (Q{0}).").format(flt(ev.saldo, 2)))
	_abonar(ev, monto, modo_pago, referencia, "Abono")
	ev.save()
	return _liquidar_si_corresponde(ev)


def _abonar(ev, monto: float, modo_pago: str, referencia: str | None, tipo: str):
	pago = recibir_anticipo(
		ev.cliente, monto, modo_pago, referencia or f"{tipo} {ev.name}",
		f"{tipo} por el alquiler {ev.name} - {ev.nombre}", galeria_evento=ev.name,
	)
	ev.append(
		"abonos",
		{"fecha": nowdate(), "modo_pago": modo_pago, "monto": monto, "referencia": referencia, "pago": pago},
	)


def _liquidar_si_corresponde(ev) -> dict:
	"""Con el saldo en cero se emite la factura (ya pagada con los abonos)."""
	resultado = {"evento": ev.name, "estado": ev.estado, "total_abonado": ev.total_abonado, "saldo": ev.saldo}
	if flt(ev.saldo) > 0.005 or ev.factura:
		return resultado
	asegurar_articulos_alquiler()
	lugar = _("todo el espacio") if ev.todo_el_espacio else ev.sala
	items = [
		{
			"item_code": ARTICULO_ALQUILER,
			"qty": 1,
			"rate": ev.precio_alquiler,
			"item_name": f"Alquiler de {lugar}"[:140],
			"description": f"Alquiler de {lugar} para {ev.nombre} ({get_datetime(ev.inicio).strftime('%d-%m-%Y %H:%M')})",
		}
	]
	for c in ev.cargos:
		items.append({"item_code": ARTICULO_CARGO, "qty": 1, "rate": c.monto, "item_name": c.descripcion[:140], "description": c.descripcion})
	anticipos = [{"pago": a.pago, "monto": pago_sin_aplicar(a.pago)} for a in ev.abonos]
	estado = crear_factura(
		items=items,
		cliente=ev.cliente,
		area=AREA,
		anticipos=[a for a in anticipos if a["monto"] > 0],
		campos={"galeria_evento": ev.name},
	)
	ev.reload()
	ev.factura = estado["factura"]
	ev.estado = "Liquidado"
	ev.save()
	resultado.update({"estado": ev.estado, "factura": ev.factura, "saldo": 0})
	return resultado


def asegurar_articulos_alquiler():
	for codigo, nombre in ((ARTICULO_ALQUILER, "Alquiler de espacio"), (ARTICULO_CARGO, "Servicio adicional de evento")):
		if not frappe.db.exists("Item", codigo):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": codigo,
					"item_name": nombre,
					"description": nombre,
					"item_group": GRUPO_ALQUILER,
					"stock_uom": UOM,
					"is_stock_item": 0,
					"is_sales_item": 1,
					"is_purchase_item": 0,
					"include_item_in_manufacturing": 0,
				}
			).insert(ignore_permissions=True)


def vencer_tentativas():
	"""Tarea diaria (y al abrir el calendario): alquileres tentativos sin anticipo
	cuya fecha de apartado pasó quedan Vencidos y liberan la sala."""
	for nombre in frappe.get_all(
		"Evento",
		filters={"tipo": ALQUILER, "estado": "Tentativo", "vence_tentativa": ["<", nowdate()]},
		pluck="name",
	):
		ev = frappe.get_doc("Evento", nombre)
		ev.estado = "Vencido"
		ev.motivo_cancelacion = _("Venció sin anticipo el {0}.").format(formatdate(ev.vence_tentativa))
		ev.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Subastas
# ---------------------------------------------------------------------------


def _lote(ev, lote: str):
	fila = next((l for l in ev.lotes if l.name == lote), None)
	if not fila:
		frappe.throw(_("La obra no pertenece a esta subasta."))
	return fila


def _subasta(evento: str, permiso: str = "write"):
	ev = _evento(evento, permiso)
	if ev.tipo != SUBASTA:
		frappe.throw(_("El evento {0} no es una subasta.").format(ev.name))
	return ev


@frappe.whitelist()
def agregar_lote(evento: str, obra: str, precio_inicial: str | float | None = None) -> dict:
	ev = _subasta(evento)
	ev.append("lotes", {"obra": obra, "precio_inicial": flt(precio_inicial) or None})
	ev.save()
	return {"evento": ev.name, "obras": len(ev.lotes)}


@frappe.whitelist()
def quitar_lote(evento: str, lote: str) -> dict:
	ev = _subasta(evento)
	fila = _lote(ev, lote)
	ev.remove(fila)
	ev.save()
	return {"evento": ev.name, "obras": len(ev.lotes)}


@frappe.whitelist()
def registrar_resultado(
	evento: str,
	lote: str,
	vendida: int = 1,
	precio_ganador: str | float | None = None,
	comprador: str | None = None,
) -> dict:
	"""Resultado de una obra al terminar la subasta: precio ganador y comprador,
	o que no se vendió."""
	ev = _subasta(evento)
	if ev.estado != "Realizado":
		frappe.throw(_("Marque la subasta como realizada para registrar los resultados."))
	fila = _lote(ev, lote)
	if cint(vendida):
		fila.update({"sin_venta": 0, "precio_ganador": flt(precio_ganador), "comprador": comprador})
	else:
		fila.update({"sin_venta": 1, "precio_ganador": 0, "comprador": None})
	ev.save()
	fila = _lote(ev, lote)
	return {"evento": ev.name, "resultado": fila.resultado, "fecha_limite_pago": fila.fecha_limite_pago}


@frappe.whitelist()
def datos_cobro_subasta(evento: str, lote: str) -> dict:
	ev = _subasta(evento, "read")
	fila = _lote(ev, lote)
	obra = frappe.db.get_value("Obra de Arte", fila.obra, ["titulo", "artista", "monto_artista"], as_dict=True)
	return {
		"evento": ev.name,
		"subasta": ev.nombre,
		"lote": fila.name,
		"obra": fila.obra,
		"titulo": obra.titulo,
		"artista": obra.artista,
		"monto_artista": obra.monto_artista,
		"precio_inicial": fila.precio_inicial,
		"precio_ganador": fila.precio_ganador,
		"comprador": fila.comprador,
		"comprador_nombre": fila.comprador_nombre,
		"resultado": fila.resultado,
		"fecha_limite_pago": fila.fecha_limite_pago,
		"dias_restantes": (getdate(fila.fecha_limite_pago) - getdate(nowdate())).days if fila.fecha_limite_pago else None,
		"modos_pago": opciones_cobro()["modos_pago"],
	}


@frappe.whitelist()
def cobrar_subasta(evento: str, lote: str, pagos, monto_artista: str | float | None = None) -> dict:
	"""El comprador paga el precio ganador completo, al contado; en ese momento
	se emite la factura (ya pagada) y la obra queda vendida."""
	ev = _subasta(evento)
	fila = _lote(ev, lote)
	if fila.resultado != ADJUDICADA:
		frappe.throw(_("La obra no está pendiente de pago (estado: {0}).").format(fila.resultado))
	if getdate(fila.fecha_limite_pago) < getdate(nowdate()):
		frappe.throw(
			_("El plazo para pagar venció el {0}; la adjudicación ya no es válida.").format(
				formatdate(fila.fecha_limite_pago)
			)
		)
	total = flt(fila.precio_ganador, 2)
	pagos = [p for p in (_cargar(pagos) or []) if flt(p.get("monto")) > 0]
	modos = opciones_cobro()["modos_pago"]
	for p in pagos:
		if p.get("modo_pago") not in modos:
			frappe.throw(_("Forma de pago no válida: {0}").format(p.get("modo_pago")))
	pagado = flt(sum(flt(p["monto"]) for p in pagos), 2)
	if abs(pagado - total) > 0.005:
		frappe.throw(
			_("La obra de subasta se paga al contado: los pagos (Q{0}) deben sumar el precio ganador (Q{1}).").format(
				pagado, total
			)
		)
	obra = frappe.get_doc("Obra de Arte", fila.obra)
	monto_artista = flt(monto_artista) if monto_artista not in (None, "") else flt(obra.monto_artista)
	if monto_artista < 0:
		frappe.throw(_("El monto para el artista no puede ser negativo."))

	estado = crear_factura(
		items=[{"item_code": obra.articulo, "qty": 1, "rate": total, "galeria_monto_artista": monto_artista}],
		cliente=fila.comprador,
		area="Arte",
		pagos=pagos,
		observaciones=f"Venta en subasta {ev.name} - {ev.nombre}",
		campos={"galeria_evento": ev.name},
	)
	ev.reload()
	fila = _lote(ev, lote)
	fila.resultado = PAGADA
	fila.factura = estado["factura"]
	ev.flags.galeria_resultado_sistema = True
	ev.save()
	estado.update({"evento": ev.name, "obra": obra.name})
	return estado


def vencer_adjudicaciones():
	"""Tarea diaria (y al abrir el calendario o Venta de Obras): si el comprador
	no pagó en el plazo, la adjudicación vence y la obra vuelve al catálogo."""
	hoy = nowdate()
	for nombre in frappe.get_all(
		"Evento Lote",
		filters={"parenttype": "Evento", "resultado": ADJUDICADA, "fecha_limite_pago": ["<", hoy]},
		pluck="parent",
		distinct=True,
	):
		ev = frappe.get_doc("Evento", nombre)
		for l in ev.lotes:
			if l.resultado == ADJUDICADA and l.fecha_limite_pago and str(l.fecha_limite_pago) < hoy:
				l.resultado = VENCIDA
				ev.add_comment(
					"Info",
					_("{0} no pagó {1} antes del {2}; la obra vuelve a estar disponible.").format(
						l.comprador_nombre or l.comprador, l.titulo or l.obra, formatdate(l.fecha_limite_pago)
					),
				)
		ev.flags.galeria_resultado_sistema = True
		ev.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Factura anulada
# ---------------------------------------------------------------------------


def al_anular_factura(doc, method=None):
	"""Sales Invoice on_cancel: si era de un evento, deshace su efecto."""
	if not doc.get("galeria_evento") or not frappe.db.exists("Evento", doc.galeria_evento):
		return
	ev = frappe.get_doc("Evento", doc.galeria_evento)
	if ev.tipo == ALQUILER and ev.factura == doc.name:
		ev.factura = None
		if ev.estado in ("Liquidado", "Realizado"):
			ev.estado = "Confirmado"
	elif ev.tipo == CENA:
		from galeria_arte.api.boletos import anular_boletos

		ev.set("asistentes", [a for a in ev.asistentes if a.factura != doc.name])
		anular_boletos({"factura": doc.name})
	elif ev.tipo == SUBASTA:
		# La obra vuelve a quedar adjudicada al comprador, con el mismo plazo.
		for l in ev.lotes:
			if l.factura == doc.name:
				l.resultado = ADJUDICADA
				l.factura = None
		ev.flags.galeria_resultado_sistema = True
	else:
		return
	ev.flags.ignore_permissions = True
	ev.save()


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------


@frappe.whitelist()
def calendario(
	start: str,
	end: str,
	sala: str | None = None,
	tipo: str | None = None,
	ver_inactivos: int = 0,
) -> list:
	"""Eventos del rango visible para el calendario."""
	frappe.has_permission("Evento", "read", throw=True)
	vencer_tentativas()
	vencer_adjudicaciones()
	filtros = [["inicio", "<", end], ["fin", ">", start]]
	if tipo:
		filtros.append(["tipo", "=", tipo])
	if not cint(ver_inactivos):
		filtros.append(["estado", "not in", INACTIVOS])
	eventos = frappe.get_all(
		"Evento",
		filters=filtros,
		fields=[
			"name", "nombre", "tipo", "estado", "inicio", "fin", "sala", "todo_el_espacio", "cupo",
			"lugares_vendidos", "cliente", "total_alquiler", "saldo", "vence_tentativa",
		],
		order_by="inicio asc",
		limit_page_length=1000,
	)
	colores_sala = {s.name: s.color for s in frappe.get_all("Sala", fields=["name", "color"])}
	subastas = [e.name for e in eventos if e.tipo == SUBASTA]
	obras_subasta = {
		f.parent: f.cantidad
		for f in (
			frappe.get_all(
				"Evento Lote",
				filters={"parenttype": "Evento", "parent": ["in", subastas]},
				fields=["parent", "count(name) as cantidad"],
				group_by="parent",
			)
			if subastas
			else []
		)
	}
	hoy = getdate(nowdate())
	salida = []
	for e in eventos:
		# Filtrar por sala: los eventos de todo el espacio aparecen en todas.
		if sala and not e.todo_el_espacio and e.sala != sala:
			continue
		lugar = _("Todo el espacio") if e.todo_el_espacio else (e.sala or "")
		detalle = ""
		if e.tipo == CENA:
			detalle = f" · {cint(e.lugares_vendidos)}/{cint(e.cupo)}"
		elif e.tipo == ALQUILER and e.cliente:
			detalle = f" · {e.cliente}"
		elif e.tipo == SUBASTA:
			n = obras_subasta.get(e.name, 0)
			detalle = f" · {n} {_('obra') if n == 1 else _('obras')}"
		clases = [f"gal-ev-{frappe.scrub(e.tipo)}"]
		if e.estado == "Tentativo":
			clases.append("gal-ev-tentativo")
		if e.estado in INACTIVOS:
			clases.append("gal-ev-inactivo")
		saldo_pendiente = bool(
			e.tipo == ALQUILER and e.estado == "Confirmado" and flt(e.saldo) > 0 and (getdate(e.inicio) - hoy).days <= 3
		)
		if saldo_pendiente:
			clases.append("gal-ev-alerta")
		# Las exposiciones duran días o semanas: van en la franja de día completo.
		todo_el_dia = e.tipo == EXPOSICION
		salida.append(
			{
				"id": e.name,
				"title": f"{e.nombre}{detalle}",
				"allDay": todo_el_dia,
				"start": str(getdate(e.inicio)) if todo_el_dia else str(e.inicio),
				"end": str(add_days(getdate(e.fin), 1)) if todo_el_dia else str(e.fin),
				"color": COLORES.get(e.tipo, "#6B7280"),
				"textColor": "#FFFFFF",
				"className": clases,
				"editable": e.estado not in INACTIVOS + ("Realizado",) and not (e.tipo == CENA and cint(e.lugares_vendidos)),
				"lugar": lugar,
				"color_sala": colores_sala.get(e.sala) if e.sala else None,
				"tipo": e.tipo,
				"estado": e.estado,
				"saldo_pendiente": saldo_pendiente,
			}
		)
	return salida


@frappe.whitelist()
def mover(evento: str, inicio: str, fin: str, todo_el_dia: int = 0) -> dict:
	"""Arrastrar en el calendario: cambia fecha y hora revisando choques de sala.
	Con todo_el_dia llegan solo fechas (fin exclusivo): se conservan las horas."""
	ev = _evento(evento)
	if cint(todo_el_dia):
		hora_inicio = get_datetime(ev.inicio).time()
		hora_fin = get_datetime(ev.fin).time()
		inicio = datetime.combine(getdate(inicio), hora_inicio)
		fin = datetime.combine(getdate(add_days(getdate(fin), -1)), hora_fin)
	if ev.estado in INACTIVOS + ("Realizado",):
		frappe.throw(_("No se puede mover un evento {0}.").format(ev.estado.lower()))
	if ev.tipo == CENA and cint(ev.lugares_vendidos):
		frappe.throw(_("La cena ya tiene boletos vendidos; cambie la fecha desde su ficha si es necesario."))
	ev.inicio = inicio
	ev.fin = fin
	ev.save()
	return {"evento": ev.name, "inicio": ev.inicio, "fin": ev.fin}


@frappe.whitelist()
def crear(datos) -> dict:
	"""Creación rápida desde el calendario."""
	datos = _cargar(datos) or {}
	ev = frappe.new_doc("Evento")
	for campo in (
		"nombre", "tipo", "inicio", "fin", "sala", "todo_el_espacio", "cupo", "precio_boleto",
		"cliente", "precio_alquiler", "descripcion",
	):
		if datos.get(campo) not in (None, ""):
			ev.set(campo, datos[campo])
	ev.insert()
	return {"evento": ev.name, "estado": ev.estado}


@frappe.whitelist()
def datos_formulario() -> dict:
	"""Salas con su precio de alquiler y opciones de cobro para los diálogos."""
	salas = frappe.get_all(
		"Sala", filters={"activa": 1}, fields=["name", "capacidad", "precio_alquiler", "color"], order_by="name asc"
	)
	opciones = opciones_cobro()
	return {
		"salas": salas,
		"precio_todo": flt(frappe.db.get_single_value("Configuracion Galeria", "precio_alquiler_todo")),
		"modos_pago": opciones["modos_pago"],
		"cliente_defecto": get_config().cliente_consumidor_final,
	}


@frappe.whitelist()
def resumen(evento: str) -> dict:
	"""Detalle de un evento para el calendario y su ficha."""
	ev = _evento(evento, "read")
	datos = {
		"name": ev.name,
		"nombre": ev.nombre,
		"tipo": ev.tipo,
		"estado": ev.estado,
		"inicio": ev.inicio,
		"fin": ev.fin,
		"lugar": _("Todo el espacio") if ev.todo_el_espacio else ev.sala,
		"responsable": ev.responsable,
		"descripcion": ev.descripcion,
	}
	if ev.tipo == CENA:
		ingresos = flt(
			sum(
				flt(frappe.db.get_value("Sales Invoice", a.factura, "grand_total"))
				for a in ev.asistentes
				if a.factura and frappe.db.get_value("Sales Invoice", a.factura, "docstatus") == 1
			),
			2,
		)
		datos.update(
			{
				"cupo": cint(ev.cupo),
				"vendidos": cint(ev.lugares_vendidos),
				"disponibles": cint(ev.cupo) - cint(ev.lugares_vendidos),
				"precio_boleto": ev.precio_boleto,
				"ingresos": ingresos,
				"asistentes": [{"nombre": a.nombre, "lugares": a.lugares, "factura": a.factura} for a in ev.asistentes],
				"boletos": frappe.get_all(
					"Boleto",
					filters={"evento": ev.name},
					fields=[
						"name", "asistente", "estado", "factura", "correo", "correo_enviado", "codigo", "ingreso",
						"whatsapp", "whatsapp_enviado",
					],
					order_by="creation asc",
				),
			}
		)
		datos["llegaron"] = len([b for b in datos["boletos"] if b.estado == "Usado"])
	elif ev.tipo == ALQUILER:
		datos.update(
			{
				"cliente": ev.cliente,
				"cliente_nombre": frappe.db.get_value("Customer", ev.cliente, "customer_name") if ev.cliente else None,
				"precio_alquiler": ev.precio_alquiler,
				"cargos": [{"descripcion": c.descripcion, "monto": c.monto} for c in ev.cargos],
				"total": ev.total_alquiler,
				"abonado": ev.total_abonado,
				"saldo": ev.saldo,
				"vence_tentativa": ev.vence_tentativa,
				"factura": ev.factura,
				"dias_para_evento": (getdate(ev.inicio) - getdate(nowdate())).days,
			}
		)
	elif ev.tipo == SUBASTA:
		hoy = getdate(nowdate())
		imagenes = {
			o.name: o
			for o in frappe.get_all(
				"Obra de Arte",
				filters={"name": ["in", [l.obra for l in ev.lotes] or [""]]},
				fields=["name", "imagen", "monto_artista", "precio_venta"],
			)
		}
		lotes = []
		for l in ev.lotes:
			o = imagenes.get(l.obra) or frappe._dict()
			lotes.append(
				{
					"lote": l.name,
					"obra": l.obra,
					"titulo": l.titulo,
					"artista": l.artista,
					"imagen": o.imagen,
					"precio_obra": o.precio_venta,
					"precio_inicial": l.precio_inicial,
					"precio_ganador": l.precio_ganador,
					"comprador": l.comprador,
					"comprador_nombre": l.comprador_nombre,
					"resultado": l.resultado,
					"fecha_limite_pago": l.fecha_limite_pago,
					"dias_restantes": (getdate(l.fecha_limite_pago) - hoy).days if l.resultado == ADJUDICADA else None,
					"factura": l.factura,
				}
			)
		vendidas = [l for l in ev.lotes if l.resultado in (ADJUDICADA, PAGADA)]
		datos.update(
			{
				"lotes": lotes,
				"dias_pago": DIAS_PAGO_SUBASTA,
				"ofrecidas": len(ev.lotes),
				"vendidas": len(vendidas),
				"pendientes": len([l for l in ev.lotes if l.resultado == PENDIENTE]),
				"total_ganador": flt(sum(flt(l.precio_ganador) for l in vendidas), 2),
				"cobrado": flt(sum(flt(l.precio_ganador) for l in ev.lotes if l.resultado == PAGADA), 2),
				"por_cobrar": flt(sum(flt(l.precio_ganador) for l in ev.lotes if l.resultado == ADJUDICADA), 2),
			}
		)
	elif ev.tipo == EXPOSICION:
		obras = [o.obra for o in ev.obras]
		vendidas = (
			frappe.get_all(
				"Obra de Arte",
				filters={
					"name": ["in", obras],
					"estado": "Vendida",
					"fecha_venta": ["between", [getdate(ev.inicio), getdate(ev.fin)]],
				},
				fields=["name", "titulo", "artista", "precio_vendido"],
			)
			if obras
			else []
		)
		datos.update(
			{
				"obras": [{"obra": o.obra, "titulo": o.titulo, "artista": o.artista} for o in ev.obras],
				"vendidas": vendidas,
				"monto_vendido": flt(sum(flt(v.precio_vendido) for v in vendidas), 2),
			}
		)
	return datos
