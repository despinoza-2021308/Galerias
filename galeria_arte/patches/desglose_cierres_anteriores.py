import frappe


def execute():
	"""Los cierres hechos antes del desglose por origen lo reciben ahora
	(se calcula con los mismos pagos del día; no cambia ningún total)."""
	for nombre in frappe.get_all("Cierre de Caja", filters={"docstatus": ["<", 2]}, pluck="name"):
		if frappe.db.exists("Cierre de Caja Origen", {"parent": nombre, "parenttype": "Cierre de Caja"}):
			continue
		c = frappe.get_doc("Cierre de Caja", nombre)
		c.calcular_origenes()
		for i, fila in enumerate(c.origenes, 1):
			fila.parent, fila.parenttype, fila.parentfield, fila.idx = c.name, "Cierre de Caja", "origenes", i
			fila.docstatus = c.docstatus
			fila.db_insert()
		frappe.db.set_value("Cierre de Caja", nombre, "boletos_vendidos", c.boletos_vendidos, update_modified=False)
