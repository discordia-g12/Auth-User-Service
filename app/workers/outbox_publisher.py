# Worker que implementa el lado publisher del patrón Outbox.
# Garantía: at-least-once. Un evento puede publicarse dos veces (si el commit
# falla después de publicar); los consumidores deduplican por message_id.
import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import aio_pika
from aio_pika.abc import AbstractExchange
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.outbox import OutboxEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox_publisher")

POLL_INTERVAL_SECONDS = 2
BATCH_SIZE = 50
HEARTBEAT = Path("/tmp/outbox-heartbeat")  # nosec B108 # archivo de liveness dentro del contenedor


async def _fetch_pending(db) -> list[OutboxEvent]:
    result = await db.execute(
        select(OutboxEvent)
        .where(OutboxEvent.processed_at.is_(None))
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(BATCH_SIZE)
    )
    return list(result.scalars())


def _build_message(event: OutboxEvent) -> aio_pika.Message:
    return aio_pika.Message(
        body=json.dumps(event.payload, default=str).encode(),
        content_type="application/json",
        # Sin esto el mensaje es transitorio: si RabbitMQ reinicia, se pierde
        # aunque la cola sea durable.
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        message_id=str(event.id),  # clave de idempotencia para los consumidores
        type=event.event_type,
        timestamp=event.created_at,
        headers={"aggregate_id": str(event.aggregate_id)},
    )


async def _publish_pending_events(exchange: AbstractExchange) -> int:
    published = 0
    async with AsyncSessionLocal() as db:  # la fábrica ya usa expire_on_commit=False (app/db/session.py)
        for event in await _fetch_pending(db):
            await exchange.publish(_build_message(event), routing_key=event.event_type)

            event.processed_at = datetime.now(UTC)
            await db.commit()
            published += 1
            logger.info("Published %s (%s) -> %s", event.event_type, event.id, event.aggregate_id)
    return published


async def run() -> None:
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            settings.rabbitmq_exchange,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        logger.info("Outbox publisher conectado a RabbitMQ, exchange=%s", settings.rabbitmq_exchange)

        while True:
            try:
                await _publish_pending_events(exchange)
                HEARTBEAT.touch()
            except Exception:
                logger.exception("Ciclo de outbox fallido; se reintenta en %ss", POLL_INTERVAL_SECONDS)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())