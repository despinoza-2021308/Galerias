# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from galeria_arte.api.facturacion import get_config


class ReservaciondeObra(Document):
	"""Reserva de una obra de arte. Se crea y se mueve desde Venta de Obras
	(galeria_arte.api.arte); aquí solo se mantienen los totales."""

	def validate(self):
		self.company = self.company or get_config().company
		if self.is_new():
			self.precio_obra = frappe.db.get_value("Obra de Arte", self.obra, "precio_venta")
			otra = frappe.db.exists(
				"Reservacion de Obra", {"obra": self.obra, "estado": "Activa", "name": ["!=", self.name]}
			)
			if otra:
				frappe.throw(_("La obra ya tiene la reservación activa {0}.").format(otra))
		self.total_abonado = flt(sum(flt(a.monto) for a in self.abonos), 2)
		self.saldo_obra = flt(flt(self.precio_obra) - self.total_abonado, 2)

	def on_trash(self):
		if self.abonos:
			frappe.throw(_("La reservación tiene abonos registrados; cancélela en lugar de eliminarla."))
