# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account
from erpnext.accounts.party import get_party_account

from galeria_arte.api.facturacion import _cargar, _listas_precios, crear_factura, get_config

GRUPO_ARTICULO = "Obras de Arte"
UOM = "Unidad(es)"
IVA = 0.12

DISPONIBLE = "Disponible"
RESERVADA = "Reservada"
VENDIDA = "Vendida"
DEVUELTA = "Devuelta al artista"


class ObradeArte(Document):
	def validate(self):
		self.company = self.company or get_config().company
		if flt(self.precio_venta) <= 0:
			frappe.throw(_("El precio de venta debe ser mayor a cero."))
		if flt(self.monto_artista) < 0:
			frappe.throw(_("El monto para el artista no puede ser negativo."))
		self.ganancia_galeria = ganancia(self.precio_venta, self.monto_artista)
		if self.ganancia_galeria < 0:
			frappe.msgprint(
				_("El monto para el artista es mayor que el precio sin IVA: la galería no gana en esta obra."),
				indicator="orange",
				alert=True,
			)

	def on_update(self):
		self.sincronizar_articulo()

	def on_trash(self):
		if self.factura:
			frappe.throw(_("La obra ya se vendió en la factura {0}; no se puede eliminar.").format(self.factura))
		if self.articulo and not frappe.db.exists("Sales Invoice Item", {"item_code": self.articulo}):
			for precio in frappe.get_all("Item Price", filters={"item_code": self.articulo}, pluck="name"):
				frappe.delete_doc("Item Price", precio, force=1, ignore_permissions=True)
			frappe.delete_doc("Item", self.articulo, force=1, ignore_permissions=True)

	# ------------------------------------------------------------------
	# Artículo de ERPNext (para poder facturar la obra)
	# ------------------------------------------------------------------

	def sincronizar_articulo(self):
		nombre = f"{self.titulo} - {self.artista}"[:140]
		if not self.articulo or not frappe.db.exists("Item", self.articulo):
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": self.name,
					"item_name": nombre,
					"description": self.descripcion or nombre,
					"item_group": GRUPO_ARTICULO,
					"stock_uom": UOM,
					"is_stock_item": 0,
					"is_sales_item": 1,
					"is_purchase_item": 0,
					"include_item_in_manufacturing": 0,
					"image": self.imagen,
				}
			).insert(ignore_permissions=True)
			self.db_set("articulo", item.name, update_modified=False)
		else:
			item = frappe.get_doc("Item", self.articulo)
			if item.item_name != nombre or item.image != self.imagen:
				item.item_name = nombre
				item.image = self.imagen
				item.save(ignore_permissions=True)

		if self.estado == VENDIDA:
			return
		for lista in _listas_precios(get_config()):
			existente = frappe.db.get_value("Item Price", {"item_code": self.articulo, "price_list": lista}, "name")
			if not existente:
				frappe.get_doc(
					{
						"doctype": "Item Price",
						"item_code": self.articulo,
						"price_list": lista,
						"price_list_rate": self.precio_venta,
					}
				).insert(ignore_permissions=True)
			elif flt(frappe.db.get_value("Item Price", existente, "price_list_rate")) != flt(self.precio_venta):
				frappe.db.set_value("Item Price", existente, "price_list_rate", self.precio_venta)

	# ------------------------------------------------------------------
	# Reserva
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def reservar(self, cliente: str, anticipo: float, modo_pago: str, fecha_limite: str, referencia: str | None = None):
		"""Aparta la obra con un anticipo del cliente."""
		self.check_permission("write")
		if self.estado != DISPONIBLE:
			frappe.throw(_("Solo se puede reservar una obra Disponible (estado actual: {0}).").format(self.estado))
		anticipo = flt(anticipo)
		if anticipo <= 0:
			frappe.throw(_("La reserva requiere un anticipo mayor a cero."))
		if anticipo > flt(self.precio_venta):
			frappe.throw(_("El anticipo no puede ser mayor que el precio de la obra."))
		if getdate(fecha_limite) < getdate(nowdate()):
			frappe.throw(_("La fecha límite de la reserva no puede ser anterior a hoy."))

		pago = self._crear_anticipo(cliente, anticipo, modo_pago, referencia)
		self.db_set(
			{
				"estado": RESERVADA,
				"reservada_por": cliente,
				"anticipo": anticipo,
				"pago_anticipo": pago,
				"fecha_limite_reserva": fecha_limite,
			}
		)
		return {"pago": pago}

	def _crear_anticipo(self, cliente: str, monto: float, modo_pago: str, referencia: str | None) -> str:
		conf = get_config()
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Receive"
		pe.company = conf.company
		pe.posting_date = nowdate()
		pe.mode_of_payment = modo_pago
		pe.party_type = "Customer"
		pe.party = cliente
		pe.paid_from = get_party_account("Customer", cliente, conf.company)
		pe.paid_to = get_bank_cash_account(modo_pago, conf.company)["account"]
		pe.paid_amount = pe.received_amount = monto
		pe.reference_no = referencia or f"Anticipo {self.name}"
		pe.reference_date = nowdate()
		pe.galeria_pago = 1
		pe.galeria_obra = self.name
		pe.custom_remarks = 1
		pe.remarks = f"Anticipo por reserva de la obra {self.name} - {self.titulo}"
		pe.setup_party_account_field()
		pe.set_missing_values()
		pe.insert()
		pe.submit()
		return pe.name

	@frappe.whitelist()
	def cancelar_reserva(self):
		"""Libera la obra. El anticipo queda como saldo a favor del cliente."""
		self.check_permission("write")
		if self.estado != RESERVADA:
			frappe.throw(_("La obra no está reservada."))
		anticipo, cliente = self.anticipo, self.reservada_por
		self.db_set(
			{
				"estado": DISPONIBLE,
				"reservada_por": None,
				"anticipo": 0,
				"pago_anticipo": None,
				"fecha_limite_reserva": None,
			}
		)
		return {"saldo_a_favor": anticipo, "cliente": cliente}

	# ------------------------------------------------------------------
	# Venta
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def vender(
		self,
		cliente: str,
		precio: float | None = None,
		monto_artista: float | None = None,
		plan_pagos: str | None = None,
		pagos=None,
	):
		"""Factura la obra. El estado Vendida lo pone el hook de la factura."""
		self.check_permission("write")
		if self.estado not in (DISPONIBLE, RESERVADA):
			frappe.throw(_("La obra no se puede vender (estado actual: {0}).").format(self.estado))
		if self.estado == RESERVADA and cliente != self.reservada_por:
			frappe.throw(_("La obra está reservada por {0}.").format(self.reservada_por))

		precio = flt(precio) if precio not in (None, "") else flt(self.precio_venta)
		monto_artista = flt(monto_artista) if monto_artista not in (None, "") else flt(self.monto_artista)
		if precio <= 0:
			frappe.throw(_("El precio de venta debe ser mayor a cero."))
		if monto_artista < 0:
			frappe.throw(_("El monto para el artista no puede ser negativo."))

		anticipos = []
		if self.estado == RESERVADA and self.pago_anticipo:
			pe = frappe.db.get_value(
				"Payment Entry", self.pago_anticipo, ["docstatus", "unallocated_amount"], as_dict=True
			)
			if pe and pe.docstatus == 1 and flt(pe.unallocated_amount) > 0:
				anticipos.append({"pago": self.pago_anticipo, "monto": min(flt(pe.unallocated_amount), precio)})

		return crear_factura(
			items=[
				{"item_code": self.articulo, "qty": 1, "rate": precio, "galeria_monto_artista": monto_artista}
			],
			cliente=cliente,
			area="Arte",
			plan_pagos=plan_pagos or None,
			pagos=_cargar(pagos) or [],
			anticipos=anticipos,
		)

	# ------------------------------------------------------------------
	# Consignación
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def devolver_al_artista(self):
		self.check_permission("write")
		if self.estado != DISPONIBLE:
			frappe.throw(_("Solo se puede devolver una obra Disponible (estado actual: {0}).").format(self.estado))
		self.db_set("estado", DEVUELTA)

	@frappe.whitelist()
	def reingresar(self):
		"""La obra devuelta vuelve a la galería."""
		self.check_permission("write")
		if self.estado != DEVUELTA:
			frappe.throw(_("La obra no está devuelta al artista."))
		self.db_set("estado", DISPONIBLE)


def ganancia(precio_con_iva, monto_artista) -> float:
	"""Ganancia de la galería: precio sin IVA menos lo que recibe el artista."""
	return flt(flt(precio_con_iva) / (1 + IVA) - flt(monto_artista), 2)
