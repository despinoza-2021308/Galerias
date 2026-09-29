# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Configuración inicial de la galería. Idempotente: se puede volver a correr
con `bench --site <sitio> execute galeria_arte.setup.install.configurar`."""

import frappe
from frappe.utils.nestedset import get_root_of

SERIE_FACTURA = "GAL-.#####"

# (nombre, es_grupo, padre); padre None = raíz del árbol de grupos
GRUPOS_ARTICULO = [
	("Obras de Arte", 0, None),
	("Cafetería", 1, None),
	("Bebidas", 0, "Cafetería"),
	("Comida", 0, "Cafetería"),
	("Postres", 0, "Cafetería"),
	("Boletos de Evento", 0, None),
	("Alquiler de Espacio", 0, None),
]

LISTAS_PRECIOS = {
	"lista_precios_publico": "Público",
	"lista_precios_evento": "Evento",
	"lista_precios_happy_hour": "Happy Hour",
}

SALAS = [
	{"nombre_sala": "Sala Principal", "capacidad": 120, "color": "#4F46E5"},
	{"nombre_sala": "Terraza", "capacidad": 60, "color": "#0D9488"},
	{"nombre_sala": "Salón Privado", "capacidad": 20, "color": "#B45309"},
]


def after_install():
	configurar()


def configurar():
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw("No hay ninguna empresa creada; cree una antes de configurar la galería.")
	currency = frappe.db.get_value("Company", company, "default_currency")

	crear_grupos_articulo()
	listas = crear_listas_precios(currency)
	agregar_serie_factura()
	crear_salas()
	configurar_galeria(company, listas)
	frappe.db.commit()


def crear_grupos_articulo():
	raiz = get_root_of("Item Group")
	for nombre, es_grupo, padre in GRUPOS_ARTICULO:
		if frappe.db.exists("Item Group", nombre):
			continue
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": nombre,
				"is_group": es_grupo,
				"parent_item_group": padre or raiz,
			}
		).insert(ignore_permissions=True)


def crear_listas_precios(currency):
	for nombre in LISTAS_PRECIOS.values():
		if frappe.db.exists("Price List", nombre):
			continue
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": nombre,
				"selling": 1,
				"currency": currency,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	return LISTAS_PRECIOS


def agregar_serie_factura():
	opciones = (frappe.get_meta("Sales Invoice").get_field("naming_series").options or "").split("\n")
	opciones = [o.strip() for o in opciones if o.strip()]
	if SERIE_FACTURA in opciones:
		return
	opciones.append(SERIE_FACTURA)
	frappe.make_property_setter(
		{
			"doctype": "Sales Invoice",
			"fieldname": "naming_series",
			"property": "options",
			"value": "\n".join(opciones),
			"property_type": "Text",
		}
	)
	frappe.clear_cache(doctype="Sales Invoice")


def crear_salas():
	for sala in SALAS:
		if frappe.db.exists("Sala", sala["nombre_sala"]):
			continue
		frappe.get_doc({"doctype": "Sala", "activa": 1, **sala}).insert(ignore_permissions=True)


def configurar_galeria(company, listas):
	conf = frappe.get_single("Configuracion Galeria")
	conf.company = conf.company or company
	conf.serie_factura = conf.serie_factura or SERIE_FACTURA
	for campo, lista in listas.items():
		if not conf.get(campo):
			conf.set(campo, lista)
	if not conf.dias_vencimiento_reserva:
		conf.dias_vencimiento_reserva = 7
	conf.save(ignore_permissions=True)
