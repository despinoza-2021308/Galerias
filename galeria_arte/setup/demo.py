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


# ---------------------------------------------------------------------------
# Arte: artistas y obras de ejemplo (ficticios)
# ---------------------------------------------------------------------------

ARTISTAS = [
	("Elena Marroquín", "Guatemala", "Pintora. Paisajes del altiplano en óleo de gran formato."),
	("Tomás Ixcot", "Guatemala", "Escultor y grabador. Trabaja madera, piedra y xilografía."),
	("Lucía Ferrante", "Italia", "Fotógrafa y acuarelista radicada en Antigua Guatemala."),
]

# (título, artista, técnica, año, alto, ancho, profundidad, precio con IVA, monto para el artista)
OBRAS = [
	("Amanecer en Atitlán", "Elena Marroquín", "Óleo sobre lienzo", 2024, 90, 120, 0, 11200, 6000),
	("Volcán de Agua", "Elena Marroquín", "Óleo sobre lienzo", 2023, 70, 100, 0, 8960, 5000),
	("Mercado de Chichicastenango", "Elena Marroquín", "Acrílico sobre lienzo", 2025, 60, 80, 0, 6720, 3800),
	("Guardián de jade", "Tomás Ixcot", "Escultura en piedra", 2022, 45, 20, 20, 15680, 9000),
	("Raíces", "Tomás Ixcot", "Talla en madera", 2024, 80, 30, 25, 13440, 7500),
	("Tejido I", "Tomás Ixcot", "Xilografía", 2025, 50, 40, 0, 2800, 1500),
	("Calle del Arco", "Lucía Ferrante", "Acuarela", 2025, 40, 30, 0, 3360, 1800),
	("Lluvia en el parque", "Lucía Ferrante", "Fotografía en papel de algodón", 2024, 60, 90, 0, 4480, 2400),
]

OBRA_PRUEBA = "OBRA-PRUEBA"


def cargar_arte():
	"""Artistas y obras de ejemplo. Retira el artículo de prueba anterior si nunca se facturó."""
	quitar_obra_de_prueba()
	artistas = 0
	for nombre, nacionalidad, bio in ARTISTAS:
		if frappe.db.exists("Artista", nombre):
			continue
		frappe.get_doc(
			{"doctype": "Artista", "nombre": nombre, "nacionalidad": nacionalidad, "biografia": bio, "activo": 1}
		).insert(ignore_permissions=True)
		artistas += 1
	obras = 0
	for titulo, artista, tecnica, anio, alto, ancho, prof, precio, monto in OBRAS:
		if frappe.db.exists("Obra de Arte", {"titulo": titulo, "artista": artista}):
			continue
		frappe.get_doc(
			{
				"doctype": "Obra de Arte",
				"titulo": titulo,
				"artista": artista,
				"tecnica": tecnica,
				"anio": anio,
				"alto_cm": alto,
				"ancho_cm": ancho,
				"profundidad_cm": prof,
				"precio_venta": precio,
				"monto_artista": monto,
			}
		).insert(ignore_permissions=True)
		obras += 1
	frappe.db.commit()
	print(f"Artistas creados: {artistas} de {len(ARTISTAS)} · Obras creadas: {obras} de {len(OBRAS)}")


def quitar_obra_de_prueba():
	if not frappe.db.exists("Item", OBRA_PRUEBA):
		return
	if frappe.db.exists("Sales Invoice Item", {"item_code": OBRA_PRUEBA}):
		return  # ya se facturó: se conserva para no romper esa factura
	for precio in frappe.get_all("Item Price", filters={"item_code": OBRA_PRUEBA}, pluck="name"):
		frappe.delete_doc("Item Price", precio, force=1, ignore_permissions=True)
	frappe.delete_doc("Item", OBRA_PRUEBA, force=1, ignore_permissions=True)
