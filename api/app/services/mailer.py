"""Envío de correo (solo para el reset de contraseña).

Usa el `smtplib` de la librería estándar en un hilo, para no añadir dependencias
ni bloquear el event loop. Si no hay SMTP configurado (`SMTP_HOST` vacío), el
mensaje **no se envía**: se registra en el log y solo en desarrollo, para poder
completar el flujo a mano. En producción, un fallo de SMTP nunca debe tumbar la
petición ni revelar el token: se avisa por log y se sigue.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _send_sync(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Envía un correo. Devuelve True si salió, False si no se pudo enviar.

    Nunca lanza: un fallo de SMTP no debe tumbar el flujo de reset.
    """
    if not settings.smtp_host:
        if settings.debug:
            # Solo en desarrollo: sin SMTP no hay forma de probar el flujo.
            logger.warning(
                "SMTP_HOST vacío: correo no enviado. Para: %s | Asunto: %s | Cuerpo:\n%s", to, subject, body
            )
        else:
            logger.error("SMTP_HOST vacío en producción: el correo de reset para %s NO se ha enviado", to)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, body)
    except Exception:
        logger.exception("Error enviando correo a %s (smtp_host=%s)", to, settings.smtp_host)
        return False
    return True


def password_reset_body(link: str, minutes: int) -> tuple[str, str]:
    """Devuelve (asunto, cuerpo) del correo de reset en texto plano."""
    subject = "Restablecer tu contraseña de Loopy"
    body = (
        "Hola,\n\n"
        "Alguien ha pedido restablecer la contraseña de esta cuenta de Loopy.\n"
        "Si no fuiste tú, ignora este mensaje: no cambiaremos nada.\n\n"
        f"Abre este enlace para elegir una contraseña nueva (caduca en {minutes} minutos):\n"
        f"{link}\n\n"
        "-- Loopy"
    )
    return subject, body
