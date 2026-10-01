# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

VALIDO = "Válido"
USADO = "Usado"
ANULADO = "Anulado"


class Boleto(Document):
	def validate(self):
		self.codigo = self.codigo or frappe.generate_hash(length=16)
		self.asistente = (self.asistente or "").strip()
		self.correo = (self.correo or "").strip() or None
