# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Productos de ejemplo para la demo. Idempotente: no duplica ni modifica lo
que ya existe. `bench --site <sitio> execute galeria_arte.setup.demo.cargar_productos`"""

import frappe

UOM = "Unidad(es)"

# (código, nombre, categoría, precio Público, precio Evento)
# Los licores se venden en la misma cafetería, dentro de Bebidas.
PRODUCTOS = [
	("CAF-001", "Café Americano", "Bebidas", 20, 22),
	("CAF-002", "Capuchino", "Bebidas", 28, 30),
	("CAF-003", "Café Latte", "Bebidas", 28, 30),
	("CAF-004", "Limonada Natural", "Bebidas", 22, 25),
	("CAF-005", "Agua Pura", "Bebidas", 10, 12),
	("CAF-006", "Copa de Vino Tinto", "Bebidas", 45, 50),
	("CAF-007", "Cerveza Nacional", "Bebidas", 25, 28),
	("CAF-008", "Cóctel de la Casa", "Bebidas", 50, 55),
	("CAF-009", "Ron Añejo (trago)", "Bebidas", 40, 45),
	("CAF-010", "Cerveza Importada", "Bebidas", 35, 38),
	("CAF-011", "Copa de Vino Blanco", "Bebidas", 45, 50),
	("COM-001", "Sándwich de Pollo", "Comida", 55, 60),
	("COM-002", "Tabla de Quesos y Carnes Frías", "Comida", 125, 140),
	("COM-003", "Bruschettas (3 unidades)", "Comida", 45, 50),
	("COM-004", "Quesadilla", "Comida", 40, 45),
	("POS-001", "Pastel de Chocolate", "Postres", 35, 38),
	("POS-002", "Cheesecake de Frutos Rojos", "Postres", 38, 42),
	("POS-003", "Brownie con Helado", "Postres", 32, 35),
	("OBRA-PRUEBA", "Obra de prueba - Paisaje al óleo", "Obras de Arte", 11200, 11200),
]


def cargar_productos():
	conf = frappe.get_single("Configuracion Galeria")
	listas = (conf.lista_precios_publico, conf.lista_precios_evento)
	creados = 0
	for codigo, nombre, grupo, *precios in PRODUCTOS:
		if not frappe.db.exists("Item", codigo):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": codigo,
					"item_name": nombre,
					"description": nombre,
					"item_group": grupo,
					"stock_uom": UOM,
					"is_stock_item": 0,
					"is_sales_item": 1,
					"is_purchase_item": 0,
					"include_item_in_manufacturing": 0,
				}
			).insert(ignore_permissions=True)
			creados += 1
		for lista, precio in zip(listas, precios):
			if not lista or precio is None:
				continue
			if frappe.db.exists("Item Price", {"item_code": codigo, "price_list": lista}):
				continue
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": codigo, "price_list": lista, "price_list_rate": precio}
			).insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"Productos creados: {creados} de {len(PRODUCTOS)}")
