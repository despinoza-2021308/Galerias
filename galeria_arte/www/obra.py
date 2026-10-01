# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Página pública de una obra: la que abre el QR de su ficha.
Solo muestra datos públicos (nunca el monto del artista, el cliente ni la factura)."""

import frappe
from frappe.utils import fmt_money, sanitize_html

from galeria_arte.utils import nombre_galeria, url_obra

no_cache = 1

ESTADOS = {
	"Disponible": ("Disponible", "disponible"),
	"Reservada": ("Reservada", "reservada"),
	"En subasta": ("En subasta", "subasta"),
	"Vendida": ("Vendida", "vendida"),
	"Devuelta al artista": ("No disponible", "vendida"),
}


def _publica(url: str | None) -> str | None:
	return url if url and url.startswith("/files/") else None


def get_context(context):
	codigo = (frappe.form_dict.get("c") or "").strip()
	nombre = frappe.db.get_value("Obra de Arte", {"codigo_publico": codigo}, "name") if codigo else None
	if not nombre:
		raise frappe.PageDoesNotExistError
	o = frappe.get_doc("Obra de Arte", nombre)
	moneda = frappe.db.get_value("Company", o.company, "default_currency") or "GTQ"
	estado, clase = ESTADOS.get(o.estado, (o.estado, "vendida"))
	medidas = " × ".join(str(int(m) if float(m).is_integer() else m) for m in (o.alto_cm, o.ancho_cm) if m)

	artista = frappe.db.get_value(
		"Artista", o.artista, ["nombre", "nacionalidad", "biografia", "foto"], as_dict=True
	) or frappe._dict(nombre=o.artista)
	otras = frappe.get_all(
		"Obra de Arte",
		filters={"artista": o.artista, "estado": "Disponible", "name": ["!=", o.name], "codigo_publico": ["is", "set"]},
		fields=["titulo", "tecnica", "imagen", "precio_venta", "codigo_publico"],
		order_by="precio_venta desc",
		limit=6,
	)
	for x in otras:
		x.imagen = _publica(x.imagen)
		x.precio = fmt_money(x.precio_venta, currency=moneda)
		x.url = url_obra(x.codigo_publico)

	context.galeria = nombre_galeria()
	context.obra = frappe._dict(
		titulo=o.titulo,
		artista=o.artista,
		tecnica=o.tecnica,
		anio=o.anio,
		medidas=f"{medidas} cm" if medidas else "",
		descripcion=o.descripcion,
		precio=fmt_money(o.precio_venta, currency=moneda),
		estado=estado,
		clase_estado=clase,
		fotos=[u for u in [_publica(o.imagen)] + [_publica(f.imagen) for f in o.fotos] if u],
		iniciales="".join(p[0] for p in (o.titulo or "?").split() if len(p) > 2)[:2].upper() or "?",
	)
	context.artista = frappe._dict(
		nombre=artista.nombre,
		nacionalidad=artista.nacionalidad,
		biografia=sanitize_html(artista.biografia or ""),
		foto=_publica(artista.foto),
	)
	context.otras = otras
	context.title = f"{o.titulo} — {o.artista}"
	context.no_breadcrumbs = 1
	context.show_sidebar = 0
	return context
