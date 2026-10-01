# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Pago a artistas por obras vendidas en consignación.

- Cada venta congela en la factura el monto para el artista.
- Una obra se puede liquidar solo cuando el cliente terminó de pagar su factura.
- Una liquidación junta varias obras del mismo artista: genera una factura de
  compra al proveedor del artista (cuentas por pagar) y, al pagarse, un pago.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, nowdate

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

from galeria_arte.api.facturacion import _cargar, get_config, opciones_cobro

ARTICULO_LIQUIDACION = "LIQ-OBRA"
GRUPO_ARTICULO = "Obras de Arte"
UOM = "Unidad(es)"

POR_PAGAR = "Por pagar"
PAGADA = "Pagada"
ANULADA = "Anulada"

# Estado del pago al artista de una obra vendida
ESPERA_CLIENTE = "En espera del cliente"
POR_LIQUIDAR = "Por liquidar"
EN_LIQUIDACION = "En liquidación"
PAGADO = "Pagado al artista"
SIN_PAGO = "Sin pago al artista"


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def _obras_vendidas(artista: str | None = None, obras: list | None = None) -> list:
	condiciones, valores = ["o.estado = 'Vendida'"], {}
	if artista:
		condiciones.append("o.artista = %(artista)s")
		valores["artista"] = artista
	if obras:
		condiciones.append("o.name IN %(obras)s")
		valores["obras"] = tuple(obras)
	filas = frappe.db.sql(
		f"""
		SELECT o.name, o.titulo, o.artista, o.imagen, o.cliente, o.factura, o.fecha_venta,
			o.precio_vendido, o.monto_artista_venta AS monto_artista, o.liquidacion, o.artista_pagado,
			si.outstanding_amount AS saldo_cliente, si.docstatus AS factura_docstatus,
			si.customer_name AS cliente_nombre
		FROM `tabObra de Arte` o
		LEFT JOIN `tabSales Invoice` si ON si.name = o.factura
		WHERE {" AND ".join(condiciones)}
		ORDER BY o.fecha_venta DESC, o.name DESC
		""",
		valores,
		as_dict=True,
	)
	for f in filas:
		f.estado_pago = _estado_pago(f)
	return filas


def _estado_pago(o) -> str:
	if o.artista_pagado:
		return PAGADO
	if o.liquidacion:
		return EN_LIQUIDACION
	if o.factura_docstatus != 1 or flt(o.saldo_cliente) > 0.005:
		return ESPERA_CLIENTE
	if flt(o.monto_artista) <= 0:
		return SIN_PAGO
	return POR_LIQUIDAR


@frappe.whitelist()
def estado_obra(obra: str) -> dict | None:
	"""Cómo va el pago al artista de una obra vendida (para la ficha de la obra)."""
	filas = _obras_vendidas(obras=[obra])
	if not filas:
		return None
	o = filas[0]
	return {
		"estado_pago": o.estado_pago,
		"monto_artista": o.monto_artista,
		"saldo_cliente": o.saldo_cliente,
		"liquidacion": o.liquidacion,
	}


def listas_por_factura(facturas: list) -> dict:
	"""Obras de esas facturas que el cliente ya pagó y falta liquidar al artista
	(para ofrecer el botón "Liquidar al artista")."""
	nombres = frappe.get_all("Obra de Arte", filters={"factura": ["in", list(facturas) or [""]]}, pluck="name")
	salida = {}
	for o in _obras_vendidas(obras=nombres) if nombres else []:
		if o.estado_pago == POR_LIQUIDAR:
			salida.setdefault(o.factura, []).append(
				{"obra": o.name, "titulo": o.titulo, "artista": o.artista, "monto_artista": o.monto_artista}
			)
	return salida


@frappe.whitelist()
def por_liquidar(artista: str) -> list:
	"""Obras del artista listas para pagarle: vendidas, cobradas por completo y sin liquidar."""
	return [o for o in _obras_vendidas(artista=artista) if o.estado_pago == POR_LIQUIDAR]


@frappe.whitelist()
def resumen() -> dict:
	"""Panel de Pagos a Artistas."""
	frappe.has_permission("Liquidacion a Artista", "read", throw=True)
	obras = _obras_vendidas()
	mes = get_first_day(getdate(nowdate()))

	liquidaciones = frappe.get_all(
		"Liquidacion a Artista",
		fields=[
			"name", "artista", "fecha", "estado", "total", "modo_pago", "referencia", "fecha_pago",
			"factura_compra", "pago", "motivo_anulacion",
		],
		order_by="creation desc",
		limit_page_length=300,
	)
	cantidades = {
		f.parent: f.n
		for f in frappe.get_all(
			"Liquidacion a Artista Obra",
			filters={"parenttype": "Liquidacion a Artista"},
			fields=["parent", "count(name) as n"],
			group_by="parent",
		)
	}
	for l in liquidaciones:
		l.num_obras = cantidades.get(l.name, 0)

	artistas = {}
	for a in frappe.get_all("Artista", fields=["name", "foto", "activo"], order_by="name asc"):
		artistas[a.name] = frappe._dict(
			artista=a.name, foto=a.foto,
			listas=0, monto_listas=0.0, espera=0, monto_espera=0.0,
			por_pagar=0.0, pagado=0.0, pagado_mes=0.0, vendidas=0,
		)
	for o in obras:
		a = artistas.get(o.artista)
		if not a:
			continue
		a.vendidas += 1
		if o.estado_pago == POR_LIQUIDAR:
			a.listas += 1
			a.monto_listas += flt(o.monto_artista)
		elif o.estado_pago == ESPERA_CLIENTE:
			a.espera += 1
			a.monto_espera += flt(o.monto_artista)
	for l in liquidaciones:
		a = artistas.get(l.artista)
		if not a:
			continue
		if l.estado == POR_PAGAR:
			a.por_pagar += flt(l.total)
		elif l.estado == PAGADA:
			a.pagado += flt(l.total)
			if l.fecha_pago and getdate(l.fecha_pago) >= mes:
				a.pagado_mes += flt(l.total)

	filas = [a for a in artistas.values() if a.vendidas or a.por_pagar or a.pagado]
	filas.sort(key=lambda a: (-(a.monto_listas + a.por_pagar), a.artista))
	return {
		"artistas": filas,
		"liquidaciones": liquidaciones,
		"obras": obras,
		"totales": {
			"por_liquidar": flt(sum(a.monto_listas for a in filas), 2),
			"obras_por_liquidar": sum(a.listas for a in filas),
			"en_espera": flt(sum(a.monto_espera for a in filas), 2),
			"obras_en_espera": sum(a.espera for a in filas),
			"por_pagar": flt(sum(a.por_pagar for a in filas), 2),
			"pagado_mes": flt(sum(a.pagado_mes for a in filas), 2),
		},
		"modos_pago": opciones_cobro()["modos_pago"],
	}


# ---------------------------------------------------------------------------
# Liquidar, pagar y anular
# ---------------------------------------------------------------------------


def asegurar_articulo_liquidacion() -> str:
	"""Artículo de compra con el que se registra en ERPNext lo que se paga al artista."""
	if not frappe.db.exists("Item", ARTICULO_LIQUIDACION):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": ARTICULO_LIQUIDACION,
				"item_name": "Liquidación de obra en consignación",
				"description": "Pago al artista por una obra vendida en consignación",
				"item_group": GRUPO_ARTICULO,
				"stock_uom": UOM,
				"is_stock_item": 0,
				"is_sales_item": 0,
				"is_purchase_item": 1,
				"include_item_in_manufacturing": 0,
			}
		).insert(ignore_permissions=True)
	return ARTICULO_LIQUIDACION


@frappe.whitelist()
def crear_liquidacion(
	artista: str,
	obras,
	pagar: int = 0,
	modo_pago: str | None = None,
	referencia: str | None = None,
	notas: str | None = None,
) -> dict:
	"""Liquida las obras indicadas: registra la deuda con el artista y, si se
	pide, el pago en el mismo paso."""
	frappe.has_permission("Liquidacion a Artista", "write", throw=True)
	seleccion = _cargar(obras) or []
	if not seleccion:
		frappe.throw(_("Elija al menos una obra para liquidar."))
	if int(pagar or 0) and not modo_pago:
		frappe.throw(_("Indique la forma de pago."))

	listas = {o.name: o for o in por_liquidar(artista)}
	faltan = [o for o in seleccion if o not in listas]
	if faltan:
		frappe.throw(
			_("Estas obras no están listas para liquidar (no son del artista, el cliente aún debe o ya se liquidaron): {0}").format(
				", ".join(faltan)
			)
		)
	proveedor = frappe.db.get_value("Artista", artista, "proveedor")
	if not proveedor:
		frappe.throw(_("El artista {0} no tiene proveedor vinculado.").format(artista))

	liq = frappe.new_doc("Liquidacion a Artista")
	liq.artista = artista
	liq.proveedor = proveedor
	liq.fecha = nowdate()
	liq.notas = notas
	for nombre in seleccion:
		o = listas[nombre]
		liq.append(
			"obras",
			{
				"obra": o.name,
				"titulo": o.titulo,
				"factura": o.factura,
				"fecha_venta": o.fecha_venta,
				"cliente": o.cliente,
				"precio_vendido": o.precio_vendido,
				"monto_artista": o.monto_artista,
			},
		)
	liq.insert(ignore_permissions=True)

	liq.factura_compra = _crear_factura_compra(liq)
	liq.save(ignore_permissions=True)
	for fila in liq.obras:
		frappe.db.set_value("Obra de Arte", fila.obra, "liquidacion", liq.name)

	if int(pagar or 0):
		return pagar_liquidacion(liq.name, modo_pago, referencia)
	return {"liquidacion": liq.name, "estado": liq.estado, "total": liq.total}


def _crear_factura_compra(liq) -> str:
	conf = get_config()
	articulo = asegurar_articulo_liquidacion()
	company = frappe.get_cached_doc("Company", conf.company)
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = conf.company
	pi.supplier = liq.proveedor
	pi.posting_date = nowdate()
	pi.bill_no = liq.name
	pi.bill_date = nowdate()
	pi.update_stock = 0
	pi.galeria_liquidacion = liq.name
	pi.remarks = f"Liquidación {liq.name} al artista {liq.artista}"
	for fila in liq.obras:
		pi.append(
			"items",
			{
				"item_code": articulo,
				"item_name": f"Obra: {fila.titulo}"[:140],
				"description": f"Obra {fila.titulo} ({fila.obra}) vendida en la factura {fila.factura}",
				"qty": 1,
				"rate": flt(fila.monto_artista),
				"expense_account": company.default_expense_account,
				"cost_center": company.cost_center,
			},
		)
	pi.set_missing_values()
	for row, fila in zip(pi.items, liq.obras):
		row.rate = row.price_list_rate = flt(fila.monto_artista)
		row.discount_percentage = 0
	pi.set("taxes", [])
	pi.taxes_and_charges = None
	pi.calculate_taxes_and_totals()
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi.name


@frappe.whitelist()
def pagar_liquidacion(liquidacion: str, modo_pago: str, referencia: str | None = None) -> dict:
	frappe.has_permission("Liquidacion a Artista", "write", throw=True)
	liq = frappe.get_doc("Liquidacion a Artista", liquidacion)
	if liq.estado != POR_PAGAR:
		frappe.throw(_("La liquidación {0} no está por pagar (estado: {1}).").format(liq.name, liq.estado))
	if modo_pago not in opciones_cobro()["modos_pago"]:
		frappe.throw(_("Forma de pago no válida: {0}").format(modo_pago))

	pe = get_payment_entry("Purchase Invoice", liq.factura_compra)
	pe.mode_of_payment = modo_pago
	pe.paid_from = get_bank_cash_account(modo_pago, liq.company)["account"]
	pe.paid_from_account_currency = frappe.get_cached_value("Account", pe.paid_from, "account_currency")
	pe.reference_no = referencia or f"Pago {liq.name}"
	pe.reference_date = nowdate()
	pe.galeria_pago = 1
	pe.galeria_liquidacion = liq.name
	pe.custom_remarks = 1
	pe.remarks = f"Pago de la liquidación {liq.name} al artista {liq.artista}"
	pe.set_amounts()
	pe.insert(ignore_permissions=True)
	pe.submit()

	liq.estado = PAGADA
	liq.modo_pago = modo_pago
	liq.referencia = referencia
	liq.fecha_pago = nowdate()
	liq.pago = pe.name
	liq.save(ignore_permissions=True)
	for fila in liq.obras:
		frappe.db.set_value("Obra de Arte", fila.obra, "artista_pagado", 1)
	return {"liquidacion": liq.name, "estado": liq.estado, "total": liq.total, "pago": pe.name}


@frappe.whitelist()
def anular_liquidacion(liquidacion: str, motivo: str | None = None) -> dict:
	"""Revierte la liquidación: anula el pago y la factura de compra, y las
	obras vuelven a quedar por liquidar."""
	frappe.has_permission("Liquidacion a Artista", "write", throw=True)
	liq = frappe.get_doc("Liquidacion a Artista", liquidacion)
	if liq.estado == ANULADA:
		frappe.throw(_("La liquidación {0} ya está anulada.").format(liq.name))

	if liq.pago and frappe.db.get_value("Payment Entry", liq.pago, "docstatus") == 1:
		frappe.get_doc("Payment Entry", liq.pago).cancel()
	if liq.factura_compra and frappe.db.get_value("Purchase Invoice", liq.factura_compra, "docstatus") == 1:
		frappe.get_doc("Purchase Invoice", liq.factura_compra).cancel()

	liq.estado = ANULADA
	liq.motivo_anulacion = motivo
	liq.save(ignore_permissions=True)
	for fila in liq.obras:
		if frappe.db.get_value("Obra de Arte", fila.obra, "liquidacion") == liq.name:
			frappe.db.set_value("Obra de Arte", fila.obra, {"liquidacion": None, "artista_pagado": 0})
	return {"liquidacion": liq.name, "estado": liq.estado}
