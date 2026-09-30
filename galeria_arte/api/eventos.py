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
	ALQUILER,
	CENA,
	EXPOSICION,
	INACTIVOS,
	SUBASTA,
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
def vender_boletos(evento: str, cantidad: int, pagos, cliente: str | None = None) -> dict:
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
	ev.reload()
	ev.append(
		"asistentes",
		{
			"cliente": frappe.db.get_value("Sales Invoice", estado["factura"], "customer"),
			"nombre": estado["cliente"],
			"lugares": cantidad,
			"factura": estado["factura"],
			"fecha": nowdate(),
		},
	)
	ev.save()
	estado.update({"evento": ev.name, "lugares_vendidos": ev.lugares_vendidos, "cupo": ev.cupo})
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
		ev.set("asistentes", [a for a in ev.asistentes if a.factura != doc.name])
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
			}
		)
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
