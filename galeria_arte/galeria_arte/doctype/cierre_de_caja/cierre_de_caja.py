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
		contado = {p.modo_pago: flt(p.contado) for p in self.pagos}

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

		pagos = frappe.db.sql(
			"""
			SELECT mode_of_payment AS modo_pago, COUNT(*) AS num, SUM(paid_amount) AS monto
			FROM `tabPayment Entry`
			WHERE company = %(company)s AND posting_date = %(fecha)s AND owner = %(cajero)s
				AND docstatus = 1 AND payment_type = 'Receive' AND galeria_pago = 1
			GROUP BY mode_of_payment
			ORDER BY mode_of_payment
			""",
			{"company": self.company, "fecha": self.fecha, "cajero": self.cajero},
			as_dict=True,
		)
		modos = {p.modo_pago: p for p in pagos}
		# Formas de pago con monto contado pero sin pagos registrados también se muestran.
		for modo in contado:
			modos.setdefault(modo, frappe._dict(modo_pago=modo, num=0, monto=0))

		self.set("pagos", [])
		for modo in sorted(modos, key=lambda m: m or ""):
			p = modos[modo]
			self.append(
				"pagos",
				{
					"modo_pago": p.modo_pago,
					"num_pagos": p.num,
					"esperado": flt(p.monto, 2),
					"contado": contado.get(modo, 0),
					"diferencia": flt(contado.get(modo, 0) - flt(p.monto), 2),
				},
			)

		self.total_esperado = flt(sum(flt(p.esperado) for p in self.pagos), 2)
		self.total_contado = flt(sum(flt(p.contado) for p in self.pagos), 2)
		self.diferencia = flt(self.total_contado - self.total_esperado, 2)
