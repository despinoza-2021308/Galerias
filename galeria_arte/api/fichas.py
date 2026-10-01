# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Fichas (cédulas) de las obras con QR a su página pública."""

import frappe
from frappe import _
from frappe.utils import fmt_money

from galeria_arte.api.facturacion import _cargar
from galeria_arte.utils import nombre_galeria, qr_data_uri, url_obra

PLANTILLA = "galeria_arte/templates/includes/ficha_obra.html"


def datos_ficha(obra: str) -> dict:
	"""Lo que muestra la ficha impresa (también se usa desde el formato de impresión)."""
	o = frappe.get_doc("Obra de Arte", obra)
	if not o.codigo_publico:
		o.db_set("codigo_publico", frappe.generate_hash(length=12), update_modified=False)
	medidas = " × ".join(str(int(m) if float(m).is_integer() else m) for m in (o.alto_cm, o.ancho_cm) if m)
	moneda = frappe.db.get_value("Company", o.company, "default_currency") or "GTQ"
	return {
		"titulo": o.titulo,
		"artista": o.artista,
		"tecnica": o.tecnica,
		"anio": o.anio,
		"medidas": f"{medidas} cm" if medidas else "",
		"precio": fmt_money(o.precio_venta, currency=moneda),
		"galeria": nombre_galeria(),
		"qr": qr_data_uri(url_obra(o.codigo_publico)),
		"url": url_obra(o.codigo_publico),
	}


@frappe.whitelist()
def obras_de_exposicion(evento: str) -> list:
	frappe.has_permission("Evento", "read", evento, throw=True)
	return frappe.get_all("Evento Obra", filters={"parent": evento, "parenttype": "Evento"}, pluck="obra", order_by="idx asc")


@frappe.whitelist()
def html_fichas(obras) -> str:
	"""Página lista para imprimir con varias fichas por hoja."""
	frappe.has_permission("Obra de Arte", "read", throw=True)
	obras = [o for o in (_cargar(obras) or []) if o]
	if not obras:
		frappe.throw(_("Elija al menos una obra."))
	fichas = [datos_ficha(o) for o in obras]
	return frappe.render_template(
		"""{% from plantilla import estilos, ficha %}<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Fichas de obras</title>{{ estilos() }}
<style>@page { size: A4; margin: 10mm; } body { margin: 0; padding: 10mm; } @media print { body { padding: 0; } }</style></head>
<body><div class="fichas-hoja">{% for o in fichas %}{{ ficha(o) }}{% endfor %}</div>
<script>window.onload = function () { setTimeout(function () { window.print(); }, 300); };</script></body></html>""",
		{"plantilla": PLANTILLA, "fichas": fichas},
	)
