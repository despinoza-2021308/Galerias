# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Boletos de las cenas: uno por lugar, con el nombre del asistente y un QR.

- Se crean al vender (eventos.vender_boletos).
- Página pública /boleto?c=<código> y QR en imagen para los correos.
- El comprador recibe un correo con todos sus boletos y cada asistente con
  correo recibe el suyo.
- En la puerta, el check-in lee el QR y marca el boleto como Usado.
- Si se anula la factura o se cancela la cena, los boletos quedan Anulados.
"""

import io

import frappe
from frappe import _
from frappe.utils import format_datetime, get_datetime, getdate, now_datetime, nowdate

from galeria_arte.api.facturacion import _cargar
from galeria_arte.galeria_arte.doctype.boleto.boleto import ANULADO, USADO, VALIDO
from galeria_arte.utils import nombre_galeria, qr_data_uri, url_boleto

PLANTILLA = "galeria_arte/templates/includes/boleto.html"
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


# ---------------------------------------------------------------------------
# Crear y anular
# ---------------------------------------------------------------------------


def crear_boletos(ev, factura: str, comprador: str, asistentes: list) -> list:
	nombres = []
	for a in asistentes:
		b = frappe.get_doc(
			{
				"doctype": "Boleto",
				"evento": ev.name,
				"asistente": a["nombre"],
				"correo": a.get("correo"),
				"comprador": comprador,
				"factura": factura,
				"estado": VALIDO,
			}
		).insert(ignore_permissions=True)
		nombres.append(b.name)
	return nombres


def anular_boletos(filtros: dict):
	for nombre in frappe.get_all("Boleto", filters={**filtros, "estado": VALIDO}, pluck="name"):
		frappe.db.set_value("Boleto", nombre, "estado", ANULADO)


# ---------------------------------------------------------------------------
# Datos para la página, la impresión y el correo
# ---------------------------------------------------------------------------


def _fecha_larga(fecha) -> str:
	d = get_datetime(fecha)
	return f"{DIAS[d.weekday()].capitalize()} {d.day} de {MESES[d.month - 1]} de {d.year}"


def datos_boleto(boleto) -> dict:
	b = boleto if not isinstance(boleto, str) else frappe.get_doc("Boleto", boleto)
	ev = frappe.db.get_value(
		"Evento", b.evento, ["nombre", "inicio", "fin", "sala", "todo_el_espacio", "descripcion", "estado", "imagen"], as_dict=True
	)
	lugar = _("Todo el espacio") if ev.todo_el_espacio else ev.sala
	return frappe._dict(
		name=b.name,
		codigo=b.codigo,
		asistente=b.asistente,
		estado=b.estado,
		ingreso=format_datetime(b.ingreso, "dd-MM-yyyy HH:mm") if b.ingreso else None,
		evento=ev.nombre,
		evento_cancelado=ev.estado == "Cancelado",
		fecha=_fecha_larga(ev.inicio),
		hora=f"{get_datetime(ev.inicio):%H:%M} – {get_datetime(ev.fin):%H:%M}",
		lugar=lugar,
		descripcion=ev.descripcion,
		imagen=ev.imagen if ev.imagen and ev.imagen.startswith("/files/") else None,
		galeria=nombre_galeria(),
		url=url_boleto(b.codigo),
		qr=qr_data_uri(url_boleto(b.codigo)),
		qr_url=frappe.utils.get_url(f"/api/method/galeria_arte.api.boletos.qr?c={b.codigo}"),
	)


@frappe.whitelist(allow_guest=True)
def qr(c: str):
	"""QR del boleto como imagen PNG (los correos no muestran imágenes incrustadas)."""
	import qrcode

	if not c or not frappe.db.exists("Boleto", {"codigo": c}):
		raise frappe.PageDoesNotExistError
	salida = io.BytesIO()
	qrcode.make(url_boleto(c), box_size=10, border=2).save(salida, format="PNG")
	frappe.local.response.filename = "boleto.png"
	frappe.local.response.filecontent = salida.getvalue()
	frappe.local.response.content_type = "image/png"
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "inline"


@frappe.whitelist()
def html_boletos(boletos) -> str:
	"""Página lista para imprimir con los boletos indicados."""
	frappe.has_permission("Boleto", "read", throw=True)
	nombres = [b for b in (_cargar(boletos) or []) if b]
	if not nombres:
		frappe.throw(_("No hay boletos para imprimir."))
	return frappe.render_template(
		"""{% from plantilla import estilos, boleto %}<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Boletos</title>{{ estilos() }}
<style>@page { size: A4; margin: 10mm; } body { margin: 0; padding: 10mm; background: #fff; } @media print { body { padding: 0; } }
.boletos-hoja { display: flex; flex-wrap: wrap; gap: 5mm; }</style></head>
<body><div class="boletos-hoja">{% for b in boletos %}{{ boleto(b) }}{% endfor %}</div>
<script>window.onload = function () { setTimeout(function () { window.print(); }, 300); };</script></body></html>""",
		{"plantilla": PLANTILLA, "boletos": [datos_boleto(b) for b in nombres]},
	)


# ---------------------------------------------------------------------------
# Correo
# ---------------------------------------------------------------------------


def _html_correo(boletos: list, saludo: str) -> str:
	return frappe.render_template(
		"""{% from plantilla import boleto_correo %}
<div style="font-family: Arial, Helvetica, sans-serif; color: #111; max-width: 560px; margin: 0 auto">
	<p style="font-size: 15px">{{ saludo | e }}</p>
	<p style="font-size: 15px">{{ "Aquí están sus boletos. Presente el código QR en la entrada (impreso o en el celular)." if boletos|length > 1 else "Aquí está su boleto. Presente el código QR en la entrada (impreso o en el celular)." }}</p>
	{% for b in boletos %}{{ boleto_correo(b) }}{% endfor %}
	<p style="font-size: 12px; color: #777; margin-top: 24px">{{ boletos[0].galeria | e }}</p>
</div>""",
		{"plantilla": PLANTILLA, "boletos": boletos, "saludo": saludo},
	)


def enviar_correos(boletos: list, correo_comprador: str | None = None) -> list:
	"""El comprador recibe todos los boletos; cada asistente con correo, el suyo.
	Quedan en la cola de correos de Frappe (se envían cuando haya cuenta de salida)."""
	docs = [frappe.get_doc("Boleto", b) for b in boletos]
	docs = [b for b in docs if b.estado == VALIDO]
	if not docs:
		return []
	datos = {b.name: datos_boleto(b) for b in docs}
	evento = datos[docs[0].name].evento
	envios = []
	if correo_comprador:
		comprador = frappe.db.get_value("Customer", docs[0].comprador, "customer_name") if docs[0].comprador else ""
		envios.append((correo_comprador, [datos[b.name] for b in docs], _("Hola {0}:").format(comprador) if comprador else _("Hola:")))
	for b in docs:
		if b.correo and b.correo.lower() != (correo_comprador or "").lower():
			envios.append((b.correo, [datos[b.name]], _("Hola {0}:").format(b.asistente)))
	enviados = []
	for destinatario, lista, saludo in envios:
		frappe.sendmail(
			recipients=[destinatario],
			subject=_("Sus boletos: {0}").format(evento) if len(lista) > 1 else _("Su boleto: {0}").format(evento),
			message=_html_correo(lista, saludo),
			reference_doctype="Evento",
			reference_name=docs[0].evento,
			delayed=True,
		)
		enviados.append(destinatario)
	for b in docs:
		frappe.db.set_value("Boleto", b.name, "correo_enviado", 1, update_modified=False)
	return enviados


@frappe.whitelist()
def enviar(boletos, correo: str | None = None) -> dict:
	frappe.has_permission("Boleto", "write", throw=True)
	nombres = [b for b in (_cargar(boletos) or []) if b]
	enviados = enviar_correos(nombres, (correo or "").strip() or None)
	return {"enviados": enviados, "hay_cuenta": hay_cuenta_de_correo()}


def hay_cuenta_de_correo() -> bool:
	"""¿Los correos salen de verdad? (cuenta real con contraseña y envío no suspendido)."""
	from frappe.utils import cint

	cuenta = frappe.db.get_value(
		"Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "awaiting_password", as_dict=True
	)
	return bool(cuenta and not cuenta.awaiting_password and not cint(frappe.db.get_default("suspend_email_queue")))


# ---------------------------------------------------------------------------
# Check-in en la puerta
# ---------------------------------------------------------------------------


def _codigo(texto: str) -> str:
	"""Acepta el código solo o la dirección completa del QR (/boleto?c=...)."""
	texto = (texto or "").strip()
	if "c=" in texto:
		texto = texto.split("c=", 1)[1].split("&", 1)[0]
	return texto


@frappe.whitelist()
def cenas_para_checkin() -> list:
	frappe.has_permission("Boleto", "read", throw=True)
	hoy = getdate(nowdate())
	return frappe.get_all(
		"Evento",
		filters={"tipo": "Cena", "estado": ["in", ["Publicado", "Realizado"]], "inicio": [">=", f"{frappe.utils.add_days(hoy, -1)} 00:00:00"]},
		fields=["name", "nombre", "inicio", "sala", "cupo", "lugares_vendidos"],
		order_by="inicio asc",
		limit=20,
	)


@frappe.whitelist()
def estado_checkin(evento: str) -> dict:
	frappe.has_permission("Boleto", "read", throw=True)
	conteo = {
		f.estado: f.n
		for f in frappe.get_all("Boleto", filters={"evento": evento}, fields=["estado", "count(name) as n"], group_by="estado")
	}
	recientes = frappe.get_all(
		"Boleto",
		filters={"evento": evento, "estado": USADO},
		fields=["asistente", "ingreso"],
		order_by="ingreso desc",
		limit=8,
	)
	ev = frappe.db.get_value("Evento", evento, ["nombre", "inicio", "fin", "sala", "todo_el_espacio"], as_dict=True)
	return {
		"evento": evento,
		"nombre": ev.nombre,
		"inicio": ev.inicio,
		"fin": ev.fin,
		"lugar": _("Todo el espacio") if ev.todo_el_espacio else ev.sala,
		"llegaron": conteo.get(USADO, 0),
		"total": conteo.get(USADO, 0) + conteo.get(VALIDO, 0),
		"recientes": recientes,
	}


@frappe.whitelist()
def registrar_ingreso(codigo: str, evento: str | None = None) -> dict:
	"""Marca el boleto como Usado. Responde ok=False con el motivo si no puede entrar."""
	frappe.has_permission("Boleto", "write", throw=True)
	nombre = frappe.db.get_value("Boleto", {"codigo": _codigo(codigo)}, "name")
	if not nombre:
		return {"ok": False, "motivo": _("Código no válido: este boleto no existe.")}
	b = frappe.get_doc("Boleto", nombre)
	info = {"boleto": b.name, "asistente": b.asistente, "evento": b.nombre_evento}
	if evento and b.evento != evento:
		return {**info, "ok": False, "motivo": _("Este boleto es de otro evento: {0}.").format(b.nombre_evento)}
	if b.estado == ANULADO:
		return {**info, "ok": False, "motivo": _("Boleto anulado.")}
	if b.estado == USADO:
		return {
			**info,
			"ok": False,
			"motivo": _("Este boleto ya se usó a las {0}.").format(format_datetime(b.ingreso, "HH:mm")),
		}
	b.estado = USADO
	b.ingreso = now_datetime()
	b.registrado_por = frappe.session.user
	b.save(ignore_permissions=True)
	return {**info, "ok": True}
