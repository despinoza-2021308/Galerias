# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Configuración inicial de la galería. Idempotente: se puede volver a correr
con `bench --site <sitio> execute galeria_arte.setup.install.configurar`."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils.nestedset import get_root_of

from galeria_arte.galeria_arte.doctype.artista.artista import asegurar_grupo_proveedor

SERIE_FACTURA = "GAL-.#####"
PLANTILLA_IVA = "IVA 12% Incluido"
CONSUMIDOR_FINAL = "Consumidor Final"

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
}

SALAS = [
	{"nombre_sala": "Sala Principal", "capacidad": 120, "color": "#4F46E5"},
	{"nombre_sala": "Terraza", "capacidad": 60, "color": "#0D9488"},
	{"nombre_sala": "Salón Privado", "capacidad": 20, "color": "#B45309"},
]

# Planes de pago en cuotas mensuales sobre el saldo después del anticipo; la
# primera cuota vence un mes después de la factura.
PLANES_CUOTAS = [3, 6, 9, 12]

AREAS = ["Arte", "Eventos", "Cafetería"]

CAMPOS_PERSONALIZADOS = {
	"Sales Invoice": [
		{
			"fieldname": "galeria_area",
			"label": "Área de la galería",
			"fieldtype": "Select",
			"options": "\n" + "\n".join(AREAS),
			# Antes del cliente: Brainfel inserta una sección de exportación oculta
			# justo después de "customer" que escondería el campo.
			"insert_after": "bfel_carga_masiva",
			"depends_on": "eval:(doc.naming_series || '').startsWith('GAL-') || (doc.name || '').startsWith('GAL-')",
			"in_standard_filter": 1,
			"allow_on_submit": 0,
			"translatable": 0,
		},
		{
			"fieldname": "galeria_reservacion",
			"label": "Reservación de obra",
			"fieldtype": "Link",
			"options": "Reservacion de Obra",
			"insert_after": "galeria_area",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "eval:doc.galeria_reservacion",
		},
	],
	"Payment Entry": [
		{
			"fieldname": "galeria_pago",
			"label": "Pago de la galería",
			"fieldtype": "Check",
			"insert_after": "mode_of_payment",
			"read_only": 1,
			"description": "Se marca solo cuando el pago corresponde a una factura o anticipo de la galería.",
		},
		{
			"fieldname": "galeria_obra",
			"label": "Obra reservada",
			"fieldtype": "Link",
			"options": "Obra de Arte",
			"insert_after": "galeria_pago",
			"read_only": 1,
			"depends_on": "eval:doc.galeria_obra",
		},
		{
			"fieldname": "galeria_reservacion",
			"label": "Reservación",
			"fieldtype": "Link",
			"options": "Reservacion de Obra",
			"insert_after": "galeria_obra",
			"read_only": 1,
			"depends_on": "eval:doc.galeria_reservacion",
		},
	],
	"Sales Invoice Item": [
		{
			"fieldname": "galeria_obra",
			"label": "Obra de arte",
			"fieldtype": "Link",
			"options": "Obra de Arte",
			"insert_after": "item_name",
			"read_only": 1,
			"depends_on": "eval:doc.galeria_obra",
		},
		{
			"fieldname": "galeria_monto_artista",
			"label": "Monto para el artista",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"insert_after": "galeria_obra",
			"depends_on": "eval:doc.galeria_obra",
			"description": "Queda congelado en la factura al venderse la obra.",
			"no_copy": 1,
		},
	],
	# En una pestaña propia al final: Brainfel oculta secciones del formulario.
	"Customer": [
		{
			"fieldname": "galeria_tab",
			"label": "Galería",
			"fieldtype": "Tab Break",
			"insert_after": "portal_users",
		},
		{
			"fieldname": "galeria_tipo_cliente",
			"label": "Tipo de cliente",
			"fieldtype": "Select",
			"options": "\nPúblico\nColeccionista\nEmpresa",
			"insert_after": "galeria_tab",
			"in_standard_filter": 1,
			"translatable": 0,
		},
		{
			"fieldname": "galeria_artistas_interes",
			"label": "Artistas de interés",
			"fieldtype": "Table MultiSelect",
			"options": "Cliente Artista Interes",
			"insert_after": "galeria_tipo_cliente",
		},
	],
}


def after_install():
	configurar()


def after_migrate():
	crear_campos_personalizados()


def configurar():
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw("No hay ninguna empresa creada; cree una antes de configurar la galería.")
	currency = frappe.db.get_value("Company", company, "default_currency")

	crear_campos_personalizados()
	crear_grupos_articulo()
	listas = crear_listas_precios(currency)
	agregar_serie_factura()
	plantilla = crear_plantilla_iva(company)
	crear_planes_cuotas()
	crear_salas()
	asegurar_grupo_proveedor()
	configurar_galeria(company, listas, plantilla)
	frappe.db.commit()


def crear_campos_personalizados():
	create_custom_fields(CAMPOS_PERSONALIZADOS, update=True)


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


def crear_plantilla_iva(company):
	"""Plantilla propia de la galería: precios al público con IVA incluido.
	No modifica la plantilla existente de la empresa."""
	abbr = frappe.db.get_value("Company", company, "abbr")
	nombre = f"{PLANTILLA_IVA} - {abbr}"
	if frappe.db.exists("Sales Taxes and Charges Template", nombre):
		return nombre
	cuenta_iva = frappe.db.get_value(
		"Sales Taxes and Charges",
		{"parenttype": "Sales Taxes and Charges Template", "rate": 12, "account_head": ["like", "%IVA%"]},
		"account_head",
	) or frappe.db.get_value("Account", {"company": company, "account_type": "Tax", "is_group": 0}, "name")
	if not cuenta_iva:
		frappe.throw(f"No se encontró la cuenta de IVA de {company}.")
	frappe.get_doc(
		{
			"doctype": "Sales Taxes and Charges Template",
			"title": PLANTILLA_IVA,
			"company": company,
			"taxes": [
				{
					"charge_type": "On Net Total",
					"account_head": cuenta_iva,
					"description": "IVA 12%",
					"rate": 12,
					"included_in_print_rate": 1,
				}
			],
		}
	).insert(ignore_permissions=True)
	return nombre


def crear_planes_cuotas():
	for n in range(1, max(PLANES_CUOTAS) + 1):
		nombre = f"Cuota {n}"
		if not frappe.db.exists("Payment Term", nombre):
			frappe.get_doc(
				{
					"doctype": "Payment Term",
					"payment_term_name": nombre,
					"due_date_based_on": "Day(s) after invoice date",
				}
			).insert(ignore_permissions=True)

	for cuotas in PLANES_CUOTAS:
		nombre = f"Galería {cuotas} cuotas"
		if frappe.db.exists("Payment Terms Template", nombre):
			continue
		# Porciones con 2 decimales que suman exactamente 100.
		base = round(100 / cuotas, 2)
		porciones = [base] * cuotas
		porciones[0] = round(100 - base * (cuotas - 1), 2)
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": nombre,
				"allocate_payment_based_on_payment_terms": 1,
				"terms": [
					{
						"payment_term": f"Cuota {i + 1}",
						"description": f"Cuota {i + 1} de {cuotas}",
						"invoice_portion": porcion,
						"due_date_based_on": "Day(s) after invoice date",
						"credit_days": 30 * (i + 1),
					}
					for i, porcion in enumerate(porciones)
				],
			}
		).insert(ignore_permissions=True)


def crear_salas():
	for sala in SALAS:
		if frappe.db.exists("Sala", sala["nombre_sala"]):
			continue
		frappe.get_doc({"doctype": "Sala", "activa": 1, **sala}).insert(ignore_permissions=True)


def configurar_galeria(company, listas, plantilla):
	conf = frappe.get_single("Configuracion Galeria")
	conf.company = conf.company or company
	conf.serie_factura = conf.serie_factura or SERIE_FACTURA
	conf.plantilla_impuestos = conf.plantilla_impuestos or plantilla
	if not conf.cliente_consumidor_final and frappe.db.exists("Customer", CONSUMIDOR_FINAL):
		conf.cliente_consumidor_final = CONSUMIDOR_FINAL
	for campo, lista in listas.items():
		if not conf.get(campo):
			conf.set(campo, lista)
	if not conf.dias_vencimiento_reserva:
		conf.dias_vencimiento_reserva = 7
	conf.save(ignore_permissions=True)
