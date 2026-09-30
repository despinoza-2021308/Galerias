# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Obras de arte: estado automático desde la factura, catálogo y ficha del
coleccionista."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from galeria_arte.api.facturacion import FEL_CERTIFICADA, _prefijo_serie, get_config
from galeria_arte.galeria_arte.doctype.obra_de_arte.obra_de_arte import (
	DEVUELTA,
	DISPONIBLE,
	RESERVADA,
	VENDIDA,
)

# ---------------------------------------------------------------------------
# Hooks de Sales Invoice
# ---------------------------------------------------------------------------


def _filas_de_obras(doc):
	"""Filas de la factura cuyo artículo es una obra de arte."""
	codigos = [r.item_code for r in doc.items if r.item_code]
	if not codigos:
		return []
	obras = {
		o.articulo: o
		for o in frappe.get_all(
			"Obra de Arte",
			filters={"articulo": ["in", codigos]},
			fields=["name", "articulo", "titulo", "estado", "reservada_por", "factura", "monto_artista"],
		)
	}
	return [(r, obras[r.item_code]) for r in doc.items if r.item_code in obras]


def validar_factura(doc, method=None):
	"""Sales Invoice validate: una obra solo se vende una vez, y una obra
	reservada solo a quien la reservó. Congela el monto para el artista."""
	if doc.get("is_return"):
		return
	vistas = set()
	for row, obra in _filas_de_obras(doc):
		if obra.name in vistas:
			frappe.throw(_("La obra {0} está repetida en la factura.").format(obra.titulo))
		vistas.add(obra.name)
		if flt(row.qty) != 1:
			frappe.throw(_("La obra {0} es única: la cantidad debe ser 1.").format(obra.titulo))
		if obra.estado == VENDIDA and obra.factura != doc.name:
			frappe.throw(_("La obra {0} ya se vendió en la factura {1}.").format(obra.titulo, obra.factura))
		if obra.estado == DEVUELTA:
			frappe.throw(_("La obra {0} fue devuelta al artista.").format(obra.titulo))
		if obra.estado == RESERVADA and obra.reservada_por != doc.customer:
			frappe.throw(_("La obra {0} está reservada por {1}.").format(obra.titulo, obra.reservada_por))
		row.galeria_obra = obra.name
		# El monto del artista se congela en la factura. Si la venta no lo trae
		# explícito (factura hecha a mano), se toma el de la ficha de la obra.
		if not doc.flags.galeria_montos_explicitos and not flt(row.get("galeria_monto_artista")):
			row.galeria_monto_artista = obra.monto_artista


def al_validar_factura(doc, method=None):
	"""Sales Invoice on_submit: las obras facturadas pasan a Vendida."""
	if doc.get("is_return"):
		return
	for row, obra in _filas_de_obras(doc):
		frappe.db.set_value(
			"Obra de Arte",
			obra.name,
			{
				"estado": VENDIDA,
				"cliente": doc.customer,
				"factura": doc.name,
				"fecha_venta": doc.posting_date,
				"precio_vendido": row.amount,
				"monto_artista_venta": row.galeria_monto_artista,
			},
		)


def al_anular_factura(doc, method=None):
	"""Sales Invoice on_cancel: la obra vuelve a Reservada o Disponible."""
	for obra in frappe.get_all(
		"Obra de Arte", filters={"factura": doc.name}, fields=["name", "reservada_por"]
	):
		frappe.db.set_value(
			"Obra de Arte",
			obra.name,
			{
				"estado": RESERVADA if obra.reservada_por else DISPONIBLE,
				"cliente": None,
				"factura": None,
				"fecha_venta": None,
				"precio_vendido": 0,
				"monto_artista_venta": 0,
			},
		)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------


@frappe.whitelist()
def catalogo(
	artista: str | None = None,
	estado: str | None = None,
	precio_min: float | None = None,
	precio_max: float | None = None,
	buscar: str | None = None,
) -> dict:
	filtros = []
	if artista:
		filtros.append(["artista", "=", artista])
	if estado == "Reserva vencida":
		filtros.append(["estado", "=", RESERVADA])
		filtros.append(["fecha_limite_reserva", "<", nowdate()])
	elif estado:
		filtros.append(["estado", "=", estado])
	if flt(precio_min):
		filtros.append(["precio_venta", ">=", flt(precio_min)])
	if flt(precio_max):
		filtros.append(["precio_venta", "<=", flt(precio_max)])
	or_filtros = None
	if buscar:
		texto = f"%{buscar.strip()}%"
		or_filtros = [["titulo", "like", texto], ["artista", "like", texto], ["tecnica", "like", texto]]

	obras = frappe.get_all(
		"Obra de Arte",
		filters=filtros,
		or_filters=or_filtros,
		fields=[
			"name", "titulo", "artista", "tecnica", "anio", "estado", "imagen", "precio_venta",
			"alto_cm", "ancho_cm", "profundidad_cm", "reservada_por", "fecha_limite_reserva", "cliente",
		],
		order_by="titulo asc",
		limit_page_length=500,
	)
	orden = {DISPONIBLE: 0, RESERVADA: 1, VENDIDA: 2, DEVUELTA: 3}
	obras.sort(key=lambda o: orden.get(o.estado, 9))
	hoy = getdate(nowdate())
	for o in obras:
		o.reserva_vencida = bool(
			o.estado == RESERVADA and o.fecha_limite_reserva and getdate(o.fecha_limite_reserva) < hoy
		)

	conteo = {
		f.estado: f.cantidad
		for f in frappe.get_all("Obra de Arte", fields=["estado", "count(name) as cantidad"], group_by="estado")
	}
	conteo["Reserva vencida"] = frappe.db.count(
		"Obra de Arte", {"estado": RESERVADA, "fecha_limite_reserva": ["<", nowdate()]}
	)
	return {"obras": obras, "conteo": conteo}


@frappe.whitelist()
def interesados(artista: str) -> list:
	"""Clientes que marcaron a este artista como de su interés."""
	return frappe.db.sql(
		"""
		SELECT c.name, c.customer_name, c.galeria_tipo_cliente AS tipo, c.mobile_no, c.email_id
		FROM `tabCliente Artista Interes` i
		JOIN `tabCustomer` c ON c.name = i.parent AND i.parenttype = 'Customer'
		WHERE i.artista = %s AND c.disabled = 0
		ORDER BY c.customer_name
		""",
		artista,
		as_dict=True,
	)


# ---------------------------------------------------------------------------
# Ficha del coleccionista
# ---------------------------------------------------------------------------


@frappe.whitelist()
def ficha_coleccionista(cliente: str) -> dict:
	frappe.has_permission("Customer", "read", cliente, throw=True)
	conf = get_config()
	c = frappe.db.get_value(
		"Customer",
		cliente,
		["name", "customer_name", "tax_id", "galeria_tipo_cliente", "mobile_no", "email_id"],
		as_dict=True,
	)
	c.artistas_interes = frappe.get_all(
		"Cliente Artista Interes", filters={"parent": cliente, "parenttype": "Customer"}, pluck="artista"
	)

	campos_obra = ["name", "titulo", "artista", "imagen", "precio_venta"]
	compradas = frappe.get_all(
		"Obra de Arte",
		filters={"cliente": cliente, "estado": VENDIDA},
		fields=[*campos_obra, "fecha_venta", "precio_vendido", "factura"],
		order_by="fecha_venta desc",
	)
	reservadas = frappe.get_all(
		"Obra de Arte",
		filters={"reservada_por": cliente, "estado": RESERVADA},
		fields=[*campos_obra, "anticipo", "fecha_limite_reserva"],
		order_by="fecha_limite_reserva asc",
	)
	hoy = getdate(nowdate())
	for o in reservadas:
		o.reserva_vencida = bool(o.fecha_limite_reserva and getdate(o.fecha_limite_reserva) < hoy)

	facturas = frappe.get_all(
		"Sales Invoice",
		filters={
			"customer": cliente,
			"company": conf.company,
			"docstatus": 1,
			"is_return": 0,
			"name": ["like", f"{_prefijo_serie(conf.serie_factura)}%"],
		},
		fields=[
			"name", "posting_date", "galeria_area", "grand_total", "outstanding_amount", "status",
			"payment_terms_template", "bfel_status", "bfel_uuid",
		],
		order_by="posting_date desc, name desc",
	)
	por_area = {"Arte": 0.0, "Eventos": 0.0, "Cafetería": 0.0}
	for f in facturas:
		f.fel = "Certificada" if f.bfel_status == FEL_CERTIFICADA and f.bfel_uuid else "Pendiente de certificar"
		if f.galeria_area in por_area:
			por_area[f.galeria_area] = flt(por_area[f.galeria_area] + f.grand_total, 2)

	saldo_a_favor = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(unallocated_amount), 0) FROM `tabPayment Entry`
			WHERE party_type = 'Customer' AND party = %s AND company = %s AND docstatus = 1
				AND payment_type = 'Receive' AND galeria_pago = 1
			""",
			(cliente, conf.company),
		)[0][0],
		2,
	)
	anticipos_en_reservas = flt(sum(flt(o.anticipo) for o in reservadas), 2)

	return {
		"cliente": c,
		"obras_compradas": compradas,
		"obras_reservadas": reservadas,
		"facturas": facturas,
		"totales": {
			"comprado": flt(sum(f.grand_total for f in facturas), 2),
			"pendiente": flt(sum(f.outstanding_amount for f in facturas), 2),
			"por_area": por_area,
			"anticipos_en_reservas": anticipos_en_reservas,
			"saldo_a_favor": flt(max(saldo_a_favor - anticipos_en_reservas, 0), 2),
		},
	}


# ---------------------------------------------------------------------------
# Acciones sobre una obra (las usan la ficha y el catálogo)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def reservar(obra: str, cliente: str, anticipo: float, modo_pago: str, fecha_limite: str, referencia: str | None = None):
	return frappe.get_doc("Obra de Arte", obra).reservar(cliente, anticipo, modo_pago, fecha_limite, referencia)


@frappe.whitelist()
def cancelar_reserva(obra: str):
	return frappe.get_doc("Obra de Arte", obra).cancelar_reserva()


@frappe.whitelist()
def vender(
	obra: str,
	cliente: str,
	precio: float | None = None,
	monto_artista: float | None = None,
	plan_pagos: str | None = None,
	pagos=None,
):
	return frappe.get_doc("Obra de Arte", obra).vender(cliente, precio, monto_artista, plan_pagos, pagos)


@frappe.whitelist()
def devolver_al_artista(obra: str):
	return frappe.get_doc("Obra de Arte", obra).devolver_al_artista()


@frappe.whitelist()
def reingresar(obra: str):
	return frappe.get_doc("Obra de Arte", obra).reingresar()


@frappe.whitelist()
def datos_venta(obra: str) -> dict:
	"""Lo que necesita el diálogo de venta: la obra, su anticipo disponible y las opciones de cobro."""
	from galeria_arte.api.facturacion import opciones_cobro

	o = frappe.get_doc("Obra de Arte", obra)
	o.check_permission("read")
	anticipo = 0.0
	if o.estado == RESERVADA and o.pago_anticipo:
		pe = frappe.db.get_value("Payment Entry", o.pago_anticipo, ["docstatus", "unallocated_amount"], as_dict=True)
		if pe and pe.docstatus == 1:
			anticipo = flt(pe.unallocated_amount)
	return {
		"obra": {
			"name": o.name,
			"titulo": o.titulo,
			"artista": o.artista,
			"estado": o.estado,
			"precio_venta": o.precio_venta,
			"monto_artista": o.monto_artista,
			"reservada_por": o.reservada_por,
			"fecha_limite_reserva": o.fecha_limite_reserva,
		},
		"anticipo_disponible": anticipo,
		**opciones_cobro(),
	}
