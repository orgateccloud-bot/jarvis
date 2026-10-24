"""Notificação nativa do Windows (winotify). Em outros sistemas, ou sem o pacote, vira no-op."""

from __future__ import annotations

from loguru import logger

try:
    from winotify import Notification
except ImportError:  # fora do Windows ou sem o pacote opcional
    Notification = None


def notify(title: str, text: str) -> bool:
    if Notification is None:
        return False
    try:
        Notification(app_id="JARVIS", title=title, msg=text[:240]).show()
        return True
    except Exception as e:  # noqa: BLE001 — notificação é melhor-esforço; nunca derruba o laço
        logger.warning(f"notificação do Windows falhou: {e}")
        return False
