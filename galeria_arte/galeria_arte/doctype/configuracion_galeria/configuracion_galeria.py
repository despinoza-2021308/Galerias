# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ConfiguracionGaleria(Document):
	def validate(self):
		self.serie_factura = (self.serie_factura or "").strip()
		opciones = (frappe.get_meta("Sales Invoice").get_field("naming_series").options or "").split("\n")
		if self.serie_factura not in [o.strip() for o in opciones]:
			frappe.throw(
				_("La serie '{0}' no existe en las series de Factura de Venta (Document Naming Settings).").format(
					self.serie_factura
				)
			)
