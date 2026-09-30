# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from galeria_arte.api.facturacion import get_config


class LiquidacionaArtista(Document):
	"""Pago a un artista por sus obras vendidas. Se crea, se paga y se anula
	desde Pagos a Artistas (galeria_arte.api.liquidaciones)."""

	def validate(self):
		self.company = self.company or get_config().company
		self.proveedor = self.proveedor or frappe.db.get_value("Artista", self.artista, "proveedor")
		self.total = flt(sum(flt(o.monto_artista) for o in self.obras), 2)

	def on_trash(self):
		if self.estado != "Anulada" and (self.factura_compra or self.pago):
			frappe.throw(_("La liquidación tiene documentos contables; anúlela en lugar de eliminarla."))
