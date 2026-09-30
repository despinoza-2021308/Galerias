# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

GRUPO_PROVEEDOR = "Artistas"


class Artista(Document):
	def validate(self):
		self.nombre = (self.nombre or "").strip()

	def after_insert(self):
		self.crear_proveedor()

	def crear_proveedor(self):
		"""Proveedor de ERPNext del artista, para registrarle los pagos."""
		if self.proveedor:
			return
		proveedor = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": self.nombre,
				"supplier_group": asegurar_grupo_proveedor(),
				"supplier_type": "Individual",
			}
		).insert(ignore_permissions=True)
		self.db_set("proveedor", proveedor.name)

	@frappe.whitelist()
	def resumen(self) -> dict:
		filas = frappe.get_all(
			"Obra de Arte",
			filters={"artista": self.name},
			fields=["estado", "count(name) as cantidad"],
			group_by="estado",
		)
		return {f.estado: f.cantidad for f in filas}


def asegurar_grupo_proveedor() -> str:
	if not frappe.db.exists("Supplier Group", GRUPO_PROVEEDOR):
		from frappe.utils.nestedset import get_root_of

		frappe.get_doc(
			{
				"doctype": "Supplier Group",
				"supplier_group_name": GRUPO_PROVEEDOR,
				"parent_supplier_group": get_root_of("Supplier Group"),
			}
		).insert(ignore_permissions=True)
	return GRUPO_PROVEEDOR
