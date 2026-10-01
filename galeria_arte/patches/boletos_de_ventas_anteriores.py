import frappe


def execute():
	"""Las cenas próximas que ya tenían lugares vendidos reciben sus boletos con QR
	(con el nombre del comprador, porque antes no se pedía el de cada asistente)."""
	if not frappe.db.table_exists("Boleto"):
		return
	from galeria_arte.api.boletos import crear_boletos

	for nombre in frappe.get_all("Evento", filters={"tipo": "Cena", "estado": "Publicado"}, pluck="name"):
		ev = frappe.get_doc("Evento", nombre)
		for a in ev.asistentes:
			if not a.factura or frappe.db.exists("Boleto", {"factura": a.factura}):
				continue
			n = int(a.lugares or 0)
			asistentes = [{"nombre": a.nombre if n == 1 else f"{a.nombre} ({i + 1} de {n})"} for i in range(n)]
			crear_boletos(ev, a.factura, a.cliente, asistentes)
