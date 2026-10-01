# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from galeria_arte.api.facturacion import _listas_precios, get_config

GRUPO_ARTICULO = "Obras de Arte"
UOM = "Unidad(es)"
IVA = 0.12

DISPONIBLE = "Disponible"
RESERVADA = "Reservada"
EN_SUBASTA = "En subasta"
VENDIDA = "Vendida"
DEVUELTA = "Devuelta al artista"


class ObradeArte(Document):
	def validate(self):
		self.company = self.company or get_config().company
		self.codigo_publico = self.codigo_publico or frappe.generate_hash(length=12)
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
		self.publicar_imagenes()
		self.sincronizar_articulo()

	def publicar_imagenes(self):
		"""Las fotos de la obra se muestran en su página pública: si se subieron
		como privadas, se pasan a públicas y se actualiza su dirección."""
		urls = [self.imagen] + [f.imagen for f in self.fotos]
		privadas = [u for u in urls if u and u.startswith("/private/")]
		cambios = {}
		for url in privadas:
			nombre = frappe.db.get_value("File", {"file_url": url, "is_private": 1}, "name")
			if not nombre:
				continue
			archivo = frappe.get_doc("File", nombre)
			archivo.is_private = 0
			archivo.save(ignore_permissions=True)
			cambios[url] = archivo.file_url
		if not cambios:
			return
		if self.imagen in cambios:
			self.db_set("imagen", cambios[self.imagen], update_modified=False)
		for f in self.fotos:
			if f.imagen in cambios:
				f.db_set("imagen", cambios[f.imagen], update_modified=False)

	def on_trash(self):
		if self.factura:
			frappe.throw(_("La obra ya se vendió en la factura {0}; no se puede eliminar.").format(self.factura))
		if frappe.db.exists("Reservacion de Obra", {"obra": self.name}):
			frappe.throw(_("La obra tiene reservaciones registradas; no se puede eliminar."))
		if frappe.db.exists("Evento Lote", {"obra": self.name}):
			frappe.throw(_("La obra está registrada en una subasta; no se puede eliminar."))
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
