# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from galeria_arte.api.facturacion import _prefijo_serie, get_config

# De dónde viene el dinero del día (en este orden se muestra).
CAFETERIA = "Cafetería"
OBRAS = "Obras de arte"
BOLETOS = "Eventos – boletos"
ALQUILERES = "Eventos – alquileres"
OTROS = "Otros cobros"
PAGOS_ARTISTAS = "Pagos a artistas"
ORIGENES = (CAFETERIA, OBRAS, BOLETOS, ALQUILERES, OTROS)
GRUPO_BOLETOS = "Boletos de Evento"


class CierredeCaja(Document):
	def validate(self):
		self.company = self.company or get_config().company
		self.validar_duplicado()
		self.calcular()

	def validar_duplicado(self):
		existente = frappe.db.exists(
			"Cierre de Caja",
			{
				"company": self.company,
				"fecha": self.fecha,
				"cajero": self.cajero,
				"docstatus": ["<", 2],
				"name": ["!=", self.name],
			},
		)
		if existente:
			frappe.throw(_("Ya existe el cierre {0} para {1} en esta fecha.").format(existente, self.cajero))

	@frappe.whitelist()
	def calcular(self):
		"""Recalcula lo esperado desde los pagos y facturas del día. Conserva
		lo contado que el cajero ya haya ingresado."""
		# Lo que el cajero ya escribió: el efectivo siempre, y tarjeta o transferencia
		# solo si las corrigió a mano (si no, se vuelven a llenar con lo registrado).
		contado = {p.modo_pago: flt(p.contado) for p in self.pagos if p.es_efectivo or p.contado_manual}
		manual = {p.modo_pago for p in self.pagos if p.contado_manual}

		facturas = frappe.db.sql(
			"""
			SELECT COUNT(*) AS num, COALESCE(SUM(grand_total), 0) AS total,
				COALESCE(SUM(outstanding_amount), 0) AS pendiente
			FROM `tabSales Invoice`
			WHERE company = %(company)s AND posting_date = %(fecha)s AND owner = %(cajero)s
				AND docstatus = 1 AND is_return = 0 AND name LIKE %(prefijo)s
			""",
			{
				"company": self.company,
				"fecha": self.fecha,
				"cajero": self.cajero,
				"prefijo": _prefijo_serie(get_config().serie_factura) + "%",
			},
			as_dict=True,
		)[0]
		self.num_facturas = facturas.num
		self.total_facturado = facturas.total
		self.ventas_pendientes = facturas.pendiente

		movimientos = frappe.db.sql(
			"""
			SELECT mode_of_payment AS modo_pago, payment_type AS tipo, COUNT(*) AS num, SUM(paid_amount) AS monto
			FROM `tabPayment Entry`
			WHERE company = %(company)s AND posting_date = %(fecha)s AND owner = %(cajero)s
				AND docstatus = 1 AND payment_type IN ('Receive', 'Pay') AND galeria_pago = 1
			GROUP BY mode_of_payment, payment_type
			""",
			{"company": self.company, "fecha": self.fecha, "cajero": self.cajero},
			as_dict=True,
		)
		modos = {}
		for m in movimientos:
			fila = modos.setdefault(m.modo_pago, frappe._dict(num=0, ingresos=0.0, egresos=0.0))
			if m.tipo == "Receive":
				fila.ingresos += flt(m.monto)
				fila.num += m.num
			else:  # pagos a artistas
				fila.egresos += flt(m.monto)
		# Formas de pago con monto contado pero sin movimientos también se muestran.
		for modo in contado:
			modos.setdefault(modo, frappe._dict(num=0, ingresos=0.0, egresos=0.0))

		self.set("pagos", [])
		for modo in sorted(modos, key=lambda m: (not es_efectivo(m), m or "")):
			fila = modos[modo]
			esperado = flt(fila.ingresos - fila.egresos, 2)
			efectivo = es_efectivo(modo)
			# El efectivo se cuenta a mano; tarjeta, transferencia y cheque se llenan
			# con lo registrado y el cajero solo los corrige si no coinciden.
			valor = contado.get(modo, 0) if (efectivo or modo in manual) else esperado
			self.append(
				"pagos",
				{
					"modo_pago": modo,
					"num_pagos": fila.num,
					"ingresos": flt(fila.ingresos, 2),
					"egresos": flt(fila.egresos, 2),
					"esperado": esperado,
					"contado": valor,
					"diferencia": flt(valor - esperado, 2),
					"es_efectivo": 1 if efectivo else 0,
					"contado_manual": 1 if modo in manual else 0,
				},
			)

		self.calcular_origenes()
		self.total_cobrado = flt(sum(flt(p.ingresos) for p in self.pagos), 2)
		self.total_pagos_artistas = flt(sum(flt(p.egresos) for p in self.pagos), 2)
		self.total_esperado = flt(sum(flt(p.esperado) for p in self.pagos), 2)
		self.total_contado = flt(sum(flt(p.contado) for p in self.pagos), 2)
		self.diferencia = flt(self.total_contado - self.total_esperado, 2)


	def calcular_origenes(self):
		"""Cada pago del día se asigna a su área: por el anticipo de una obra o
		de un alquiler, o por el área de la factura que paga."""
		filtros = {"company": self.company, "fecha": self.fecha, "cajero": self.cajero}
		pagos = frappe.db.sql(
			"""
			SELECT name, payment_type, mode_of_payment, paid_amount, galeria_obra, galeria_reservacion,
				galeria_evento, galeria_liquidacion
			FROM `tabPayment Entry`
			WHERE company = %(company)s AND posting_date = %(fecha)s AND owner = %(cajero)s
				AND docstatus = 1 AND payment_type IN ('Receive', 'Pay') AND galeria_pago = 1
			""",
			filtros,
			as_dict=True,
		)
		facturas = {}
		if pagos:
			for r in frappe.db.sql(
				"""
				SELECT per.parent, si.galeria_area, si.galeria_evento
				FROM `tabPayment Entry Reference` per
				JOIN `tabSales Invoice` si ON si.name = per.reference_name
				WHERE per.reference_doctype = 'Sales Invoice' AND per.parent IN %(pagos)s
				""",
				{"pagos": tuple(p.name for p in pagos)},
				as_dict=True,
			):
				facturas.setdefault(r.parent, r)
		eventos = {p.galeria_evento for p in pagos if p.galeria_evento} | {
			f.galeria_evento for f in facturas.values() if f.galeria_evento
		}
		tipos = (
			dict(frappe.get_all("Evento", filters={"name": ["in", list(eventos)]}, fields=["name", "tipo"], as_list=True))
			if eventos
			else {}
		)

		def origen(p):
			if p.payment_type == "Pay":
				return PAGOS_ARTISTAS
			if p.galeria_obra or p.galeria_reservacion:
				return OBRAS
			evento = p.galeria_evento
			f = facturas.get(p.name)
			if f and f.galeria_area == "Cafetería":
				return CAFETERIA
			if f and f.galeria_area == "Arte":
				return OBRAS
			if f and f.galeria_area == "Eventos":
				evento = evento or f.galeria_evento
			if evento:
				return BOLETOS if tipos.get(evento) == "Cena" else ALQUILERES
			return OTROS

		grupos = {}
		for p in pagos:
			clave = (p.mode_of_payment, origen(p))
			g = grupos.setdefault(clave, frappe._dict(num=0, monto=0.0))
			g.num += 1
			g.monto += flt(p.paid_amount)
		orden = {o: i for i, o in enumerate(ORIGENES + (PAGOS_ARTISTAS,))}
		self.set("origenes", [])
		for (modo, org), g in sorted(grupos.items(), key=lambda x: (not es_efectivo(x[0][0]), x[0][0] or "", orden.get(x[0][1], 99))):
			self.append(
				"origenes",
				{
					"modo_pago": modo,
					"origen": org,
					"num_pagos": g.num,
					"monto": flt(g.monto, 2),
					"es_egreso": 1 if org == PAGOS_ARTISTAS else 0,
				},
			)

		self.boletos_vendidos = int(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(sii.qty), 0) FROM `tabSales Invoice Item` sii
				JOIN `tabSales Invoice` si ON si.name = sii.parent
				WHERE si.company = %(company)s AND si.posting_date = %(fecha)s AND si.owner = %(cajero)s
					AND si.docstatus = 1 AND si.is_return = 0 AND sii.item_group = %(grupo)s
				""",
				dict(filtros, grupo=GRUPO_BOLETOS),
			)[0][0]
			or 0
		)


def es_efectivo(modo_pago: str | None) -> bool:
	"""Formas de pago de tipo Caja (efectivo): son las que se cuentan en el cajón."""
	return bool(modo_pago) and frappe.get_cached_value("Mode of Payment", modo_pago, "type") == "Cash"
