# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe

from galeria_arte.setup.install import crear_planes_cuotas


def execute():
	"""Las cuotas se calculan sobre el saldo después del anticipo: la primera
	vence un mes después de la factura (antes vencía el mismo día). Agrega el
	plan de 9 cuotas."""
	for plantilla in frappe.get_all(
		"Payment Terms Template", filters={"template_name": ["like", "Galería % cuotas"]}, pluck="name"
	):
		for fila in frappe.get_all(
			"Payment Terms Template Detail",
			filters={"parent": plantilla, "parenttype": "Payment Terms Template"},
			fields=["name", "idx"],
		):
			frappe.db.set_value(
				"Payment Terms Template Detail", fila.name, "credit_days", 30 * fila.idx, update_modified=False
			)
	crear_planes_cuotas()
