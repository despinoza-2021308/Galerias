# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Demo completa de la galería: 3 meses de operación.

    bench --site <sitio> execute galeria_arte.setup.demo_completa.reiniciar

`limpiar()` borra solo lo de la galería (facturas GAL-, sus pagos, liquidaciones,
reservaciones, eventos, obras, artistas, cierres de caja y los clientes de
prueba/demo). No toca las facturas ni los pagos de FacEx, ni los productos de
la cafetería.

`cargar()` recorre los últimos ~3 meses día por día con las mismas funciones
de la app (POS, venta de obras, cuotas, eventos, subastas, liquidaciones y
cierres de caja). Un "reloj simulado" hace que cada operación quede con la
fecha y hora en que ocurrió. Es reproducible: siempre genera la misma historia
respecto al día en que se carga.
"""

import random
import sys
import time
from datetime import datetime, timedelta

import frappe
import frappe.utils.data
from frappe.utils import add_days, flt, getdate, nowdate

SEMILLA = 2026
DIAS_HISTORIA = 92
EFECTIVO, TARJETA, TRANSFERENCIA, CHEQUE = "Efectivo", "Tarjetas de credito", "Transferencia bancaria", "Cheque"

# Clientes creados durante las pruebas de la galería (solo tienen facturas GAL-).
CLIENTES_DE_PRUEBA = ["Juan Gonzales", "Elmer Jimenez", "David C", "Manuel Garcia"]


# ---------------------------------------------------------------------------
# Reloj simulado
# ---------------------------------------------------------------------------

# Se guarda en una lista para que el parche no se reemplace a sí mismo.
_REAL = [frappe.utils.data.now_datetime]
_AHORA = [None]
_TIC = [0]


def _reloj():
	"""Hora simulada. Avanza un microsegundo en cada consulta: dos guardados
	seguidos del mismo documento nunca tienen la misma marca de tiempo."""
	if not _AHORA[0]:
		return _REAL[0]()
	_TIC[0] += 1
	return _AHORA[0] + timedelta(microseconds=_TIC[0])


def _instalar_reloj() -> list:
	"""Cambia now_datetime en todos los módulos que ya lo importaron; nowdate,
	now, nowtime y getdate() lo usan por dentro."""
	parches = []
	for modulo in list(sys.modules.values()):
		d = getattr(modulo, "__dict__", None)
		if not isinstance(d, dict):
			continue
		for nombre, valor in list(d.items()):
			if valor is _REAL[0]:
				d[nombre] = _reloj
				parches.append((d, nombre))
	return parches


def _quitar_reloj(parches):
	for d, nombre in parches:
		d[nombre] = _REAL[0]
	_AHORA[0] = None


# ---------------------------------------------------------------------------
# Limpieza (solo lo de la galería)
# ---------------------------------------------------------------------------


def _borrar(doctype: str, nombre: str):
	if not frappe.db.exists(doctype, nombre):
		return
	meta = frappe.get_meta(doctype)
	if meta.is_submittable and frappe.db.get_value(doctype, nombre, "docstatus") == 1:
		frappe.db.set_value(doctype, nombre, "docstatus", 2, update_modified=False)
	frappe.delete_doc(
		doctype, nombre, force=1, ignore_permissions=True, ignore_on_trash=True, delete_permanently=True
	)


def limpiar():
	frappe.set_user("Administrator")
	serie = frappe.db.get_single_value("Configuracion Galeria", "serie_factura").split(".")[0]
	facturas = frappe.get_all("Sales Invoice", filters={"name": ["like", f"{serie}%"]}, pluck="name")
	pagos = frappe.db.sql_list(
		"""
		SELECT name FROM `tabPayment Entry`
		WHERE galeria_pago = 1 OR IFNULL(galeria_obra, '') != '' OR IFNULL(galeria_reservacion, '') != ''
			OR IFNULL(galeria_liquidacion, '') != '' OR IFNULL(galeria_evento, '') != ''
			OR name IN (SELECT parent FROM `tabPayment Entry Reference` WHERE reference_name IN %(facturas)s)
		""",
		{"facturas": tuple(facturas) or ("",)},
	)
	compras = frappe.get_all("Purchase Invoice", filters={"galeria_liquidacion": ["is", "set"]}, pluck="name")
	comprobantes = tuple(facturas + pagos + compras) or ("",)

	# Asientos contables de esos documentos (se borran junto con ellos).
	for tabla in ("GL Entry", "Payment Ledger Entry", "Advance Payment Ledger Entry"):
		if frappe.db.table_exists(tabla):
			frappe.db.sql(f"DELETE FROM `tab{tabla}` WHERE voucher_no IN %(c)s", {"c": comprobantes})
	if frappe.db.table_exists("BFEL Log") and frappe.get_meta("BFEL Log").has_field("reference_name"):
		frappe.db.sql("DELETE FROM `tabBFEL Log` WHERE reference_name IN %(c)s", {"c": comprobantes})

	for nombre in pagos:
		_borrar("Payment Entry", nombre)
	for nombre in facturas:
		_borrar("Sales Invoice", nombre)
	for nombre in compras:
		_borrar("Purchase Invoice", nombre)
	for doctype in ("Boleto", "Cierre de Caja", "Liquidacion a Artista", "Reservacion de Obra", "Evento", "Obra de Arte"):
		for nombre in frappe.get_all(doctype, pluck="name"):
			_borrar(doctype, nombre)

	# Artículos de obras y boletos, con sus precios.
	articulos = frappe.get_all(
		"Item", filters={"item_group": ["in", ["Obras de Arte", "Boletos de Evento"]], "name": ["not in", ["LIQ-OBRA"]]}, pluck="name"
	)
	for codigo in articulos:
		frappe.db.delete("Item Price", {"item_code": codigo})
		_borrar("Item", codigo)

	artistas = frappe.get_all("Artista", fields=["name", "proveedor"])
	frappe.db.delete("Cliente Artista Interes", {"artista": ["in", [a.name for a in artistas] or [""]]})
	for a in artistas:
		_borrar("Artista", a.name)
		if a.proveedor and not frappe.db.exists("Purchase Invoice", {"supplier": a.proveedor}):
			frappe.delete_doc("Supplier", a.proveedor, force=1, ignore_permissions=True, delete_permanently=True)

	# Clientes de prueba y de la demo, si ya no tienen ninguna factura.
	for nombre in CLIENTES_DE_PRUEBA + [c[0] for c in CLIENTES]:
		if frappe.db.exists("Customer", nombre) and not frappe.db.exists("Sales Invoice", {"customer": nombre}):
			frappe.delete_doc("Customer", nombre, force=1, ignore_permissions=True, delete_permanently=True)

	anio = getdate(nowdate()).year
	frappe.db.sql(
		"UPDATE `tabSeries` SET current = 0 WHERE name IN %(s)s",
		{"s": (f"{serie}", "OBRA-", "EVT-", "RES-", "LIQ-", "BOL-", f"CIERRE-{anio}-")},
	)
	frappe.db.commit()
	print(
		f"Limpieza: {len(facturas)} facturas, {len(pagos)} pagos, {len(compras)} facturas de compra, "
		f"{len(artistas)} artistas, {len(articulos)} artículos de obras/boletos."
	)


# ---------------------------------------------------------------------------
# Datos de la demo (ficticios)
# ---------------------------------------------------------------------------

ARTISTAS = [
	("Elena Marroquín", "Guatemala", "Pintora. Paisajes del altiplano guatemalteco en óleo de gran formato."),
	("Tomás Ixcot", "Guatemala", "Escultor y grabador de Totonicapán. Trabaja piedra, madera y xilografía."),
	("Lucía Ferrante", "Italia", "Acuarelista y fotógrafa radicada en Antigua Guatemala; retrata su arquitectura colonial."),
	("Andrés Choc", "Guatemala", "Tallador de San Juan Comalapa. Máscaras y figuras en madera policromada."),
	("Mariana Solís", "Guatemala", "Fotógrafa documental. Mercados, oficios y tradiciones de Guatemala."),
	("Rodrigo Batz", "Guatemala", "Pintor abstracto. Técnica mixta, textura y color inspirados en la ciudad."),
	("Sofía Aldana", "México", "Grabadora y serigrafista. Fauna y arte popular mesoamericano."),
	("Daniel Quemé", "Guatemala", "Ceramista. Piezas contemporáneas con técnicas de alfarería tradicional."),
]

# clave: (título, artista, técnica, año, alto, ancho, precio con IVA, monto artista, días desde que ingresó)
OBRAS = {
	"E1": ("Amanecer en Atitlán", "Elena Marroquín", "Óleo sobre lienzo", 2024, 90, 120, 11200, 6000, 95),
	"E2": ("Volcán de Agua", "Elena Marroquín", "Óleo sobre lienzo", 2023, 70, 100, 8960, 5000, 95),
	"E3": ("Lago de fuego", "Elena Marroquín", "Óleo sobre lienzo", 2025, 120, 160, 33600, 18000, 95),
	"E4": ("Neblina en Todos Santos", "Elena Marroquín", "Óleo sobre lienzo", 2024, 80, 100, 12320, 6600, 95),
	"E5": ("Mercado de Chichicastenango", "Elena Marroquín", "Acrílico sobre lienzo", 2025, 60, 80, 6720, 3800, 95),
	"E6": ("Tarde en San Juan", "Elena Marroquín", "Óleo sobre tela", 2025, 40, 50, 4480, 2400, 60),
	"T1": ("Guardián de jade", "Tomás Ixcot", "Escultura en piedra", 2022, 45, 20, 15680, 9000, 94),
	"T2": ("Raíces", "Tomás Ixcot", "Talla en madera", 2024, 80, 30, 13440, 7500, 94),
	"T3": ("Tejido I", "Tomás Ixcot", "Xilografía", 2025, 50, 40, 2800, 1500, 94),
	"T4": ("Tejido II", "Tomás Ixcot", "Xilografía", 2025, 50, 40, 2800, 1500, 40),
	"T5": ("Nahual del maíz", "Tomás Ixcot", "Talla en madera", 2025, 60, 25, 9520, 5200, 35),
	"L1": ("Calle del Arco", "Lucía Ferrante", "Acuarela", 2025, 40, 30, 3360, 1800, 90),
	"L2": ("Lluvia en el parque", "Lucía Ferrante", "Fotografía en papel de algodón", 2024, 60, 90, 4480, 2400, 90),
	"L3": ("Santa Catalina al atardecer", "Lucía Ferrante", "Acuarela", 2025, 35, 50, 3920, 2100, 70),
	"L4": ("Fuente de las Sirenas", "Lucía Ferrante", "Acuarela", 2024, 30, 40, 2940, 1600, 70),
	"A1": ("Máscara del Venado", "Andrés Choc", "Madera policromada", 2024, 40, 25, 7840, 4200, 88),
	"A2": ("Danza de la Conquista", "Andrés Choc", "Madera policromada", 2023, 70, 40, 17920, 9600, 88),
	"A3": ("Máscara del Tigre", "Andrés Choc", "Madera policromada", 2025, 38, 24, 6160, 3300, 88),
	"A4": ("Ceiba", "Andrés Choc", "Talla en madera", 2025, 90, 35, 11760, 6300, 36),
	"M1": ("Manos que tejen", "Mariana Solís", "Fotografía en papel de algodón", 2024, 50, 75, 5040, 2700, 85),
	"M2": ("Mercado de flores", "Mariana Solís", "Fotografía en papel de algodón", 2025, 60, 90, 6720, 3600, 85),
	"M3": ("Procesión", "Mariana Solís", "Fotografía en papel de algodón", 2025, 40, 60, 3920, 2100, 45),
	"M4": ("Retrato de Doña Juana", "Mariana Solís", "Fotografía en papel de algodón", 2023, 50, 50, 4480, 2400, 45),
	"R1": ("Composición en ocre", "Rodrigo Batz", "Técnica mixta sobre lienzo", 2025, 100, 100, 22400, 12000, 80),
	"R2": ("Ritmo urbano", "Rodrigo Batz", "Técnica mixta sobre lienzo", 2024, 80, 120, 11200, 6000, 80),
	"R3": ("Fragmentos", "Rodrigo Batz", "Técnica mixta sobre madera", 2025, 70, 70, 9520, 5100, 80),
	"R4": ("Horizonte azul", "Rodrigo Batz", "Acrílico sobre lienzo", 2025, 60, 90, 7280, 3900, 20),
	"S1": ("Colibríes", "Sofía Aldana", "Serigrafía", 2025, 50, 70, 3360, 1800, 75),
	"S2": ("Alebrije", "Sofía Aldana", "Grabado en linóleo", 2024, 40, 50, 2520, 1350, 75),
	"S3": ("Día de mercado", "Sofía Aldana", "Grabado en linóleo", 2023, 40, 50, 2520, 1350, 75),
	"D1": ("Vasija ceremonial", "Daniel Quemé", "Cerámica de alta temperatura", 2025, 45, 30, 5600, 3000, 80),
	"D2": ("Serie Tierra I", "Daniel Quemé", "Cerámica", 2025, 30, 30, 3080, 1650, 40),
	"D3": ("Serie Tierra II", "Daniel Quemé", "Cerámica", 2025, 30, 30, 3080, 1650, 40),
	"D4": ("Cuenco de obsidiana", "Daniel Quemé", "Cerámica con engobe negro", 2024, 25, 25, 2240, 1200, 40),
}

# (nombre, tipo, artistas de interés)
CLIENTES = [
	("Ana Lucía Castillo", "Coleccionista", ["Elena Marroquín", "Lucía Ferrante"]),
	("Roberto Méndez", "Coleccionista", ["Tomás Ixcot", "Rodrigo Batz"]),
	("Carmen Aguilar", "Coleccionista", ["Elena Marroquín"]),
	("Luis Fernando Arriola", "Coleccionista", ["Rodrigo Batz", "Tomás Ixcot"]),
	("Gabriela Monterroso", "Coleccionista", ["Elena Marroquín", "Mariana Solís"]),
	("Jorge Estrada", "Público", []),
	("Patricia Samayoa", "Público", ["Lucía Ferrante"]),
	("Héctor Villatoro", "Coleccionista", ["Andrés Choc"]),
	("Isabel Cifuentes", "Público", ["Daniel Quemé"]),
	("Fernando Juárez", "Público", ["Rodrigo Batz"]),
	("Claudia Pineda", "Público", ["Lucía Ferrante"]),
	("Ricardo Solórzano", "Coleccionista", ["Elena Marroquín"]),
	("Mónica Barrios", "Público", ["Mariana Solís"]),
	("Pablo Rosales", "Público", ["Mariana Solís"]),
	("Daniela Orellana", "Público", ["Sofía Aldana"]),
	("Sergio Figueroa", "Público", ["Andrés Choc", "Sofía Aldana"]),
	("Marcela Rodríguez", "Público", []),
	("Inversiones Kukulcán, S.A.", "Empresa", []),
	("Consultores Ixchel, S.A.", "Empresa", []),
	("Fundación Arte Vivo", "Empresa", ["Daniel Quemé", "Sofía Aldana"]),
]

# Popularidad de cada producto en la cafetería (0 = nunca se vende en la demo).
POPULARIDAD = {
	"CAF-001": 18, "CAF-002": 16, "CAF-003": 12, "CAF-004": 10, "CAF-005": 8, "CAF-006": 4, "CAF-007": 5,
	"CAF-008": 3, "CAF-009": 0.6, "CAF-010": 0, "CAF-011": 2, "COM-001": 9, "COM-002": 1.5, "COM-003": 4,
	"COM-004": 6, "POS-001": 10, "POS-002": 7, "POS-003": 6,
}
# En las noches de evento se vende más bebida.
POPULARIDAD_EVENTO = {
	"CAF-006": 14, "CAF-011": 8, "CAF-007": 10, "CAF-008": 9, "CAF-009": 3, "CAF-005": 6, "COM-002": 5,
	"COM-003": 7, "POS-001": 4, "POS-002": 3,
}
HORAS = {9: 3, 10: 6, 11: 9, 12: 10, 13: 9, 14: 8, 15: 10, 16: 9, 17: 7, 18: 5, 19: 3}
# Nombres para los asistentes de las cenas (cada boleto lleva el suyo).
NOMBRES = ["Andrea", "Carlos", "Lucía", "Diego", "Valeria", "José", "Sofía", "Javier", "Paola", "Miguel", "Fernanda",
	"Alejandro", "Camila", "Rodrigo", "Natalia", "Esteban", "Mariela", "Óscar", "Alejandra", "Raúl"]
APELLIDOS = ["López", "García", "Morales", "Hernández", "Pérez", "Castillo", "Ramírez", "Cifuentes", "Barrios",
	"Molina", "Ortiz", "Reyes", "Flores", "Juárez", "Méndez", "Rivas"]


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------


class Demo:
	def __init__(self):
		self.rnd = random.Random(SEMILLA)
		self.hoy = getdate(nowdate())
		self.agenda = []
		self.obras = {}  # clave -> name de la Obra
		self.r = {}  # resultados (facturas, reservaciones, eventos)
		self.planes = {
			int(p.split()[1]): p
			for p in frappe.get_all("Payment Terms Template", filters={"name": ["like", "Galería % cuotas"]}, pluck="name")
		}

	# -- utilidades ------------------------------------------------------

	def momento(self, dias: int, hora: str = "10:00") -> datetime:
		h, m = (int(x) for x in hora.split(":"))
		return datetime.combine(add_days(self.hoy, -dias), datetime.min.time()) + timedelta(hours=h, minutes=m)

	def en(self, dias: int, hora: str, accion, texto: str = ""):
		self.agenda.append((self.momento(dias, hora), len(self.agenda), accion, texto))

	def pago(self, modo, monto, referencia=None):
		return {"modo_pago": modo, "monto": flt(monto, 2), "referencia": referencia}

	# -- catálogo --------------------------------------------------------

	def crear_base(self):
		from galeria_arte.setup.demo import cargar_productos

		cargar_productos()
		grupo = frappe.db.get_single_value("Selling Settings", "customer_group") or frappe.db.get_value(
			"Customer Group", {"is_group": 0}, "name"
		)
		territorio = frappe.db.get_single_value("Selling Settings", "territory") or frappe.db.get_value(
			"Territory", {"is_group": 0}, "name"
		)
		for nombre, pais, bio in ARTISTAS:
			frappe.get_doc(
				{"doctype": "Artista", "nombre": nombre, "nacionalidad": pais, "biografia": bio, "activo": 1}
			).insert(ignore_permissions=True)
		for nombre, tipo, intereses in CLIENTES:
			c = frappe.new_doc("Customer")
			c.customer_name = nombre
			c.customer_type = "Company" if tipo == "Empresa" else "Individual"
			c.customer_group = grupo
			c.territory = territorio
			c.tax_id = "CF"
			if c.meta.has_field("bfel_identificacion"):
				c.bfel_identificacion = "CF"
			if c.meta.has_field("bfel_id_receptor"):
				c.bfel_id_receptor = "CF"
			c.galeria_tipo_cliente = tipo
			for a in intereses:
				c.append("galeria_artistas_interes", {"artista": a})
			c.insert(ignore_permissions=True)
			if c.name != nombre:
				frappe.throw(f"El cliente {nombre} se guardó como {c.name}; la demo lo busca por su nombre.")

	def crear_obra(self, clave):
		titulo, artista, tecnica, anio, alto, ancho, precio, monto, dias = OBRAS[clave]
		ingreso = add_days(self.hoy, -dias)
		o = frappe.get_doc(
			{
				"doctype": "Obra de Arte",
				"titulo": titulo,
				"artista": artista,
				"tecnica": tecnica,
				"anio": anio,
				"alto_cm": alto,
				"ancho_cm": ancho,
				"precio_venta": precio,
				"monto_artista": monto,
				"fecha_ingreso": ingreso,
				"fecha_limite_consignacion": add_days(ingreso, 180),
			}
		).insert(ignore_permissions=True)
		self.obras[clave] = o.name

	# -- cafetería -------------------------------------------------------

	def ticket(self, evento=False):
		from galeria_arte.api.pos import vender

		pesos = dict(POPULARIDAD)
		if evento:
			pesos.update(POPULARIDAD_EVENTO)
		codigos = [c for c, p in pesos.items() if p > 0]
		lineas = {}
		for _ in range(self.rnd.choices([1, 2, 3], [50, 35, 15])[0]):
			codigo = self.rnd.choices(codigos, [pesos[c] for c in codigos])[0]
			lineas[codigo] = lineas.get(codigo, 0) + self.rnd.choices([1, 2], [85, 15])[0]
		lista = "Evento" if evento else "Público"
		precios = {
			p.item_code: flt(p.price_list_rate)
			for p in frappe.get_all(
				"Item Price", filters={"price_list": lista, "item_code": ["in", list(lineas)]}, fields=["item_code", "price_list_rate"]
			)
		}
		total = flt(sum(precios[c] * q for c, q in lineas.items()), 2)
		modo = self.rnd.choices([EFECTIVO, TARJETA, TRANSFERENCIA], [50, 42, 8])[0]
		if total >= 150 and self.rnd.random() < 0.12:
			pagos = [self.pago(EFECTIVO, 100), self.pago(TARJETA, total - 100)]
		else:
			pagos = [self.pago(modo, total)]
		cliente = self.rnd.choice(CLIENTES[:16])[0] if self.rnd.random() < 0.1 else None
		vender([{"item_code": c, "qty": q} for c, q in lineas.items()], pagos, cliente=cliente, lista_precios=lista)

	def programar_cafeteria(self, noches_evento: set):
		for dias in range(DIAS_HISTORIA, -1, -1):
			fecha = add_days(self.hoy, -dias)
			if fecha.weekday() == 0:  # lunes cerrado
				continue
			avance = (DIAS_HISTORIA - dias) / DIAS_HISTORIA  # la cafetería crece mes a mes
			base = 14 if fecha.weekday() >= 5 else 7
			cantidad = max(2, round(base * (0.8 + 0.45 * avance) * self.rnd.uniform(0.7, 1.3)))
			horas = self.rnd.choices(list(HORAS), list(HORAS.values()), k=cantidad)
			ahora = _REAL[0]()  # hora real en la zona del sistema
			for h in sorted(horas):
				hora = f"{h}:{self.rnd.randint(0, 59):02d}"
				if dias == 0 and self.momento(0, hora) > ahora:
					continue  # hoy solo hasta la hora actual
				self.en(dias, hora, lambda: self.ticket(), "cafetería")
			if dias in noches_evento:
				for _ in range(self.rnd.randint(6, 12)):
					self.en(dias, f"{self.rnd.choice([19, 20, 21])}:{self.rnd.randint(0, 59):02d}", lambda: self.ticket(True), "cafetería evento")

	# -- arte ------------------------------------------------------------

	def vender_obra(self, clave, cliente, pagos, plan=None, antes_de=None, precio=None):
		from galeria_arte.api.arte import vender

		r = vender(
			self.obras[clave], cliente, precio=precio, plan_pagos=self.planes.get(plan) if plan else None,
			pagos=pagos, pagar_antes_de=str(add_days(self.hoy, -antes_de)) if antes_de is not None else None,
		)
		self.r[clave] = r["factura"]

	def reservar(self, clave, cliente, anticipo, modo, limite):
		from galeria_arte.api.arte import crear_reservacion

		r = crear_reservacion(self.obras[clave], cliente, anticipo, modo, str(add_days(self.hoy, -limite)))
		self.r[f"res-{clave}"] = r["reservacion"]

	def abonar_reserva(self, clave, monto, modo):
		from galeria_arte.api.arte import agregar_abono

		agregar_abono(self.r[f"res-{clave}"], monto, modo)

	def cobrar(self, clave, pagos):
		from galeria_arte.api.facturacion import registrar_pagos

		registrar_pagos(self.r[clave], pagos)

	def cobrar_cuota(self, clave, modo, referencia=None):
		"""Paga exactamente la próxima cuota (su monto real, con los centavos del plan)."""
		from galeria_arte.api.facturacion import estado_factura

		cuota = estado_factura(self.r[clave])["proxima"]
		self.cobrar(clave, [self.pago(modo, cuota["monto"], referencia)])

	def liquidar(self, artista, claves, pagar_con=None):
		from galeria_arte.api.liquidaciones import crear_liquidacion

		crear_liquidacion(artista, [self.obras[c] for c in claves], pagar=1 if pagar_con else 0, modo_pago=pagar_con)

	def programar_arte(self):
		from galeria_arte.api.arte import cancelar_reservacion

		# Ventas al contado
		self.en(80, "11:30", lambda: self.vender_obra("E1", "Ana Lucía Castillo", [self.pago(TARJETA, 11200, "VOU-2231")]))
		self.en(75, "16:10", lambda: self.vender_obra("T3", "Jorge Estrada", [self.pago(EFECTIVO, 2800)]))
		self.en(60, "12:15", lambda: self.vender_obra("L1", "Patricia Samayoa", [self.pago(TARJETA, 3360, "VOU-3102")]))
		self.en(20, "17:40", lambda: self.vender_obra("M1", "Pablo Rosales", [self.pago(TRANSFERENCIA, 5040, "TRF-88120")]))
		self.en(8, "11:05", lambda: self.vender_obra("S2", "Daniela Orellana", [self.pago(TARJETA, 2520, "VOU-4410")]))

		# Reserva que termina en venta al contado
		self.en(70, "15:00", lambda: self.reservar("T2", "Roberto Méndez", 3000, EFECTIVO, 40))
		self.en(55, "10:30", lambda: self.abonar_reserva("T2", 4000, TRANSFERENCIA))
		self.en(45, "16:20", lambda: self.vender_obra("T2", "Roberto Méndez", [self.pago(TARJETA, 6440, "VOU-3877")]))

		# Reserva que termina en venta a 6 cuotas
		self.en(50, "12:00", lambda: self.reservar("R1", "Luis Fernando Arriola", 5000, TRANSFERENCIA, 30))
		self.en(35, "17:00", lambda: self.vender_obra("R1", "Luis Fernando Arriola", [], plan=6))
		self.en(6, "10:15", lambda: self.cobrar_cuota("R1", TRANSFERENCIA, "TRF-90211"))

		# Cuotas: 3 (al día, la próxima vence en 2 días), 12 (una vencida), 9 (primera vencida)
		self.en(88, "13:00", lambda: self.vender_obra("E2", "Carmen Aguilar", [self.pago(EFECTIVO, 2960)], plan=3))
		self.en(57, "11:00", lambda: self.cobrar_cuota("E2", EFECTIVO))
		self.en(27, "11:20", lambda: self.cobrar_cuota("E2", TARJETA, "VOU-4012"))
		self.en(85, "17:30", lambda: self.vender_obra("E3", "Gabriela Monterroso", [self.pago(TRANSFERENCIA, 9600, "TRF-71002")], plan=12))
		self.en(54, "09:45", lambda: self.cobrar_cuota("E3", TRANSFERENCIA, "TRF-80410"))
		self.en(40, "15:30", lambda: self.vender_obra("A2", "Héctor Villatoro", [self.pago(CHEQUE, 4500, "CHQ-001245")], plan=9))

		# Abonos libres: pagada, vencida con saldo y vigente
		self.en(65, "14:00", lambda: self.vender_obra("D1", "Isabel Cifuentes", [self.pago(EFECTIVO, 1600)], antes_de=35))
		self.en(50, "12:30", lambda: self.cobrar("D1", [self.pago(EFECTIVO, 2000)]))
		self.en(38, "16:45", lambda: self.cobrar("D1", [self.pago(TARJETA, 2000, "VOU-3950")]))
		self.en(75, "11:40", lambda: self.vender_obra("R3", "Fernando Juárez", [self.pago(EFECTIVO, 2000)], antes_de=45))
		self.en(60, "15:10", lambda: self.cobrar("R3", [self.pago(TRANSFERENCIA, 3000, "TRF-77301")]))
		self.en(12, "13:20", lambda: self.vender_obra("M2", "Mónica Barrios", [self.pago(TARJETA, 2000, "VOU-4301")], antes_de=-18))
		self.en(3, "10:40", lambda: self.cobrar("M2", [self.pago(EFECTIVO, 1500)]))

		# Reservas: vigente, vencida y cancelada
		self.en(10, "16:00", lambda: self.reservar("L2", "Claudia Pineda", 1000, EFECTIVO, -10))
		self.en(30, "12:40", lambda: self.reservar("E4", "Ricardo Solórzano", 2500, TRANSFERENCIA, 5))
		self.en(62, "11:15", lambda: self.reservar("A3", "Sergio Figueroa", 800, EFECTIVO, 32))
		self.en(48, "10:00", lambda: cancelar_reservacion(self.r["res-A3"], "El cliente desistió de la compra."))

		# Obra devuelta al artista
		self.en(25, "09:30", lambda: frappe.get_doc("Obra de Arte", self.obras["S3"]).devolver_al_artista())

		# Pagos a artistas
		self.en(70, "10:00", lambda: self.liquidar("Elena Marroquín", ["E1"], TRANSFERENCIA))
		self.en(30, "10:00", lambda: self.liquidar("Lucía Ferrante", ["L1"]))
		self.en(20, "10:00", lambda: self.liquidar("Tomás Ixcot", ["T2", "T3"], TRANSFERENCIA))
		self.en(10, "10:00", lambda: self.liquidar("Daniel Quemé", ["D1"], EFECTIVO))

	# -- eventos ---------------------------------------------------------

	def crear_evento(self, clave, datos, obras=None, publicar=True):
		from galeria_arte.api.eventos import crear, publicar as publicar_evento

		r = crear(datos)
		self.r[clave] = r["evento"]
		if obras:
			ev = frappe.get_doc("Evento", r["evento"])
			for o in obras:
				ev.append("obras", {"obra": self.obras[o]})
			ev.save(ignore_permissions=True)
		if publicar and datos["tipo"] != "Alquiler":
			publicar_evento(r["evento"])

	def boletos(self, clave, cantidad):
		from galeria_arte.api.eventos import vender_boletos

		precio = flt(frappe.db.get_value("Evento", self.r[clave], "precio_boleto"))
		total = flt(precio * cantidad, 2)
		modo = self.rnd.choices([EFECTIVO, TARJETA, TRANSFERENCIA], [30, 55, 15])[0]
		cliente = self.rnd.choice(CLIENTES[:16])[0] if self.rnd.random() < 0.6 else None
		asistentes = [{"nombre": cliente}] if cliente else []
		while len(asistentes) < cantidad:
			asistentes.append({"nombre": f"{self.rnd.choice(NOMBRES)} {self.rnd.choice(APELLIDOS)}"})
		vender_boletos(self.r[clave], cantidad, [self.pago(modo, total)], cliente=cliente, asistentes=asistentes)

	def llegaron(self, clave):
		"""Cena pasada: casi todos los asistentes registraron su ingreso en la puerta."""
		inicio = frappe.db.get_value("Evento", self.r[clave], "inicio")
		for nombre in frappe.get_all("Boleto", filters={"evento": self.r[clave], "estado": "Válido"}, pluck="name"):
			if self.rnd.random() < 0.92:
				frappe.db.set_value("Boleto", nombre, {
					"estado": "Usado",
					"ingreso": inicio + timedelta(minutes=self.rnd.randint(-25, 50)),
					"registrado_por": "Administrator",
				}, update_modified=False)

	def vender_cena(self, clave, lugares, desde, hasta):
		"""Reparte los lugares vendidos en compras de 1 a 4 entre dos fechas."""
		restantes = lugares
		while restantes > 0:
			n = min(restantes, self.rnd.choices([1, 2, 3, 4], [20, 50, 15, 15])[0])
			dias = self.rnd.randint(hasta, desde)
			self.en(dias, f"{self.rnd.randint(10, 18)}:{self.rnd.randint(0, 59):02d}", lambda n=n: self.boletos(clave, n), "boletos")
			restantes -= n

	def realizado(self, clave):
		from galeria_arte.api.eventos import marcar_realizado

		marcar_realizado(self.r[clave])

	def fecha(self, dias, hora):
		return self.momento(dias, hora).strftime("%Y-%m-%d %H:%M:%S")

	def programar_eventos(self) -> set:
		from galeria_arte.api.eventos import (
			abonar_alquiler,
			agregar_lote,
			cobrar_subasta,
			confirmar_alquiler,
			registrar_resultado,
			vencer_adjudicaciones,
			vencer_tentativas,
		)

		f = self.fecha
		# Exposiciones en la Sala Principal
		self.en(92, "09:00", lambda: self.crear_evento("expo1", {
			"nombre": "Luces del Altiplano — Elena Marroquín", "tipo": "Exposición", "sala": "Sala Principal",
			"inicio": f(85, "10:00"), "fin": f(50, "18:00"),
			"descripcion": "Paisajes del altiplano guatemalteco en óleo de gran formato.",
		}, obras=["E1", "E2", "E3", "E4", "E5"]))
		self.en(49, "09:00", lambda: self.realizado("expo1"))
		self.en(33, "09:00", lambda: self.crear_evento("expo2", {
			"nombre": "Raíces y Territorio — Tomás Ixcot y Andrés Choc", "tipo": "Exposición", "sala": "Sala Principal",
			"inicio": f(26, "10:00"), "fin": f(-20, "18:00"),
			"descripcion": "Escultura en piedra y madera: la tierra, el maíz y las máscaras de la tradición.",
		}, obras=["T4", "T5", "A3", "A4"]))

		# Cenas: (clave, nombre, días, hora inicio, hora fin, sala, cupo, precio, vendidos, creada, realizada)
		cenas = [
			("cena1", "Cena de Maridaje: Vinos del Mundo", 78, "19:30", "22:30", "Terraza", 40, 350, 34, 92),
			("cena2", "Noche de Jazz y Arte", 58, "19:00", "22:30", "Terraza", 50, 250, 47, 76),
			("cena3", "Cena del Artista con Elena Marroquín", 52, "19:30", "22:00", "Salón Privado", 18, 450, 18, 70),
			("cena4", "Cena de Otoño", 16, "19:30", "22:30", "Terraza", 40, 380, 29, 40),
			("cena5", "Cena de Día de Muertos", -31, "19:00", "22:30", "Terraza", 50, 400, 22, 20),
			("cena6", "Maridaje de Cafés de Altura", -12, "18:00", "20:30", "Salón Privado", 16, 300, 9, 14),
		]
		noches = set()
		for clave, nombre, dias, hi, hf, sala, cupo, precio, vendidos, creada in cenas:
			self.en(creada, "09:15", lambda clave=clave, nombre=nombre, dias=dias, hi=hi, hf=hf, sala=sala, cupo=cupo, precio=precio: self.crear_evento(clave, {
				"nombre": nombre, "tipo": "Cena", "sala": sala, "inicio": f(dias, hi), "fin": f(dias, hf),
				"cupo": cupo, "precio_boleto": precio,
			}))
			self.vender_cena(clave, vendidos, creada - 1, max(dias + 1, 0))
			if dias > 0:
				self.en(dias, "23:00", lambda clave=clave: self.llegaron(clave), "check-in")
				self.en(dias - 1, "09:00", lambda clave=clave: self.realizado(clave))
				noches.add(dias)
		noches.update({85, 26})  # inauguraciones de las exposiciones

		# Alquileres
		self.en(80, "10:30", lambda: self.crear_evento("boda", {
			"nombre": "Boda Rodríguez Pérez", "tipo": "Alquiler", "todo_el_espacio": 1, "cliente": "Marcela Rodríguez",
			"inicio": f(44, "17:00"), "fin": f(44, "23:30"), "descripcion": "Recepción de boda para 150 invitados.",
		}))
		self.en(80, "10:35", lambda: self._cargos("boda", [("Montaje y mobiliario", 2500), ("Personal de seguridad", 800)]))
		self.en(78, "11:00", lambda: confirmar_alquiler(self.r["boda"], 5000, TRANSFERENCIA, "TRF-70011"))
		self.en(60, "11:00", lambda: abonar_alquiler(self.r["boda"], 6000, TRANSFERENCIA, "TRF-77420"))
		self.en(47, "11:00", lambda: abonar_alquiler(self.r["boda"], 6300, CHEQUE, "CHQ-000932"))
		self.en(43, "09:00", lambda: self.realizado("boda"))

		self.en(50, "15:00", lambda: self.crear_evento("kukulcan", {
			"nombre": "Lanzamiento Inversiones Kukulcán", "tipo": "Alquiler", "sala": "Terraza",
			"cliente": "Inversiones Kukulcán, S.A.", "inicio": f(33, "18:00"), "fin": f(33, "22:00"),
		}))
		self.en(50, "15:05", lambda: self._cargos("kukulcan", [("Equipo de sonido e iluminación", 900)]))
		self.en(49, "10:00", lambda: confirmar_alquiler(self.r["kukulcan"], 2000, TRANSFERENCIA, "TRF-81001"))
		self.en(36, "10:00", lambda: abonar_alquiler(self.r["kukulcan"], 3900, TRANSFERENCIA, "TRF-84550"))
		self.en(32, "09:00", lambda: self.realizado("kukulcan"))

		self.en(20, "12:00", lambda: self.crear_evento("ixchel", {
			"nombre": "Taller Consultores Ixchel", "tipo": "Alquiler", "sala": "Salón Privado",
			"cliente": "Consultores Ixchel, S.A.", "inicio": f(9, "08:00"), "fin": f(9, "13:00"),
		}))
		self.en(19, "10:00", lambda: confirmar_alquiler(self.r["ixchel"], 1000, TARJETA, "VOU-4122"))
		self.en(10, "10:00", lambda: abonar_alquiler(self.r["ixchel"], 1500, TRANSFERENCIA, "TRF-90010"))
		self.en(8, "09:00", lambda: self.realizado("ixchel"))

		self.en(12, "14:00", lambda: self.crear_evento("arte_vivo", {
			"nombre": "Aniversario Fundación Arte Vivo", "tipo": "Alquiler", "sala": "Terraza",
			"cliente": "Fundación Arte Vivo", "inicio": f(-18, "18:00"), "fin": f(-18, "23:00"),
		}))
		self.en(12, "14:05", lambda: self._cargos("arte_vivo", [("Coordinación de catering", 1200)]))
		self.en(11, "10:00", lambda: confirmar_alquiler(self.r["arte_vivo"], 2500, TRANSFERENCIA, "TRF-90220"))

		self.en(40, "16:00", lambda: self.crear_evento("reunion", {
			"nombre": "Reunión familiar", "tipo": "Alquiler", "sala": "Salón Privado",
			"cliente": "Héctor Villatoro", "inicio": f(28, "12:00"), "fin": f(28, "16:00"),
		}))
		self.en(32, "00:05", vencer_tentativas)
		self.en(2, "11:00", lambda: self.crear_evento("graduacion", {
			"nombre": "Graduación privada", "tipo": "Alquiler", "sala": "Salón Privado",
			"cliente": "Pablo Rosales", "inicio": f(-25, "19:00"), "fin": f(-25, "23:00"),
		}))

		# Subasta pasada: 2 pagadas, 1 no vendida y 1 ganador que no pagó
		self.en(35, "10:00", lambda: self.crear_evento("subasta1", {
			"nombre": "Subasta de Verano", "tipo": "Subasta", "sala": "Salón Privado",
			"inicio": f(19, "18:00"), "fin": f(19, "21:00"),
			"descripcion": "Subasta en vivo. El ganador paga al contado en 7 días.",
		}, publicar=False))
		for o in ("T1", "R2", "A1", "S1"):
			self.en(35, "10:05", lambda o=o: agregar_lote(self.r["subasta1"], self.obras[o]))
		self.en(34, "09:00", lambda: self._publicar("subasta1"))
		self.en(19, "21:30", lambda: self.realizado("subasta1"))
		resultados = {"T1": ("Luis Fernando Arriola", 19500), "R2": ("Roberto Méndez", 13200), "A1": None, "S1": ("Sergio Figueroa", 4100)}
		for o, res in resultados.items():
			self.en(19, "21:45", lambda o=o, res=res: registrar_resultado(
				self.r["subasta1"], self._lote("subasta1", o), 1 if res else 0, res[1] if res else None, res[0] if res else None
			))
		self.en(15, "11:00", lambda: cobrar_subasta(self.r["subasta1"], self._lote("subasta1", "T1"), [
			self.pago(TARJETA, 10000, "VOU-4380"), self.pago(TRANSFERENCIA, 9500, "TRF-89400")
		]))
		self.en(14, "15:00", lambda: cobrar_subasta(self.r["subasta1"], self._lote("subasta1", "R2"), [
			self.pago(TRANSFERENCIA, 13200, "TRF-89522")
		]))
		self.en(11, "00:05", vencer_adjudicaciones)

		# Subasta próxima
		self.en(6, "10:00", lambda: self.crear_evento("subasta2", {
			"nombre": "Subasta de Otoño", "tipo": "Subasta", "sala": "Salón Privado",
			"inicio": f(-23, "18:00"), "fin": f(-23, "21:00"),
			"descripcion": "Obras de Elena Marroquín, Mariana Solís y Daniel Quemé.",
		}, publicar=False))
		for o in ("E6", "M3", "D2"):
			self.en(6, "10:05", lambda o=o: agregar_lote(self.r["subasta2"], self.obras[o]))
		self.en(5, "09:00", lambda: self._publicar("subasta2"))
		return noches

	def _cargos(self, clave, cargos):
		ev = frappe.get_doc("Evento", self.r[clave])
		for descripcion, monto in cargos:
			ev.append("cargos", {"descripcion": descripcion, "monto": monto})
		ev.save(ignore_permissions=True)

	def _publicar(self, clave):
		from galeria_arte.api.eventos import publicar

		publicar(self.r[clave])

	def _lote(self, clave, obra):
		return frappe.db.get_value(
			"Evento Lote", {"parent": self.r[clave], "parenttype": "Evento", "obra": self.obras[obra]}, "name"
		)

	# -- cierres de caja -------------------------------------------------

	def cierre(self, dias, diferencia=0):
		fecha = add_days(self.hoy, -dias)
		if frappe.db.exists("Cierre de Caja", {"fecha": fecha, "cajero": "Administrator", "docstatus": ["<", 2]}):
			return
		c = frappe.new_doc("Cierre de Caja")
		c.fecha = fecha
		c.cajero = "Administrator"
		c.insert(ignore_permissions=True)
		for p in c.pagos:
			if p.es_efectivo:
				p.contado = flt(p.esperado) + diferencia
		if diferencia:
			c.observaciones = "Diferencia en efectivo revisada con el cajero."
		c.save(ignore_permissions=True)
		c.submit()

	def programar_cierres(self):
		abiertos = [d for d in range(1, 16) if add_days(self.hoy, -d).weekday() != 0][:10]
		for i, dias in enumerate(abiertos):
			diferencia = {2: -20, 6: 10}.get(i, 0)
			self.en(dias, "23:30", lambda dias=dias, diferencia=diferencia: self.cierre(dias, diferencia), "cierre")

	# -- ejecución -------------------------------------------------------

	def programar(self):
		self.en(DIAS_HISTORIA + 4, "09:00", self.crear_base, "artistas y clientes")
		for clave, datos in OBRAS.items():
			self.en(datos[8], "08:30", lambda clave=clave: self.crear_obra(clave), "obra")
		self.programar_arte()
		noches = self.programar_eventos()
		self.programar_cafeteria(noches)
		self.programar_cierres()

	def ejecutar(self):
		self.agenda.sort(key=lambda x: (x[0], x[1]))
		total = len(self.agenda)
		inicio = time.time()
		for i, (cuando, _, accion, texto) in enumerate(self.agenda, 1):
			_AHORA[0] = cuando
			_TIC[0] = 0
			try:
				accion()
			except Exception:
				print(f"Falló el paso {i} ({texto or accion}) del {cuando}")
				raise
			if i % 50 == 0:
				frappe.db.commit()
				print(f"  {i}/{total} pasos · {cuando:%d-%m-%Y} · {time.time() - inicio:.0f}s", flush=True)
		frappe.db.commit()


def cargar():
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	parches = _instalar_reloj()
	try:
		demo = Demo()
		demo.programar()
		print(f"Cargando {len(demo.agenda)} operaciones de {DIAS_HISTORIA} días…", flush=True)
		demo.ejecutar()
	finally:
		_quitar_reloj(parches)
	# Lo que ERPNext hace cada noche: marca Vencidas las facturas con cuotas atrasadas.
	from erpnext.controllers.accounts_controller import update_invoice_status

	update_invoice_status()
	frappe.db.commit()
	print("Demo cargada.")


def reiniciar():
	"""Deja la demo como nueva: limpia lo de la galería y vuelve a cargar."""
	limpiar()
	cargar()
