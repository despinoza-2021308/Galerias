# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe

LISTA = "Happy Hour"


def execute():
	"""La galería no tiene bar: se elimina la lista de precios Happy Hour.
	Quedan Público y Evento."""
	frappe.db.delete("Singles", {"doctype": "Configuracion Galeria", "field": "lista_precios_happy_hour"})
	if not frappe.db.exists("Price List", LISTA):
		return
	# Si alguna factura la usó, solo se deshabilita para no romper el historial.
	if frappe.db.exists("Sales Invoice", {"selling_price_list": LISTA}):
		frappe.db.set_value("Price List", LISTA, "enabled", 0)
		return
	for precio in frappe.get_all("Item Price", filters={"price_list": LISTA}, pluck="name"):
		frappe.delete_doc("Item Price", precio, force=1, ignore_permissions=True)
	frappe.delete_doc("Price List", LISTA, force=1, ignore_permissions=True)
