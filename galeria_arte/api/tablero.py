# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Dashboard de la galería: todo lo del período en una sola llamada.

Montos con IVA (como se cobran), salvo la ganancia estimada, que va sin IVA:
- Arte: precio sin IVA menos el monto para el artista (exacta).
- Cafetería y eventos: venta sin IVA (no se registra el costo de los productos).
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, get_first_day, getdate, nowdate

from galeria_arte.api.facturacion import _prefijo_serie, get_config

AREAS = ("Arte", "Eventos", "Cafetería")
GRUPO_CAFETERIA = "Cafetería"
DIAS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


@frappe.whitelist()
def datos(desde: str | None = None, hasta: str | None = None) -> dict:
	frappe.has_permission("Sales Invoice", "read", throw=True)
	hoy = getdate(nowdate())
	desde = getdate(desde) if desde else get_first_day(hoy)
	hasta = getdate(hasta) if hasta else hoy
	if hasta < desde:
		frappe.throw(_("La fecha final no puede ser anterior a la inicial."))
	dias = date_diff(hasta, desde) + 1
	# Período anterior de la misma duración, para comparar.
	ant_hasta = add_days(desde, -1)
	ant_desde = add_days(ant_hasta, -(dias - 1))

	conf = get_config()
	c = frappe._dict(
		company=conf.company,
		serie=f"{_prefijo_serie(conf.serie_factura)}%",
		desde=desde,
		hasta=hasta,
		hoy=hoy,
		consumidor=conf.cliente_consumidor_final or "",
	)
	facturas = _facturas(c, desde, hasta)
	anteriores = _facturas(c, ant_desde, ant_hasta)
	items = _items(c)

	return {
		"desde": desde,
		"hasta": hasta,
		"anterior": {"desde": ant_desde, "hasta": ant_hasta},
		"resumen": _resumen(c, facturas, anteriores, items),
		"areas": _areas(facturas, desde, hasta),
		"productos": _productos(c, facturas, items),
		"arte": _arte(c, items),
		"eventos": _eventos(c, facturas),
		"cobros": _cobros(c),
		"clientes": _clientes(c, facturas),
	}


# ---------------------------------------------------------------------------
# Consultas base
# ---------------------------------------------------------------------------


def _facturas(c, desde, hasta) -> list:
	return frappe.db.sql(
		"""
		SELECT name, posting_date, posting_time, customer, customer_name, galeria_area, grand_total, net_total,
			outstanding_amount, selling_price_list, galeria_reservacion, galeria_evento
		FROM `tabSales Invoice`
		WHERE company = %(company)s AND docstatus = 1 AND is_return = 0 AND name LIKE %(serie)s
			AND posting_date BETWEEN %(desde)s AND %(hasta)s
		""",
		dict(c, desde=desde, hasta=hasta),
		as_dict=True,
	)


def _items(c) -> list:
	"""Renglones de las facturas del período con su grupo de artículo."""
	return frappe.db.sql(
		"""
		SELECT sii.parent, sii.item_code, sii.item_name, sii.item_group, sii.qty, sii.amount, sii.net_amount,
			sii.galeria_obra, sii.galeria_monto_artista, si.galeria_area, si.posting_date,
			si.galeria_reservacion, si.galeria_evento
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.company = %(company)s AND si.docstatus = 1 AND si.is_return = 0 AND si.name LIKE %(serie)s
			AND si.posting_date BETWEEN %(desde)s AND %(hasta)s
		""",
		c,
		as_dict=True,
	)


def _suma(filas, campo) -> float:
	return flt(sum(flt(f.get(campo)) for f in filas), 2)


def _cambio(actual, anterior):
	"""% de cambio contra el período anterior (None si antes no hubo ventas)."""
	return round((actual - anterior) / anterior * 100, 1) if anterior else None


# ---------------------------------------------------------------------------
# Tarjetas de resumen
# ---------------------------------------------------------------------------


def _resumen(c, facturas, anteriores, items) -> dict:
	from galeria_arte.api.liquidaciones import POR_LIQUIDAR, POR_PAGAR, _obras_vendidas

	ventas = _suma(facturas, "grand_total")
	ventas_ant = _suma(anteriores, "grand_total")
	cobrado = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(paid_amount), 0) FROM `tabPayment Entry`
			WHERE company = %(company)s AND docstatus = 1 AND payment_type = 'Receive' AND galeria_pago = 1
				AND posting_date BETWEEN %(desde)s AND %(hasta)s
			""",
			c,
		)[0][0],
		2,
	)
	pendiente = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(outstanding_amount), 0) AS total,
			COALESCE(SUM(CASE WHEN status = 'Overdue' THEN outstanding_amount ELSE 0 END), 0) AS vencido
		FROM `tabSales Invoice`
		WHERE company = %(company)s AND docstatus = 1 AND is_return = 0 AND name LIKE %(serie)s
			AND outstanding_amount > 0
		""",
		c,
		as_dict=True,
	)[0]

	# Artistas: obras listas para liquidar + liquidaciones sin pagar.
	listas = [o for o in _obras_vendidas() if o.estado_pago == POR_LIQUIDAR]
	liquidaciones = frappe.get_all(
		"Liquidacion a Artista", filters={"estado": POR_PAGAR}, fields=["sum(total) as total", "count(name) as n"]
	)[0]
	por_pagar_artistas = flt(_suma(listas, "monto_artista") + flt(liquidaciones.total), 2)

	# Ganancia estimada (sin IVA).
	ganancia = {a: 0.0 for a in AREAS}
	for i in items:
		area = i.galeria_area if i.galeria_area in ganancia else None
		neto = flt(i.net_amount) - (flt(i.galeria_monto_artista) if i.galeria_obra else 0)
		if area:
			ganancia[area] = flt(ganancia[area] + neto, 2)

	return {
		"ventas": ventas,
		"ventas_anterior": ventas_ant,
		"cambio": _cambio(ventas, ventas_ant),
		"facturas": len(facturas),
		"ticket_promedio": flt(ventas / len(facturas), 2) if facturas else 0,
		"cobrado": cobrado,
		"por_cobrar": flt(pendiente.total, 2),
		"vencido": flt(pendiente.vencido, 2),
		"por_pagar_artistas": por_pagar_artistas,
		"obras_por_liquidar": len(listas),
		"liquidaciones_por_pagar": liquidaciones.n or 0,
		"ganancia": flt(sum(ganancia.values()), 2),
		"ganancia_por_area": ganancia,
	}


# ---------------------------------------------------------------------------
# Ventas por área (dona + serie en el tiempo)
# ---------------------------------------------------------------------------


def _areas(facturas, desde, hasta) -> dict:
	totales = {a: 0.0 for a in AREAS}
	for f in facturas:
		if f.galeria_area in totales:
			totales[f.galeria_area] = flt(totales[f.galeria_area] + f.grand_total, 2)

	# Agrupación según el largo del período: días, semanas o meses.
	dias = date_diff(hasta, desde) + 1
	if dias <= 31:
		escala = "día"
		clave = lambda d: d
		etiqueta = lambda d: f"{d.day:02d}-{d.month:02d}"
		inicio = desde
		paso = lambda d: add_days(d, 1)
	elif dias <= 120:
		escala = "semana"
		clave = lambda d: add_days(d, -d.weekday())
		etiqueta = lambda d: f"{d.day:02d}-{d.month:02d}"
		inicio = add_days(desde, -desde.weekday())
		paso = lambda d: add_days(d, 7)
	else:
		escala = "mes"
		clave = lambda d: d.replace(day=1)
		etiqueta = lambda d: f"{MESES[d.month - 1]} {d.year}"
		inicio = desde.replace(day=1)
		paso = lambda d: getdate(add_days(d.replace(day=28), 4)).replace(day=1)

	periodos = []
	d = getdate(inicio)
	while d <= hasta:
		periodos.append(d)
		d = getdate(paso(d))
	indice = {p: i for i, p in enumerate(periodos)}
	valores = {a: [0.0] * len(periodos) for a in AREAS}
	for f in facturas:
		i = indice.get(clave(getdate(f.posting_date)))
		if i is not None and f.galeria_area in valores:
			valores[f.galeria_area][i] = flt(valores[f.galeria_area][i] + f.grand_total, 2)

	return {
		"totales": totales,
		"escala": escala,
		"etiquetas": [etiqueta(p) for p in periodos],
		"series": valores,
	}


# ---------------------------------------------------------------------------
# Productos de cafetería
# ---------------------------------------------------------------------------


def _grupos_cafeteria() -> list:
	lft, rgt = frappe.db.get_value("Item Group", GRUPO_CAFETERIA, ["lft", "rgt"]) or (0, 0)
	return frappe.get_all("Item Group", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name")


def _productos(c, facturas, items) -> dict:
	grupos = set(_grupos_cafeteria())
	caf = [i for i in items if i.item_group in grupos]

	por_producto = {}
	for i in caf:
		p = por_producto.setdefault(
			i.item_code, frappe._dict(item_code=i.item_code, nombre=i.item_name, grupo=i.item_group, cantidad=0, ingreso=0)
		)
		p.cantidad += flt(i.qty)
		p.ingreso = flt(p.ingreso + flt(i.amount), 2)
	lista = sorted(por_producto.values(), key=lambda p: (-p.cantidad, -p.ingreso))

	por_categoria = defaultdict(lambda: {"cantidad": 0, "ingreso": 0.0})
	for i in caf:
		g = por_categoria[i.item_group]
		g["cantidad"] += flt(i.qty)
		g["ingreso"] = flt(g["ingreso"] + flt(i.amount), 2)

	vendidos = set(por_producto)
	sin_ventas = frappe.get_all(
		"Item",
		filters={
			"item_group": ["in", list(grupos) or [""]],
			"disabled": 0,
			"is_sales_item": 1,
			"name": ["not in", list(vendidos) or [""]],
		},
		fields=["name as item_code", "item_name as nombre", "item_group as grupo"],
		order_by="item_group asc, item_name asc",
	)

	# Cuándo se vende más (solo facturas de cafetería).
	cafeteria = [f for f in facturas if f.galeria_area == "Cafetería"]
	por_dia = [0.0] * 7
	por_hora = defaultdict(float)
	por_lista = defaultdict(float)
	for f in cafeteria:
		por_dia[getdate(f.posting_date).weekday()] += flt(f.grand_total)
		hora = int(str(f.posting_time or "0").split(":")[0] or 0)
		por_hora[hora] += flt(f.grand_total)
		por_lista[f.selling_price_list or _("Sin lista")] += flt(f.grand_total)
	horas = sorted(por_hora) or []
	rango_horas = list(range(min(horas), max(horas) + 1)) if horas else []

	return {
		"top": lista[:10],
		"total_productos": len(lista),
		"unidades": sum(p.cantidad for p in lista),
		"ingreso": _suma(caf, "amount"),
		"por_categoria": [
			{"grupo": g, "cantidad": v["cantidad"], "ingreso": v["ingreso"]}
			for g, v in sorted(por_categoria.items(), key=lambda x: -x[1]["ingreso"])
		],
		"sin_ventas": sin_ventas,
		"por_dia": {"etiquetas": list(DIAS), "valores": [flt(v, 2) for v in por_dia]},
		"por_hora": {"etiquetas": [f"{h}:00" for h in rango_horas], "valores": [flt(por_hora[h], 2) for h in rango_horas]},
		"por_lista": [{"lista": k, "total": flt(v, 2)} for k, v in sorted(por_lista.items(), key=lambda x: -x[1])],
		"tickets": len(cafeteria),
	}


# ---------------------------------------------------------------------------
# Arte
# ---------------------------------------------------------------------------


def _arte(c, items) -> dict:
	obras = [i for i in items if i.galeria_obra]
	info = {
		o.name: o
		for o in frappe.get_all(
			"Obra de Arte",
			filters={"name": ["in", [i.galeria_obra for i in obras] or [""]]},
			fields=["name", "titulo", "artista", "fecha_ingreso", "creation", "fecha_venta"],
		)
	}

	por_artista = {}
	canales = {"Directa": [0, 0.0], "Desde reserva": [0, 0.0], "Subasta": [0, 0.0]}
	dias_venta = []
	for i in obras:
		o = info.get(i.galeria_obra) or frappe._dict(artista=_("Sin artista"))
		a = por_artista.setdefault(o.artista, frappe._dict(artista=o.artista, obras=0, monto=0.0, para_artista=0.0))
		a.obras += 1
		a.monto = flt(a.monto + flt(i.amount), 2)
		a.para_artista = flt(a.para_artista + flt(i.galeria_monto_artista), 2)
		canal = "Subasta" if i.galeria_evento else "Desde reserva" if i.galeria_reservacion else "Directa"
		canales[canal][0] += 1
		canales[canal][1] = flt(canales[canal][1] + flt(i.amount), 2)
		entrada = o.get("fecha_ingreso") or (getdate(o.creation) if o.get("creation") else None)
		if entrada:
			dias_venta.append(max(date_diff(i.posting_date, entrada), 0))

	inventario = {
		f.estado: frappe._dict(estado=f.estado, obras=f.obras, valor=flt(f.valor, 2))
		for f in frappe.get_all(
			"Obra de Arte",
			filters={"estado": ["in", ["Disponible", "Reservada", "En subasta"]]},
			fields=["estado", "count(name) as obras", "sum(precio_venta) as valor"],
			group_by="estado",
		)
	}
	return {
		"vendidas": len(obras),
		"monto": _suma(obras, "amount"),
		"para_artistas": _suma(obras, "galeria_monto_artista"),
		"ticket_promedio": flt(_suma(obras, "amount") / len(obras), 2) if obras else 0,
		"por_artista": sorted(por_artista.values(), key=lambda a: -a.monto),
		"canales": [{"canal": k, "obras": v[0], "monto": v[1]} for k, v in canales.items()],
		"inventario": [inventario.get(e) or {"estado": e, "obras": 0, "valor": 0} for e in ("Disponible", "Reservada", "En subasta")],
		"dias_promedio_venta": round(sum(dias_venta) / len(dias_venta)) if dias_venta else None,
	}


# ---------------------------------------------------------------------------
# Eventos y subastas (por fecha del evento)
# ---------------------------------------------------------------------------


def _eventos(c, facturas) -> dict:
	eventos = frappe.get_all(
		"Evento",
		filters={"inicio": ["between", [f"{c.desde} 00:00:00", f"{c.hasta} 23:59:59"]]},
		fields=["name", "nombre", "tipo", "estado", "inicio", "cupo", "lugares_vendidos", "total_alquiler", "factura"],
		order_by="inicio asc",
	)
	ingreso_por_evento = defaultdict(float)
	for f in facturas:
		if f.galeria_evento:
			ingreso_por_evento[f.galeria_evento] += flt(f.grand_total)

	cenas = []
	for e in eventos:
		if e.tipo != "Cena" or e.estado in ("Cancelado", "Vencido"):
			continue
		cupo = int(e.cupo or 0)
		vendidos = int(e.lugares_vendidos or 0)
		cenas.append(
			{
				"name": e.name,
				"nombre": e.nombre,
				"inicio": e.inicio,
				"cupo": cupo,
				"vendidos": vendidos,
				"ocupacion": round(vendidos / cupo * 100) if cupo else 0,
				"ingreso": flt(ingreso_por_evento.get(e.name), 2),
			}
		)

	alquileres = defaultdict(int)
	ingreso_alquiler = 0.0
	for e in eventos:
		if e.tipo == "Alquiler":
			alquileres[e.estado] += 1
			ingreso_alquiler += flt(ingreso_por_evento.get(e.name))

	subastas = [e.name for e in eventos if e.tipo == "Subasta" and e.estado not in ("Cancelado", "Vencido")]
	lotes = (
		frappe.get_all(
			"Evento Lote",
			filters={"parenttype": "Evento", "parent": ["in", subastas]},
			fields=["resultado", "precio_inicial", "precio_ganador"],
		)
		if subastas
		else []
	)
	vendidas = [l for l in lotes if l.resultado in ("Adjudicada", "Pagada", "Vencida")]
	inicial = sum(flt(l.precio_inicial) for l in vendidas)
	ganador = sum(flt(l.precio_ganador) for l in vendidas)

	boletos = [f for f in facturas if f.galeria_area == "Eventos" and f.galeria_evento]
	return {
		"total": len([e for e in eventos if e.estado not in ("Cancelado", "Vencido")]),
		"por_tipo": {
			t: len([e for e in eventos if e.tipo == t and e.estado not in ("Cancelado", "Vencido")])
			for t in ("Exposición", "Cena", "Subasta", "Alquiler")
		},
		"ingreso_eventos": _suma(boletos, "grand_total"),
		"cenas": cenas,
		"alquileres": {
			"por_estado": dict(alquileres),
			"ingreso": flt(ingreso_alquiler, 2),
		},
		"subastas": {
			"subastas": len(subastas),
			"ofrecidas": len(lotes),
			"vendidas": len([l for l in lotes if l.resultado in ("Adjudicada", "Pagada")]),
			"no_pagaron": len([l for l in lotes if l.resultado == "Vencida"]),
			"no_vendidas": len([l for l in lotes if l.resultado == "No vendida"]),
			"pendientes": len([l for l in lotes if l.resultado == "Pendiente"]),
			"total_ganador": flt(sum(flt(l.precio_ganador) for l in lotes if l.resultado in ("Adjudicada", "Pagada")), 2),
			"alza": round((ganador - inicial) / inicial * 100, 1) if inicial else None,
		},
	}


# ---------------------------------------------------------------------------
# Cobros y cartera
# ---------------------------------------------------------------------------


def _cobros(c) -> dict:
	formas = frappe.db.sql(
		"""
		SELECT mode_of_payment AS modo, COUNT(name) AS pagos, SUM(paid_amount) AS total
		FROM `tabPayment Entry`
		WHERE company = %(company)s AND docstatus = 1 AND payment_type = 'Receive' AND galeria_pago = 1
			AND posting_date BETWEEN %(desde)s AND %(hasta)s
		GROUP BY mode_of_payment ORDER BY total DESC
		""",
		c,
		as_dict=True,
	)

	pendientes = frappe.db.sql(
		"""
		SELECT name, customer, customer_name, outstanding_amount FROM `tabSales Invoice`
		WHERE company = %(company)s AND docstatus = 1 AND is_return = 0 AND name LIKE %(serie)s
			AND outstanding_amount > 0
		""",
		c,
		as_dict=True,
	)
	calendario = defaultdict(list)
	if pendientes:
		for s in frappe.get_all(
			"Payment Schedule",
			filters={"parenttype": "Sales Invoice", "parent": ["in", [p.name for p in pendientes]]},
			fields=["parent", "idx", "due_date", "payment_amount"],
			order_by="parent asc, idx asc",
		):
			calendario[s.parent].append(s)

	# Lo que falta pagar corresponde a las últimas cuotas (los pagos cubren
	# primero las más antiguas): el saldo se reparte de la última hacia atrás.
	antiguedad = {"Al día": 0.0, "1 a 30 días": 0.0, "31 a 60 días": 0.0, "Más de 60 días": 0.0}
	proximas = []
	limite = add_days(c.hoy, 7)
	for p in pendientes:
		saldo = flt(p.outstanding_amount)
		filas = calendario.get(p.name) or [frappe._dict(idx=1, due_date=c.hoy, payment_amount=saldo)]
		pendiente_por_fila = []
		for s in reversed(filas):
			monto = min(saldo, flt(s.payment_amount)) if s is not filas[0] else saldo
			saldo = flt(saldo - monto, 2)
			if monto > 0.005:
				pendiente_por_fila.append((s, monto))
			if saldo <= 0.005:
				break
		for s, monto in pendiente_por_fila:
			atraso = date_diff(c.hoy, s.due_date)
			tramo = (
				"Al día" if atraso <= 0 else "1 a 30 días" if atraso <= 30 else "31 a 60 días" if atraso <= 60 else "Más de 60 días"
			)
			antiguedad[tramo] = flt(antiguedad[tramo] + monto, 2)
			if c.hoy <= getdate(s.due_date) <= getdate(limite):
				proximas.append(
					{
						"factura": p.name,
						"cliente": p.customer_name,
						"vence": s.due_date,
						"monto": flt(monto, 2),
						"cuota": s.idx if len(filas) > 1 else None,
						"cuotas": len(filas),
					}
				)
	proximas.sort(key=lambda x: str(x["vence"]))

	por_cliente = defaultdict(lambda: {"saldo": 0.0, "facturas": 0})
	nombres = {}
	for p in pendientes:
		por_cliente[p.customer]["saldo"] = flt(por_cliente[p.customer]["saldo"] + flt(p.outstanding_amount), 2)
		por_cliente[p.customer]["facturas"] += 1
		nombres[p.customer] = p.customer_name
	deudores = sorted(
		({"cliente": k, "nombre": nombres[k], **v} for k, v in por_cliente.items()), key=lambda x: -x["saldo"]
	)[:5]

	return {
		"formas_pago": [{"modo": f.modo or _("Sin forma de pago"), "pagos": f.pagos, "total": flt(f.total, 2)} for f in formas],
		"antiguedad": [{"tramo": k, "monto": v} for k, v in antiguedad.items()],
		"proximas": proximas[:10],
		"deudores": deudores,
	}


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------


def _clientes(c, facturas) -> list:
	por_cliente = {}
	for f in facturas:
		if f.customer == c.consumidor:
			continue
		x = por_cliente.setdefault(
			f.customer, frappe._dict(cliente=f.customer, nombre=f.customer_name, total=0.0, facturas=0, areas=set())
		)
		x.total = flt(x.total + flt(f.grand_total), 2)
		x.facturas += 1
		if f.galeria_area:
			x.areas.add(f.galeria_area)
	top = sorted(por_cliente.values(), key=lambda x: -x.total)[:10]
	tipos = {
		t.name: t.galeria_tipo_cliente
		for t in frappe.get_all(
			"Customer", filters={"name": ["in", [x.cliente for x in top] or [""]]}, fields=["name", "galeria_tipo_cliente"]
		)
	}
	for x in top:
		x.areas = sorted(x.areas)
		x.tipo = tipos.get(x.cliente)
	return top
