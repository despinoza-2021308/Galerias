# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Utilidades para los formatos de impresión y las páginas públicas."""

import base64
import io

import frappe
from frappe.utils import get_url


def qr_data_uri(texto: str) -> str:
	"""Código QR en SVG como data URI (nítido al imprimir, sin archivos)."""
	import qrcode
	import qrcode.image.svg

	img = qrcode.make(texto or "", image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
	salida = io.BytesIO()
	img.save(salida)
	return "data:image/svg+xml;base64," + base64.b64encode(salida.getvalue()).decode()


def url_obra(codigo: str) -> str:
	"""Página pública de una obra (la que abre el QR de su ficha)."""
	return get_url(f"/obra?c={codigo}")


def url_boleto(codigo: str) -> str:
	"""Página pública de un boleto."""
	return get_url(f"/boleto?c={codigo}")


def nombre_galeria() -> str:
	conf_company = frappe.db.get_single_value("Configuracion Galeria", "company")
	nombre = frappe.db.get_value("BFEL Settings", {"company": conf_company, "enabled": 1}, "nombrecomercial")
	return nombre or conf_company or "Galería"
