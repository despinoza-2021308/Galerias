# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Página pública de un boleto (la que abre el QR o el enlace del correo)."""

import frappe

from galeria_arte.api.boletos import datos_boleto

no_cache = 1


def get_context(context):
	codigo = (frappe.form_dict.get("c") or "").strip()
	nombre = frappe.db.get_value("Boleto", {"codigo": codigo}, "name") if codigo else None
	if not nombre:
		raise frappe.PageDoesNotExistError
	context.b = datos_boleto(nombre)
	context.title = f"{context.b.evento} — {context.b.asistente}"
	context.metatags = {
		"og:type": "website",
		"og:title": f"Boleto · {context.b.evento}",
		"og:description": f"{context.b.asistente} · {context.b.fecha}, {context.b.hora} · {context.b.lugar}",
		"og:image": context.b.qr_url,
		"og:url": context.b.url,
		"description": f"{context.b.asistente} · {context.b.fecha}, {context.b.hora} · {context.b.lugar}",
	}
	context.no_breadcrumbs = 1
	return context
