# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Venta de obras de arte: reservaciones (documento propio, con abonos e
historial) y facturación. Separado del POS de cafetería.

Reglas:
- Reservar o vender una obra exige un anticipo.
- El saldo se paga con abonos libres o en cuotas mensuales (3, 6, 9 o 12)
  calculadas sobre lo que queda después del anticipo.
- Una reserva vencida solo se avisa; nunca se libera sola.
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, formatdate, get_first_day, getdate, nowdate


from galeria_arte.api.facturacion import (
	FEL_CERTIFICADA,
	_cargar,
	_prefijo_serie,
	crear_factura,
	get_config,
	opciones_cobro,
	recibir_anticipo,
	resumen_cuotas,
)
from galeria_arte.galeria_arte.doctype.obra_de_arte.obra_de_arte import DISPONIBLE, RESERVADA

ACTIVA = "Activa"
CONVERTIDA = "Convertida en venta"
CANCELADA = "Cancelada"
AREA = "Arte"
ABONOS_LIBRES = "Abonos libres"
DIAS_ABONOS_LIBRES = 30


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _obra(obra: str, permiso: str = "write"):
	doc = frappe.get_doc("Obra de Arte", obra)
	doc.check_permission(permiso)
	return doc


def _reservacion(reservacion: str, permiso: str = "write"):
	doc = frappe.get_doc("Reservacion de Obra", reservacion)
	doc.check_permission(permiso)
	return doc


def _validar_modo_pago(modo_pago: str):
	if modo_pago not in opciones_cobro()["modos_pago"]:
		frappe.throw(_("Forma de pago no válida: {0}").format(modo_pago))


def _recibir_pago(cliente: str, monto: float, modo_pago: str, referencia, obra, reservacion=None) -> str:
	"""Anticipo o abono por una obra; queda a favor del cliente hasta aplicarse."""
	observacion = f"Anticipo por la obra {obra.name} - {obra.titulo}" + (f" (reserva {reservacion})" if reservacion else "")
	return recibir_anticipo(
		cliente, monto, modo_pago, referencia or f"Anticipo {reservacion or obra.name}", observacion,
		galeria_obra=obra.name, galeria_reservacion=reservacion,
	)


def _sin_aplicar(pago: str) -> float:
	pe = frappe.db.get_value("Payment Entry", pago, ["docstatus", "unallocated_amount"], as_dict=True)
	return flt(pe.unallocated_amount) if pe and pe.docstatus == 1 else 0.0


def _sincronizar_obra(res):
	"""La obra muestra quién la tiene reservada, hasta cuándo y cuánto lleva abonado."""
	frappe.db.set_value(
		"Obra de Arte",
		res.obra,
		{
			"estado": RESERVADA,
			"reservacion": res.name,
			"reservada_por": res.cliente,
			"fecha_limite_reserva": res.fecha_limite,
			"anticipo": res.total_abonado,
		},
	)


def _liberar_obra(obra: str):
	frappe.db.set_value(
		"Obra de Arte",
		obra,
		{
			"estado": DISPONIBLE,
			"reservacion": None,
			"reservada_por": None,
			"fecha_limite_reserva": None,
			"anticipo": 0,
		},
	)


# ---------------------------------------------------------------------------
# Reservaciones
# ---------------------------------------------------------------------------


@frappe.whitelist()
def crear_reservacion(
	obra: str,
	cliente: str,
	anticipo: float,
	modo_pago: str,
	fecha_limite: str,
	referencia: str | None = None,
	notas: str | None = None,
) -> dict:
	"""Aparta una obra Disponible con un anticipo del cliente."""
	o = _obra(obra)
	if o.estado != DISPONIBLE:
		frappe.throw(_("Solo se puede reservar una obra Disponible (estado actual: {0}).").format(o.estado))
	anticipo = flt(anticipo)
	if anticipo <= 0:
		frappe.throw(_("La reserva requiere un anticipo mayor a cero."))
	if anticipo > flt(o.precio_venta):
		frappe.throw(_("El anticipo no puede ser mayor que el precio de la obra."))
	if getdate(fecha_limite) < getdate(nowdate()):
		frappe.throw(_("La fecha límite de la reserva no puede ser anterior a hoy."))
	_validar_modo_pago(modo_pago)

	res = frappe.new_doc("Reservacion de Obra")
	res.obra = o.name
	res.cliente = cliente
	res.fecha = nowdate()
	res.fecha_limite = fecha_limite
	res.notas = notas
	res.insert(ignore_permissions=True)

	pago = _recibir_pago(cliente, anticipo, modo_pago, referencia, o, res.name)
	res.append(
		"abonos",
		{"fecha": nowdate(), "modo_pago": modo_pago, "monto": anticipo, "referencia": referencia, "pago": pago},
	)
	res.save()
	_sincronizar_obra(res)
	return {"reservacion": res.name, "pago": pago}


@frappe.whitelist()
def agregar_abono(reservacion: str, monto: float, modo_pago: str, referencia: str | None = None) -> dict:
	"""Otro abono del cliente mientras la obra sigue reservada."""
	res = _reservacion(reservacion)
	if res.estado != ACTIVA:
		frappe.throw(_("La reservación {0} no está activa.").format(res.name))
	monto = flt(monto)
	if monto <= 0:
		frappe.throw(_("El abono debe ser mayor a cero."))
	if flt(res.total_abonado + monto, 2) > flt(res.precio_obra, 2):
		frappe.throw(
			_("Con este abono se pasaría del precio de la obra. Saldo: Q{0}.").format(flt(res.saldo_obra, 2))
		)
	o = _obra(res.obra)
	pago = _recibir_pago(res.cliente, monto, modo_pago, referencia, o, res.name)
	res.append(
		"abonos",
		{"fecha": nowdate(), "modo_pago": modo_pago, "monto": monto, "referencia": referencia, "pago": pago},
	)
	res.save()
	_sincronizar_obra(res)
	return {"reservacion": res.name, "pago": pago, "total_abonado": res.total_abonado, "saldo_obra": res.saldo_obra}


@frappe.whitelist()
def extender_reservacion(reservacion: str, fecha_limite: str) -> dict:
	res = _reservacion(reservacion)
	if res.estado != ACTIVA:
		frappe.throw(_("La reservación {0} no está activa.").format(res.name))
	if getdate(fecha_limite) < getdate(nowdate()):
		frappe.throw(_("La nueva fecha no puede ser anterior a hoy."))
	anterior = res.fecha_limite
	res.fecha_limite = fecha_limite
	res.save()
	res.add_comment(
		"Info", _("Reserva extendida del {0} al {1}.").format(formatdate(anterior), formatdate(fecha_limite))
	)
	_sincronizar_obra(res)
	return {"reservacion": res.name, "fecha_limite": res.fecha_limite}


@frappe.whitelist()
def cancelar_reservacion(reservacion: str, motivo: str | None = None) -> dict:
	"""Libera la obra. Lo abonado queda como saldo a favor del cliente."""
	res = _reservacion(reservacion)
	if res.estado != ACTIVA:
		frappe.throw(_("La reservación {0} no está activa.").format(res.name))
	res.estado = CANCELADA
	res.fecha_cierre = nowdate()
	res.motivo_cancelacion = motivo
	res.save()
	_liberar_obra(res.obra)
	return {"reservacion": res.name, "cliente": res.cliente, "saldo_a_favor": res.total_abonado}


# ---------------------------------------------------------------------------
# Venta
# ---------------------------------------------------------------------------


@frappe.whitelist()
def datos_venta(obra: str) -> dict:
	"""Lo que necesitan los diálogos de reservar y vender."""
	o = _obra(obra, "read")
	reservacion = None
	if o.estado == RESERVADA and o.reservacion:
		res = frappe.get_doc("Reservacion de Obra", o.reservacion)
		reservacion = {
			"name": res.name,
			"cliente": res.cliente,
			"fecha_limite": res.fecha_limite,
			"total_abonado": res.total_abonado,
			"disponible": flt(sum(_sin_aplicar(a.pago) for a in res.abonos), 2),
		}
	opciones = opciones_cobro()
	return {
		"obra": {
			"name": o.name,
			"titulo": o.titulo,
			"artista": o.artista,
			"estado": o.estado,
			"precio_venta": o.precio_venta,
			"monto_artista": o.monto_artista,
		},
		"reservacion": reservacion,
		"modos_pago": opciones["modos_pago"],
		"planes_pago": opciones["planes_pago"],
		"abonos_libres": ABONOS_LIBRES,
		"dias_abonos_libres": DIAS_ABONOS_LIBRES,
	}


@frappe.whitelist()
def vender(
	obra: str,
	cliente: str,
	precio: str | float | None = None,
	monto_artista: str | float | None = None,
	plan_pagos: str | None = None,
	pagos=None,
	pagar_antes_de: str | None = None,
) -> dict:
	"""Factura una obra.

	pagos: [{modo_pago, monto, referencia?}] recibidos hoy (anticipo o pago total).
	plan_pagos: plantilla de cuotas para el saldo; vacío o "Abonos libres" = el
	cliente abona cuando pueda, antes de `pagar_antes_de`.
	"""
	o = _obra(obra)
	if o.estado not in (DISPONIBLE, RESERVADA):
		frappe.throw(_("La obra no se puede vender (estado actual: {0}).").format(o.estado))

	res = None
	if o.estado == RESERVADA:
		if o.reservacion:
			res = frappe.get_doc("Reservacion de Obra", o.reservacion)
		if cliente != o.reservada_por:
			frappe.throw(_("La obra está reservada por {0}.").format(o.reservada_por))

	precio = flt(precio) if precio not in (None, "") else flt(o.precio_venta)
	monto_artista = flt(monto_artista) if monto_artista not in (None, "") else flt(o.monto_artista)
	if precio <= 0:
		frappe.throw(_("El precio de venta debe ser mayor a cero."))
	if monto_artista < 0:
		frappe.throw(_("El monto para el artista no puede ser negativo."))

	# Anticipos de la reserva que aún no se han aplicado a otra factura.
	anticipos = []
	if res:
		for a in res.abonos:
			disponible = _sin_aplicar(a.pago)
			if disponible > 0:
				anticipos.append({"pago": a.pago, "monto": disponible})
	de_reserva = flt(sum(a["monto"] for a in anticipos), 2)

	pagos = [p for p in (_cargar(pagos) or []) if flt(p.get("monto")) > 0]
	for p in pagos:
		_validar_modo_pago(p.get("modo_pago"))
	de_hoy = flt(sum(flt(p["monto"]) for p in pagos), 2)

	recibido = flt(de_reserva + de_hoy, 2)
	if recibido <= 0:
		frappe.throw(_("Para vender la obra se necesita un anticipo: registre el pago de hoy."))
	if recibido > precio:
		frappe.throw(
			_("Lo recibido (Q{0}) es mayor que el precio de la obra (Q{1}).").format(recibido, precio)
		)
	saldo = flt(precio - recibido, 2)

	if plan_pagos in (None, "", ABONOS_LIBRES, "Contado"):
		plan_pagos = None
	elif plan_pagos not in opciones_cobro()["planes_pago"]:
		frappe.throw(_("Plan de pagos no válido: {0}").format(plan_pagos))
	vence = None
	if saldo <= 0:
		plan_pagos = None
	elif not plan_pagos:
		vence = getdate(pagar_antes_de) if pagar_antes_de else getdate(add_days(nowdate(), DIAS_ABONOS_LIBRES))
		if vence < getdate(nowdate()):
			frappe.throw(_("La fecha límite de pago no puede ser anterior a hoy."))

	# Lo recibido hoy entra como anticipo, para que las cuotas se calculen
	# sobre el saldo que queda después.
	for p in pagos:
		pago = _recibir_pago(cliente, flt(p["monto"]), p["modo_pago"], p.get("referencia"), o, res.name if res else None)
		anticipos.append({"pago": pago, "monto": flt(p["monto"])})

	estado = crear_factura(
		items=[{"item_code": o.articulo, "qty": 1, "rate": precio, "galeria_monto_artista": monto_artista}],
		cliente=cliente,
		area=AREA,
		plan_pagos=plan_pagos,
		anticipos=anticipos,
		vence=vence,
	)
	estado["reservacion"] = res.name if res else None
	estado["obra"] = o.name
	return estado


# ---------------------------------------------------------------------------
# Panel de Venta de Obras
# ---------------------------------------------------------------------------


@frappe.whitelist()
def panel() -> dict:
	from galeria_arte.api.eventos import vencer_adjudicaciones

	vencer_adjudicaciones()
	conf = get_config()
	hoy = getdate(nowdate())

	disponibles = frappe.get_all(
		"Obra de Arte",
		filters={"estado": DISPONIBLE},
		fields=["name", "titulo", "artista", "tecnica", "anio", "imagen", "precio_venta", "alto_cm", "ancho_cm"],
		order_by="titulo asc",
		limit_page_length=500,
	)

	reservaciones = frappe.get_all(
		"Reservacion de Obra",
		fields=[
			"name", "obra", "titulo_obra", "artista", "cliente", "estado", "fecha", "fecha_limite",
			"precio_obra", "total_abonado", "saldo_obra", "factura", "fecha_cierre", "motivo_cancelacion",
		],
		order_by="creation desc",
		limit_page_length=300,
	)
	clientes = {
		c.name: c.customer_name
		for c in frappe.get_all(
			"Customer",
			filters={"name": ["in", list({r.cliente for r in reservaciones}) or [""]]},
			fields=["name", "customer_name"],
		)
	}
	orden = {ACTIVA: 0, CONVERTIDA: 1, CANCELADA: 2}
	for r in reservaciones:
		r.cliente_nombre = clientes.get(r.cliente, r.cliente)
		r.vencida = bool(r.estado == ACTIVA and r.fecha_limite and getdate(r.fecha_limite) < hoy)
		r.dias_restantes = date_diff(r.fecha_limite, hoy) if r.estado == ACTIVA and r.fecha_limite else None
	reservaciones.sort(key=lambda r: (orden.get(r.estado, 9), str(r.fecha_limite) if r.estado == ACTIVA else ""))

	base = {
		"company": conf.company,
		"docstatus": 1,
		"is_return": 0,
		"galeria_area": AREA,
		"name": ["like", f"{_prefijo_serie(conf.serie_factura)}%"],
	}
	ventas = frappe.get_all(
		"Sales Invoice",
		filters=base,
		fields=[
			"name", "posting_date", "customer", "customer_name", "grand_total", "outstanding_amount", "status",
			"payment_terms_template", "due_date", "galeria_reservacion", "galeria_evento", "bfel_status", "bfel_uuid",
		],
		order_by="posting_date desc, name desc",
		limit_page_length=300,
	)
	obras_por_factura = {}
	if ventas:
		for ob in frappe.get_all(
			"Obra de Arte",
			filters={"factura": ["in", [v.name for v in ventas]]},
			fields=["name", "titulo", "artista", "factura"],
		):
			obras_por_factura.setdefault(ob.factura, []).append(ob)
	cuotas = resumen_cuotas([v.name for v in ventas if v.payment_terms_template])
	for v in ventas:
		v.cuotas = cuotas.get(v.name)
		v.pagado = flt(v.grand_total - v.outstanding_amount, 2)
		v.obras = obras_por_factura.get(v.name, [])
		v.fel = "Certificada" if v.bfel_status == FEL_CERTIFICADA and v.bfel_uuid else "Pendiente de certificar"

	# Obras ganadas en subasta: por pagar (7 días, al contado), pagadas o vencidas.
	subastas = frappe.db.sql(
		"""
		SELECT l.name AS lote, l.parent AS evento, e.nombre AS subasta, e.inicio, l.obra, l.titulo, l.artista,
			l.precio_inicial, l.precio_ganador, l.comprador, l.comprador_nombre, l.resultado, l.fecha_limite_pago,
			l.factura
		FROM `tabEvento Lote` l
		JOIN `tabEvento` e ON e.name = l.parent AND l.parenttype = 'Evento'
		WHERE l.resultado IN ('Adjudicada', 'Pagada', 'Vencida')
		ORDER BY FIELD(l.resultado, 'Adjudicada', 'Vencida', 'Pagada'), l.fecha_limite_pago ASC, e.inicio DESC
		LIMIT 300
		""",
		as_dict=True,
	)
	for sub in subastas:
		sub.dias_restantes = date_diff(sub.fecha_limite_pago, hoy) if sub.resultado == "Adjudicada" else None
	por_pagar = [sub for sub in subastas if sub.resultado == "Adjudicada"]

	activas = [r for r in reservaciones if r.estado == ACTIVA]
	mes = get_first_day(hoy)
	return {
		"obras": disponibles,
		"reservaciones": reservaciones,
		"ventas": ventas,
		"subastas": subastas,
		"totales": {
			"vendido_mes": flt(sum(v.grand_total for v in ventas if getdate(v.posting_date) >= mes), 2),
			"ventas_mes": len([v for v in ventas if getdate(v.posting_date) >= mes]),
			"reservas_activas": len(activas),
			"anticipos_reservas": flt(sum(flt(r.total_abonado) for r in activas), 2),
			"reservas_vencidas": len([r for r in activas if r.vencida]),
			"por_cobrar": flt(sum(flt(v.outstanding_amount) for v in ventas), 2),
			"subastas_por_pagar": len(por_pagar),
			"subastas_por_vencer": len([sub for sub in por_pagar if sub.dias_restantes <= 2]),
		},
	}
