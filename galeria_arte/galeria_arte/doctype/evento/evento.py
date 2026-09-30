# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, format_datetime, get_datetime, getdate, nowdate

from galeria_arte.api.facturacion import _listas_precios, get_config

EXPOSICION = "Exposición"
CENA = "Cena"
SUBASTA = "Subasta"
ALQUILER = "Alquiler"

# Tipos que ocupan la sala: no pueden coincidir entre sí. Las exposiciones no bloquean.
BLOQUEAN_SALA = (CENA, SUBASTA, ALQUILER)
INACTIVOS = ("Cancelado", "Vencido")

GRUPO_BOLETOS = "Boletos de Evento"
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
			frappe.throw(
				_("Choque de horario: {0} ya está ocupado por {1} ({2}) de {3} a {4}.").format(
					lugar, c.nombre, c.name, format_datetime(c.inicio, "dd-MM-yyyy HH:mm"), format_datetime(c.fin, "HH:mm")
				),
				title=_("Sala ocupada"),
			)

	def on_update(self):
		if self.tipo == CENA:
			self.sincronizar_boleto()

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


def precio_alquiler_base(sala: str | None, todo_el_espacio: int = 0) -> float:
	if todo_el_espacio:
		return flt(frappe.db.get_single_value("Configuracion Galeria", "precio_alquiler_todo"))
	return flt(frappe.db.get_value("Sala", sala, "precio_alquiler")) if sala else 0.0
