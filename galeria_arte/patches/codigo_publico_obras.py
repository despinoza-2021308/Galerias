import frappe


def execute():
	"""Cada obra necesita su código para la página pública del QR."""
	for nombre in frappe.get_all("Obra de Arte", filters={"codigo_publico": ["is", "not set"]}, pluck="name"):
		frappe.db.set_value(
			"Obra de Arte", nombre, "codigo_publico", frappe.generate_hash(length=12), update_modified=False
		)
