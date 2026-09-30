# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""POS de cafetería: venta rápida que termina en una factura de la galería
pagada al momento. Reutiliza galeria_arte.api.facturacion."""

import frappe
from frappe import _
from frappe.utils import flt

from galeria_arte.api.facturacion import _cargar, _listas_precios, crear_factura, get_config, opciones_cobro

GRUPO_CAFETERIA = "Cafetería"
AREA = "Cafetería"
FORMATO_TICKET = "Ticket Galería"


def _categorias() -> list:
	"""Categorías hoja dentro del grupo Cafetería."""
	if not frappe.db.exists("Item Group", GRUPO_CAFETERIA):
		return []
	lft, rgt = frappe.db.get_value("Item Group", GRUPO_CAFETERIA, ["lft", "rgt"])
	return frappe.get_all(
		"Item Group",
		filters={"lft": [">=", lft], "rgt": ["<=", rgt], "is_group": 0},
		pluck="name",
		order_by="lft asc",
	)


def _precios(lista_precios: str, conf) -> dict:
	"""Precio por producto en la lista; si falta, se usa el de la lista Público."""
	precios = {}
	for lista in dict.fromkeys([conf.lista_precios_publico, lista_precios]):
		if not lista:
			continue
		for p in frappe.get_all(
			"Item Price",
			filters={"price_list": lista, "selling": 1},
			fields=["item_code", "price_list_rate"],
		):
			precios[p.item_code] = flt(p.price_list_rate)
	return precios


@frappe.whitelist()
def datos_pos() -> dict:
	conf = get_config()
	return {
		"categorias": _categorias(),
		"listas_precios": _listas_precios(conf),
		"lista_precios": conf.lista_precios_publico,
		"cliente": conf.cliente_consumidor_final,
		"modos_pago": opciones_cobro()["modos_pago"],
		"formato_ticket": FORMATO_TICKET,
	}


@frappe.whitelist()
def productos(lista_precios: str | None = None) -> list:
	conf = get_config()
	lista_precios = lista_precios if lista_precios in _listas_precios(conf) else conf.lista_precios_publico
	categorias = _categorias()
	if not categorias:
		return []
	precios = _precios(lista_precios, conf)
	items = frappe.get_all(
		"Item",
		filters={"item_group": ["in", categorias], "disabled": 0, "is_sales_item": 1, "has_variants": 0},
		fields=["name as item_code", "item_name", "item_group", "image"],
		order_by="item_group asc, item_name asc",
	)
	for it in items:
		it.precio = precios.get(it.item_code, 0)
	return [it for it in items if it.precio > 0]


@frappe.whitelist()
def vender(items, pagos, cliente: str | None = None, lista_precios: str | None = None) -> dict:
	"""Venta de mostrador: factura de la galería pagada por completo.

	items: [{item_code, qty}]. Los precios se toman de la lista en el servidor.
	pagos: [{modo_pago, monto, referencia?}]; deben sumar el total.
	"""
	items = _cargar(items) or []
	pagos = [p for p in (_cargar(pagos) or []) if flt(p.get("monto")) > 0]
	if not items:
		frappe.throw(_("El pedido está vacío."))
	conf = get_config()
	lista_precios = lista_precios if lista_precios in _listas_precios(conf) else conf.lista_precios_publico

	categorias = set(_categorias())
	precios = _precios(lista_precios, conf)
	lineas, total = [], 0.0
	for row in items:
		codigo, qty = row.get("item_code"), flt(row.get("qty"))
		if qty <= 0:
			continue
		if frappe.db.get_value("Item", codigo, "item_group") not in categorias:
			frappe.throw(_("El producto {0} no es de la cafetería.").format(codigo))
		precio = precios.get(codigo)
		if not precio:
			frappe.throw(_("El producto {0} no tiene precio en la lista {1}.").format(codigo, lista_precios))
		lineas.append({"item_code": codigo, "qty": qty, "rate": precio})
		total += qty * precio
	total = flt(total, 2)
	if not lineas:
		frappe.throw(_("El pedido está vacío."))

	pagado = flt(sum(flt(p["monto"]) for p in pagos), 2)
	if abs(pagado - total) > 0.005:
		frappe.throw(
			_("Los pagos (Q{0}) deben sumar el total de la venta (Q{1}).").format(pagado, total)
		)
	modos = set(opciones_cobro()["modos_pago"])
	for p in pagos:
		if p.get("modo_pago") not in modos:
			frappe.throw(_("Forma de pago no válida: {0}").format(p.get("modo_pago")))

	estado = crear_factura(
		items=lineas, cliente=cliente, area=AREA, lista_precios=lista_precios, pagos=pagos
	)
	estado["formato_ticket"] = FORMATO_TICKET
	return estado


@frappe.whitelist()
def crear_cliente(nombre: str, nit: str | None = None) -> dict:
	"""Cliente rápido desde el POS para facturas con NIT."""
	nombre = (nombre or "").strip()
	nit = (nit or "").strip().upper() or "CF"
	if not nombre:
		frappe.throw(_("Indique el nombre del cliente."))
	if nit != "CF":
		existente = frappe.db.get_value("Customer", {"tax_id": nit}, ["name", "customer_name"], as_dict=True)
		if existente:
			return {"name": existente.name, "customer_name": existente.customer_name, "existente": True}
	cliente = frappe.new_doc("Customer")
	cliente.customer_name = nombre
	cliente.customer_type = "Individual"
	cliente.customer_group = frappe.db.get_single_value("Selling Settings", "customer_group") or frappe.db.get_value(
		"Customer Group", {"is_group": 0}, "name"
	)
	cliente.territory = frappe.db.get_single_value("Selling Settings", "territory") or frappe.db.get_value(
		"Territory", {"is_group": 0}, "name"
	)
	cliente.tax_id = nit
	if cliente.meta.has_field("bfel_identificacion"):
		cliente.bfel_identificacion = "CF" if nit == "CF" else "NIT"
	if cliente.meta.has_field("bfel_id_receptor"):
		cliente.bfel_id_receptor = nit
	cliente.insert()
	return {"name": cliente.name, "customer_name": cliente.customer_name, "existente": False}
