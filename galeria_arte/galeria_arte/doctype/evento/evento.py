# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, format_datetime, get_datetime, getdate, nowdate

from galeria_arte.api.facturacion import _listas_precios, get_config
from galeria_arte.galeria_arte.doctype.obra_de_arte.obra_de_arte import DISPONIBLE, EN_SUBASTA

EXPOSICION = "Exposición"
CENA = "Cena"
SUBASTA = "Subasta"
ALQUILER = "Alquiler"

# Todos los tipos ocupan su sala: dos eventos no pueden coincidir en la misma sala.
BLOQUEAN_SALA = (EXPOSICION, CENA, SUBASTA, ALQUILER)
INACTIVOS = ("Cancelado", "Vencido")

GRUPO_BOLETOS = "Boletos de Evento"

# Subastas: cada obra termina Adjudicada (el comprador paga al contado en
# DIAS_PAGO_SUBASTA días), Pagada (con su factura), No vendida o Vencida
# (ganó y no pagó a tiempo).
PENDIENTE = "Pendiente"
ADJUDICADA = "Adjudicada"
PAGADA = "Pagada"
NO_VENDIDA = "No vendida"
VENCIDA = "Vencida"
DIAS_PAGO_SUBASTA = 7
UOM = "Unidad(es)"


class Evento(Document):
	def validate(self):
		conf = get_config()
		self.company = self.company or conf.company
		if get_datetime(self.fin) <= get_datetime(self.inicio):
			frappe.throw(_("La hora de fin debe ser posterior a la de inicio."))
		if self.todo_el_espacio:
			self.sala = None
		elif not self.sala:
			frappe.throw(_("Elija la sala o marque Todo el espacio."))

		if self.is_new():
			# Frappe llena el Select con su primera opción: el estado inicial depende del tipo.
			self.estado = "Tentativo" if self.tipo == ALQUILER else "Planificado"
		if self.tipo == ALQUILER and self.estado == "Tentativo" and not self.vence_tentativa:
			dias = int(conf.dias_vencimiento_reserva or 7)
			# El apartado nunca dura más allá del día del evento.
			self.vence_tentativa = min(getdate(add_days(nowdate(), dias)), getdate(self.inicio))

		if self.tipo == CENA:
			self.validar_cena()
		if self.tipo == ALQUILER:
			self.validar_alquiler(conf)
		if self.tipo == SUBASTA:
			self.validar_subasta()
		elif self.lotes:
			frappe.throw(_("Quite las obras a subastar antes de cambiar el tipo de evento."))
		self.validar_choque()

	def validar_cena(self):
		if int(self.cupo or 0) <= 0:
			frappe.throw(_("Indique el cupo de la cena."))
		if flt(self.precio_boleto) <= 0:
			frappe.throw(_("Indique el precio del boleto."))
		self.lugares_vendidos = sum(int(a.lugares or 0) for a in self.asistentes)
		if int(self.cupo) < self.lugares_vendidos:
			frappe.throw(
				_("El cupo no puede ser menor que los lugares ya vendidos ({0}).").format(self.lugares_vendidos)
			)
		capacidad = self.capacidad_sala()
		if capacidad and int(self.cupo) > capacidad:
			frappe.msgprint(
				_("El cupo ({0}) supera la capacidad de la sala ({1}).").format(self.cupo, capacidad),
				indicator="orange",
				alert=True,
			)

	def validar_alquiler(self, conf):
		if not self.cliente:
			frappe.throw(_("Indique el cliente que alquila el espacio."))
		if not flt(self.precio_alquiler):
			self.precio_alquiler = precio_alquiler_base(self.sala, self.todo_el_espacio)
		total = flt(flt(self.precio_alquiler) + sum(flt(c.monto) for c in self.cargos), 2)
		abonado = flt(sum(flt(a.monto) for a in self.abonos), 2)
		if self.factura and flt(self.total_alquiler) and total != flt(self.total_alquiler):
			frappe.throw(_("El alquiler ya se facturó; no se puede cambiar el total."))
		if total < abonado:
			frappe.throw(_("El total del alquiler (Q{0}) no puede ser menor que lo ya abonado (Q{1}).").format(total, abonado))
		self.total_alquiler = total
		self.total_abonado = abonado
		self.saldo = flt(total - abonado, 2)

	def validar_subasta(self):
		antes = self.get_doc_before_save()
		previos = {l.name: l for l in antes.lotes} if antes else {}
		antes_de_la_subasta = self.estado in ("Planificado", "Publicado")
		vistas = set()
		for l in self.lotes:
			prev = previos.get(l.name)
			if l.obra in vistas:
				frappe.throw(_("La obra {0} está repetida en la subasta.").format(l.titulo or l.obra))
			vistas.add(l.obra)
			if not prev or prev.obra != l.obra:
				if prev and prev.resultado != PENDIENTE:
					frappe.throw(_("La obra {0} ya tiene resultado; no se puede cambiar.").format(prev.titulo or prev.obra))
				if not antes_de_la_subasta:
					frappe.throw(_("Las obras se agregan antes de la subasta (estado: {0}).").format(self.estado))
				obra = frappe.db.get_value(
					"Obra de Arte", l.obra, ["titulo", "estado", "subasta", "precio_venta"], as_dict=True
				)
				if not (obra.estado == DISPONIBLE or (obra.estado == EN_SUBASTA and obra.subasta == self.name)):
					frappe.throw(
						_("La obra {0} no está disponible para subastar (estado: {1}).").format(obra.titulo, obra.estado)
					)
				if not flt(l.precio_inicial):
					l.precio_inicial = obra.precio_venta
			if flt(l.precio_inicial) <= 0:
				frappe.throw(_("Indique el precio inicial de {0}.").format(l.titulo or l.obra))
			self.calcular_resultado(l, prev)

		actuales = {l.name for l in self.lotes}
		self._obras_quitadas = []
		for nombre, prev in previos.items():
			if nombre in actuales:
				continue
			if prev.resultado != PENDIENTE or not antes_de_la_subasta:
				frappe.throw(_("La obra {0} ya se subastó; no se puede quitar.").format(prev.titulo or prev.obra))
			self._obras_quitadas.append(prev.obra)

	def calcular_resultado(self, l, prev):
		"""El estado de cada obra sale de lo que se registró al terminar la subasta.
		Pagada y Vencida solo las pone el sistema (cobro y plazo vencido)."""
		anterior = prev.resultado if prev else PENDIENTE
		if anterior in (PAGADA, VENCIDA) or l.resultado in (PAGADA, VENCIDA):
			if l.resultado != anterior and not self.flags.galeria_resultado_sistema:
				frappe.throw(_("El estado de {0} no se puede cambiar a mano.").format(l.titulo or l.obra))
			if l.resultado in (PAGADA, VENCIDA) and prev and not self.flags.galeria_resultado_sistema:
				# Lo cobrado o vencido queda como registro: no se edita.
				l.precio_ganador, l.comprador, l.sin_venta = prev.precio_ganador, prev.comprador, prev.sin_venta
			return

		if self.estado != "Realizado":
			if flt(l.precio_ganador) or l.comprador or l.sin_venta:
				frappe.throw(_("El precio ganador se registra cuando la subasta se marca como realizada."))
			l.resultado = PENDIENTE
			l.fecha_limite_pago = None
			return

		if l.sin_venta:
			l.precio_ganador = 0
			l.comprador = None
			l.resultado = NO_VENDIDA
			l.fecha_limite_pago = None
		elif flt(l.precio_ganador) or l.comprador:
			nombre = l.titulo or l.obra
			if flt(l.precio_ganador) <= 0 or not l.comprador:
				frappe.throw(_("Indique el precio ganador y el comprador de {0}.").format(nombre))
			if flt(l.precio_ganador) < flt(l.precio_inicial):
				frappe.throw(
					_("El precio ganador de {0} (Q{1}) no puede ser menor que el inicial (Q{2}).").format(
						nombre, flt(l.precio_ganador, 2), flt(l.precio_inicial, 2)
					)
				)
			l.resultado = ADJUDICADA
			if not l.fecha_limite_pago:
				l.fecha_limite_pago = add_days(getdate(self.fin), DIAS_PAGO_SUBASTA)
		else:
			l.resultado = PENDIENTE
			l.fecha_limite_pago = None
		if not l.comprador:
			l.comprador_nombre = None

		# Una obra que se dio por no vendida ya volvió al catálogo: para
		# adjudicarla después tiene que seguir libre.
		if anterior == NO_VENDIDA and l.resultado != NO_VENDIDA:
			obra = frappe.db.get_value("Obra de Arte", l.obra, ["titulo", "estado", "subasta"], as_dict=True)
			if not (obra.estado == DISPONIBLE or (obra.estado == EN_SUBASTA and obra.subasta == self.name)):
				frappe.throw(_("La obra {0} ya no está disponible (estado: {1}).").format(obra.titulo, obra.estado))

	def capacidad_sala(self) -> int:
		if self.todo_el_espacio:
			return sum(int(c or 0) for c in frappe.get_all("Sala", filters={"activa": 1}, pluck="capacidad"))
		return int(frappe.db.get_value("Sala", self.sala, "capacidad") or 0)

	def validar_choque(self):
		if self.tipo not in BLOQUEAN_SALA or self.estado in INACTIVOS:
			return
		choque = frappe.db.sql(
			"""
			SELECT name, nombre, sala, todo_el_espacio, inicio, fin FROM `tabEvento`
			WHERE name != %(name)s AND tipo IN %(tipos)s AND estado NOT IN %(inactivos)s
				AND inicio < %(fin)s AND fin > %(inicio)s
				AND (todo_el_espacio = 1 OR %(todo)s = 1 OR sala = %(sala)s)
			ORDER BY inicio LIMIT 1
			""",
			{
				"name": self.name or "",
				"tipos": BLOQUEAN_SALA,
				"inactivos": INACTIVOS,
				"inicio": self.inicio,
				"fin": self.fin,
				"todo": 1 if self.todo_el_espacio else 0,
				"sala": self.sala or "",
			},
			as_dict=True,
		)
		if choque:
			c = choque[0]
			lugar = _("todo el espacio") if c.todo_el_espacio else c.sala
			# Si termina otro día (p. ej. una exposición), se muestra también la fecha de fin.
			formato_fin = "HH:mm" if getdate(c.inicio) == getdate(c.fin) else "dd-MM-yyyy HH:mm"
			frappe.throw(
				_("Choque de horario: {0} ya está ocupado por {1} ({2}) de {3} a {4}.").format(
					lugar, c.nombre, c.name, format_datetime(c.inicio, "dd-MM-yyyy HH:mm"), format_datetime(c.fin, formato_fin)
				),
				title=_("Sala ocupada"),
			)

	def on_update(self):
		if self.tipo == CENA:
			self.sincronizar_boleto()
		if self.tipo == SUBASTA:
			self.sincronizar_obras_subasta()

	def sincronizar_obras_subasta(self):
		"""Las obras quedan En subasta (nadie más las puede vender ni reservar)
		mientras estén pendientes o adjudicadas; si no se venden, si el ganador
		no paga o si se cancela la subasta, vuelven a Disponible."""
		activa = self.estado not in INACTIVOS
		for l in self.lotes:
			if activa and l.resultado in (PENDIENTE, ADJUDICADA):
				apartar_obra(l.obra, self.name)
			elif l.resultado != PAGADA:
				liberar_obra(l.obra, self.name)
			if l.resultado == ADJUDICADA and l.comprador:
				marcar_coleccionista(l.comprador)
		for obra in getattr(self, "_obras_quitadas", None) or []:
			liberar_obra(obra, self.name)

	def sincronizar_boleto(self):
		"""Producto del boleto de la cena, con su precio en las listas de la galería."""
		nombre = f"Boleto - {self.nombre}"[:140]
		if not self.articulo_boleto or not frappe.db.exists("Item", self.articulo_boleto):
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"BOL-{self.name}",
					"item_name": nombre,
					"description": nombre,
					"item_group": GRUPO_BOLETOS,
					"stock_uom": UOM,
					"is_stock_item": 0,
					"is_sales_item": 1,
					"is_purchase_item": 0,
					"include_item_in_manufacturing": 0,
				}
			).insert(ignore_permissions=True)
			self.db_set("articulo_boleto", item.name, update_modified=False)
		elif frappe.db.get_value("Item", self.articulo_boleto, "item_name") != nombre:
			frappe.db.set_value("Item", self.articulo_boleto, {"item_name": nombre, "description": nombre})
		for lista in _listas_precios(get_config()):
			existente = frappe.db.get_value("Item Price", {"item_code": self.articulo_boleto, "price_list": lista}, "name")
			if not existente:
				frappe.get_doc(
					{
						"doctype": "Item Price",
						"item_code": self.articulo_boleto,
						"price_list": lista,
						"price_list_rate": self.precio_boleto,
					}
				).insert(ignore_permissions=True)
			elif flt(frappe.db.get_value("Item Price", existente, "price_list_rate")) != flt(self.precio_boleto):
				frappe.db.set_value("Item Price", existente, "price_list_rate", self.precio_boleto)

	def on_trash(self):
		if self.asistentes or self.abonos or self.factura:
			frappe.throw(_("El evento tiene boletos, abonos o factura; cancélelo en lugar de eliminarlo."))
		if any(l.resultado != PENDIENTE for l in self.lotes):
			frappe.throw(_("La subasta ya tiene resultados; cancélela en lugar de eliminarla."))
		for l in self.lotes:
			liberar_obra(l.obra, self.name)


def precio_alquiler_base(sala: str | None, todo_el_espacio: int = 0) -> float:
	if todo_el_espacio:
		return flt(frappe.db.get_single_value("Configuracion Galeria", "precio_alquiler_todo"))
	return flt(frappe.db.get_value("Sala", sala, "precio_alquiler")) if sala else 0.0


def apartar_obra(obra: str, subasta: str):
	if frappe.db.get_value("Obra de Arte", obra, "estado") == DISPONIBLE:
		frappe.db.set_value("Obra de Arte", obra, {"estado": EN_SUBASTA, "subasta": subasta})


def liberar_obra(obra: str, subasta: str):
	if frappe.db.get_value("Obra de Arte", obra, ["estado", "subasta"]) == (EN_SUBASTA, subasta):
		frappe.db.set_value("Obra de Arte", obra, {"estado": DISPONIBLE, "subasta": None})


def marcar_coleccionista(cliente: str):
	"""Quien gana una subasta queda registrado como coleccionista (salvo empresas)."""
	if frappe.db.get_value("Customer", cliente, "galeria_tipo_cliente") in (None, "", "Público"):
		frappe.db.set_value("Customer", cliente, "galeria_tipo_cliente", "Coleccionista", update_modified=False)
