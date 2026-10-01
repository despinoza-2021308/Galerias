# Copyright (c) 2026, despinoza-2021308 and contributors
# For license information, please see license.txt

"""Cuenta de correo de prueba para los boletos.

    bench --site <sitio> execute galeria_arte.setup.correo.cuenta_de_prueba

Crea la cuenta de salida "Galería - Boletos" en estado "esperando contraseña"
y deja suspendido el envío: los correos se arman y quedan en la cola de correos
(se pueden ver), pero no salen. Para enviar de verdad: poner el correo real y su
contraseña de aplicación en la cuenta y reanudar el envío en la cola de correos.
"""

import frappe

CUENTA = "Galería - Boletos"


def cuenta_de_prueba():
	if frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
		print("Ya hay una cuenta de salida por defecto; no se crea la de prueba.")
		return
	if not frappe.db.exists("Email Account", CUENTA):
		frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": CUENTA,
				"email_id": "boletos@galeria-demo.invalid",
				"smtp_server": "smtp.gmail.com",
				"smtp_port": 587,
				"use_tls": 1,
				"enable_outgoing": 1,
				"default_outgoing": 1,
				"enable_incoming": 0,
				"awaiting_password": 1,
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value("Email Account", CUENTA, {"enable_outgoing": 1, "default_outgoing": 1})
	frappe.db.set_default("suspend_email_queue", 1)
	frappe.db.commit()
	print("Cuenta de prueba lista; el envío queda suspendido.")
