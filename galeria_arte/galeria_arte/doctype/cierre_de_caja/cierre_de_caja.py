# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from galeria_arte.api.facturacion import _prefijo_serie, get_config


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

		self.total_cobrado = flt(sum(flt(p.ingresos) for p in self.pagos), 2)
		self.total_pagos_artistas = flt(sum(flt(p.egresos) for p in self.pagos), 2)
		self.total_esperado = flt(sum(flt(p.esperado) for p in self.pagos), 2)
		self.total_contado = flt(sum(flt(p.contado) for p in self.pagos), 2)
		self.diferencia = flt(self.total_contado - self.total_esperado, 2)


def es_efectivo(modo_pago: str | None) -> bool:
	"""Formas de pago de tipo Caja (efectivo): son las que se cuentan en el cajón."""
	return bool(modo_pago) and frappe.get_cached_value("Mode of Payment", modo_pago, "type") == "Cash"
