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
		self.whatsapp = normalizar_whatsapp(self.whatsapp)


def normalizar_whatsapp(numero: str | None) -> str | None:
	"""Deja solo los dígitos (como los pide wa.me). Un número de 8 dígitos es de
	Guatemala: se le antepone 502. Si ya trae código de país, se respeta."""
	digitos = "".join(c for c in (numero or "") if c.isdigit())
	if digitos.startswith("00"):
		digitos = digitos[2:]
	if len(digitos) == 8:
		digitos = "502" + digitos
	return digitos or None
