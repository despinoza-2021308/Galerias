# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Facturación y cobros de la galería.

- Las facturas usan la serie, la plantilla de IVA incluido y las listas de
  precios de Configuracion Galeria.
- La FEL la certifica Brainfel; mientras `certificar_fel_automaticamente`
  esté apagado, las facturas quedan pendientes de certificar.
- Los pagos (mixtos, abonos, cuotas) son Payment Entry nativos de ERPNext.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

FEL_CERTIFICADA = "02 Procesada"


def get_config():
	conf = frappe.get_cached_doc("Configuracion Galeria")
	if not conf.company:
		frappe.throw(_("Configure la empresa en Configuración Galería."))
	return conf


def _prefijo_serie(serie: str) -> str:
	return (serie or "").split(".")[0]


def es_factura_galeria(doc) -> bool:
	serie = get_config().serie_factura
	return bool(doc.name and doc.name.startswith(_prefijo_serie(serie))) or doc.get("naming_series") == serie


def extend_bootinfo(bootinfo):
	"""Datos mínimos de la galería para el escritorio (serie y plantilla de IVA)."""
	try:
		conf = frappe.get_cached_doc("Configuracion Galeria")
	except Exception:
		return
	bootinfo.galeria = {
		"serie_factura": conf.serie_factura,
		"prefijo": _prefijo_serie(conf.serie_factura),
		"plantilla_impuestos": conf.plantilla_impuestos,
		"lista_precios_publico": conf.lista_precios_publico,
		"listas_precios": [
			l for l in (conf.lista_precios_publico, conf.lista_precios_evento, conf.lista_precios_happy_hour) if l
		],
	}


def _cargar(valor):
	if isinstance(valor, str):
		return json.loads(valor) if valor else None
	return valor


# ---------------------------------------------------------------------------
# Facturas
# ---------------------------------------------------------------------------


@frappe.whitelist()
def crear_factura(
	items,
	cliente: str | None = None,
	area: str | None = None,
	lista_precios: str | None = None,
	plan_pagos: str | None = None,
	pagos=None,
	observaciones: str | None = None,
):
	"""Crea y valida una factura de la galería.

	items: [{item_code, qty, rate?}]; sin rate se usa el precio de la lista.
	plan_pagos: Payment Terms Template (cuotas); vacío = contado.
	pagos: [{modo_pago, monto, referencia?}] que se registran al momento.
	"""
	items = _cargar(items) or []
	if not items:
		frappe.throw(_("Agregue al menos un producto."))
	conf = get_config()

	si = frappe.new_doc("Sales Invoice")
	si.naming_series = conf.serie_factura
	si.company = conf.company
	si.customer = cliente or conf.cliente_consumidor_final
	if not si.customer:
		frappe.throw(_("Indique el cliente o configure el cliente Consumidor Final."))
	si.posting_date = nowdate()
	si.set_posting_time = 0
	si.galeria_area = area
	si.selling_price_list = lista_precios or conf.lista_precios_publico
	si.taxes_and_charges = conf.plantilla_impuestos
	si.remarks = observaciones
	if plan_pagos:
		si.payment_terms_template = plan_pagos

	for row in items:
		item = {"item_code": row["item_code"], "qty": flt(row.get("qty") or 1)}
		if row.get("rate") not in (None, ""):
			item["rate"] = flt(row["rate"])
			item["price_list_rate"] = flt(row["rate"])
		si.append("items", item)

	si.set_missing_values()
	# set_missing_values trae el precio de lista; se respeta el precio enviado.
	for row, original in zip(si.items, items):
		if original.get("rate") not in (None, ""):
			row.price_list_rate = row.rate = flt(original["rate"])
			row.discount_percentage = 0
	if si.taxes_and_charges:
		si.set("taxes", [])
		si.set_taxes()
	si.calculate_taxes_and_totals()
	si.insert()
	si.submit()

	pagos = _cargar(pagos) or []
	if pagos:
		registrar_pagos(si.name, pagos)

	return estado_factura(si.name)


@frappe.whitelist()
def certificar(factura: str):
	"""Certifica con Brainfel (sin modificarlo)."""
	from brainfel.api.certify_sales_invoice import certify_sales_invoice

	certify_sales_invoice(sales_invoice_name=factura)
	return estado_factura(factura)


def on_submit_factura(doc, method=None):
	"""Sales Invoice on_submit: certificación automática si está activada."""
	if not es_factura_galeria(doc):
		return
	if not frappe.db.get_single_value("Configuracion Galeria", "certificar_fel_automaticamente"):
		return
	frappe.enqueue(
		"galeria_arte.api.facturacion._certificar_en_segundo_plano",
		factura=doc.name,
		enqueue_after_commit=True,
	)


def _certificar_en_segundo_plano(factura: str):
	try:
		certificar(factura)
	except Exception:
		frappe.log_error(title=f"Galería: no se pudo certificar {factura}")


# ---------------------------------------------------------------------------
# Pagos
# ---------------------------------------------------------------------------


def marcar_pago_galeria(doc, method=None):
	"""Payment Entry validate: marca los pagos aplicados a facturas de la galería
	(también los registrados desde el escritorio) para el cierre de caja."""
	prefijo = _prefijo_serie(get_config().serie_factura)
	if any(
		r.reference_doctype == "Sales Invoice" and (r.reference_name or "").startswith(prefijo)
		for r in doc.references
	):
		doc.galeria_pago = 1


@frappe.whitelist()
def registrar_pagos(factura: str, pagos):
	"""Registra uno o varios pagos (pago mixto o abono) contra una factura.

	pagos: [{modo_pago, monto, referencia?}]. Cada forma de pago genera un
	Payment Entry. Si la factura tiene cuotas, el monto se aplica a las cuotas
	en orden de vencimiento.
	"""
	pagos = [p for p in (_cargar(pagos) or []) if flt(p.get("monto")) > 0]
	if not pagos:
		frappe.throw(_("Indique al menos un pago con monto mayor a cero."))

	si = frappe.get_doc("Sales Invoice", factura)
	if si.docstatus != 1:
		frappe.throw(_("La factura {0} no está validada.").format(factura))
	total = sum(flt(p["monto"]) for p in pagos)
	if flt(total, 2) > flt(si.outstanding_amount, 2):
		frappe.throw(
			_("El total de los pagos (Q{0}) es mayor que el saldo pendiente (Q{1}).").format(
				flt(total, 2), flt(si.outstanding_amount, 2)
			)
		)

	creados = []
	for p in pagos:
		creados.append(_crear_payment_entry(si, p["modo_pago"], flt(p["monto"]), p.get("referencia")))
	return {"pagos": creados, **estado_factura(factura)}


def _crear_payment_entry(si, modo_pago: str, monto: float, referencia: str | None = None) -> str:
	pe = get_payment_entry("Sales Invoice", si.name, party_amount=monto)
	pe.mode_of_payment = modo_pago
	pe.paid_to = get_bank_cash_account(modo_pago, si.company)["account"]
	pe.paid_to_account_currency = frappe.get_cached_value("Account", pe.paid_to, "account_currency")
	pe.paid_amount = pe.received_amount = monto
	pe.reference_no = referencia or f"{modo_pago} {si.name}"
	pe.reference_date = nowdate()

	# get_payment_entry asigna el saldo completo de cada cuota; se reparte el
	# monto real en orden de vencimiento.
	restante = monto
	for ref in list(pe.references):
		asignar = min(restante, flt(ref.get("payment_term_outstanding") or ref.outstanding_amount))
		if asignar <= 0:
			pe.remove(ref)
			continue
		ref.allocated_amount = asignar
		restante = flt(restante - asignar, 2)

	pe.set_amounts()
	pe.insert()
	pe.submit()
	return pe.name


@frappe.whitelist()
def estado_factura(factura: str) -> dict:
	si = frappe.get_doc("Sales Invoice", factura)
	pagos = frappe.db.sql(
		"""
		SELECT pe.name, pe.posting_date, pe.mode_of_payment, per.allocated_amount AS monto,
			per.payment_term AS cuota
		FROM `tabPayment Entry Reference` per
		JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Sales Invoice' AND per.reference_name = %s AND pe.docstatus = 1
		ORDER BY pe.posting_date, pe.creation
		""",
		factura,
		as_dict=True,
	)
	return {
		"factura": si.name,
		"cliente": si.customer_name,
		"fecha": si.posting_date,
		"area": si.get("galeria_area"),
		"total": si.grand_total,
		"pagado": flt(si.grand_total - si.outstanding_amount, 2),
		"pendiente": si.outstanding_amount,
		"estado": si.status,
		"fel": "Certificada" if si.get("bfel_status") == FEL_CERTIFICADA and si.get("bfel_uuid") else "Pendiente de certificar",
		"fel_uuid": si.get("bfel_uuid"),
		"plan_pagos": si.payment_terms_template,
		"cuotas": [
			{
				"cuota": c.description or c.payment_term,
				"vence": c.due_date,
				"monto": c.payment_amount,
				"pagado": c.paid_amount,
				"pendiente": c.outstanding,
			}
			for c in si.payment_schedule
		]
		if si.payment_terms_template
		else [],
		"pagos": pagos,
	}


@frappe.whitelist()
def facturas_pendientes(cliente: str | None = None, area: str | None = None, vencidas: int = 0) -> list:
	"""Facturas de la galería con saldo pendiente."""
	conf = get_config()
	filtros = {
		"company": conf.company,
		"docstatus": 1,
		"outstanding_amount": [">", 0],
		"name": ["like", f"{_prefijo_serie(conf.serie_factura)}%"],
	}
	if cliente:
		filtros["customer"] = cliente
	if area:
		filtros["galeria_area"] = area
	if int(vencidas or 0):
		filtros["status"] = "Overdue"
	facturas = frappe.get_all(
		"Sales Invoice",
		filters=filtros,
		fields=[
			"name", "customer", "customer_name", "posting_date", "due_date", "grand_total",
			"outstanding_amount", "status", "galeria_area", "payment_terms_template", "bfel_status", "bfel_uuid",
		],
		order_by="due_date asc, posting_date asc",
	)
	hoy = getdate(nowdate())
	for f in facturas:
		f.pagado = flt(f.grand_total - f.outstanding_amount, 2)
		f.fel = "Certificada" if f.bfel_status == FEL_CERTIFICADA and f.bfel_uuid else "Pendiente de certificar"
		proxima = frappe.db.get_value(
			"Payment Schedule",
			{"parent": f.name, "parenttype": "Sales Invoice", "outstanding": [">", 0]},
			["due_date", "outstanding"],
			order_by="due_date asc",
			as_dict=True,
		)
		f.proximo_vencimiento = proxima.due_date if proxima else f.due_date
		f.proximo_monto = proxima.outstanding if proxima else f.outstanding_amount
		f.vencida = bool(f.proximo_vencimiento and getdate(f.proximo_vencimiento) < hoy)
	return facturas


@frappe.whitelist()
def opciones_cobro() -> dict:
	"""Formas de pago con cuenta en la empresa y planes de cuotas de la galería."""
	conf = get_config()
	modos = frappe.get_all(
		"Mode of Payment Account",
		filters={"company": conf.company, "parenttype": "Mode of Payment"},
		pluck="parent",
		order_by="parent asc",
	)
	modos = [m for m in modos if frappe.db.get_value("Mode of Payment", m, "enabled")]
	planes = frappe.get_all(
		"Payment Terms Template", filters={"template_name": ["like", "Galería %"]}, pluck="name"
	)
	planes.sort(key=lambda p: int("".join(c for c in p if c.isdigit()) or 0))
	return {"modos_pago": modos, "planes_pago": planes}


# ---------------------------------------------------------------------------
# Ventas de la galería
# ---------------------------------------------------------------------------

ESTADOS_PAGO = {
	"Pagada": ["Paid"],
	"Pendiente": ["Unpaid", "Partly Paid", "Overdue", "Unpaid and Discounted", "Partly Paid and Discounted", "Overdue and Discounted"],
	"Vencida": ["Overdue", "Overdue and Discounted"],
}


@frappe.whitelist()
def ventas(
	desde: str | None = None,
	hasta: str | None = None,
	area: str | None = None,
	cliente: str | None = None,
	estado_pago: str | None = None,
	fel: str | None = None,
) -> dict:
	"""Facturas de la galería (solo serie de la galería) con totales."""
	from frappe.utils import get_first_day

	conf = get_config()
	hoy = getdate(nowdate())
	desde = getdate(desde) if desde else get_first_day(hoy)
	hasta = getdate(hasta) if hasta else hoy
	base = {
		"company": conf.company,
		"docstatus": 1,
		"is_return": 0,
		"name": ["like", f"{_prefijo_serie(conf.serie_factura)}%"],
	}

	filtros = dict(base, posting_date=["between", [desde, hasta]])
	if area:
		filtros["galeria_area"] = area
	if cliente:
		filtros["customer"] = cliente
	if estado_pago in ESTADOS_PAGO:
		filtros["status"] = ["in", ESTADOS_PAGO[estado_pago]]
	if fel == "Certificada":
		filtros["bfel_uuid"] = ["is", "set"]
	elif fel == "Pendiente de certificar":
		filtros["bfel_uuid"] = ["is", "not set"]

	facturas = frappe.get_all(
		"Sales Invoice",
		filters=filtros,
		fields=[
			"name", "posting_date", "customer", "customer_name", "galeria_area", "grand_total",
			"outstanding_amount", "status", "payment_terms_template", "bfel_status", "bfel_uuid",
		],
		order_by="posting_date desc, name desc",
		limit_page_length=500,
	)
	for f in facturas:
		f.pagado = flt(f.grand_total - f.outstanding_amount, 2)
		f.fel = "Certificada" if f.bfel_status == FEL_CERTIFICADA and f.bfel_uuid else "Pendiente de certificar"

	def total(extra):
		return flt(
			frappe.get_all("Sales Invoice", filters=dict(base, **extra), fields=["sum(grand_total) as t"])[0].t, 2
		)

	por_area = {a: 0.0 for a in ("Arte", "Eventos", "Cafetería")}
	sin_area = 0.0
	for f in facturas:
		if f.galeria_area in por_area:
			por_area[f.galeria_area] = flt(por_area[f.galeria_area] + f.grand_total, 2)
		else:
			sin_area = flt(sin_area + f.grand_total, 2)

	return {
		"desde": desde,
		"hasta": hasta,
		"facturas": facturas,
		"totales": {
			"hoy": total({"posting_date": hoy}),
			"mes": total({"posting_date": ["between", [get_first_day(hoy), hoy]]}),
			"rango": flt(sum(f.grand_total for f in facturas), 2),
			"pendiente_rango": flt(sum(f.outstanding_amount for f in facturas), 2),
			"por_area": por_area,
			"sin_area": sin_area,
		},
	}
