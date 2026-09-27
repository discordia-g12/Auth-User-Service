# Este es el worker que implementa el lado publisher del patron Outbox
import asyncio
import json
import logging
from datetime import UTC, datetime

import aio_pika
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.outbox import OutboxEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbox_publisher")

POLL_INTERVAL_SECONDS = 2
BATCH_SIZE = 50


async def _fetch_pending(db) -> list[OutboxEvent]:
    result = await db.execute(
        select(OutboxEvent).where(OutboxEvent.processed_at.is_(None)).order_by(OutboxEvent.created_at).limit(BATCH_SIZE)
    )
    return list(result.scalars())


async def _publish_pending_events(exchange: aio_pika.abc.AbstractExchange) -> None:
    async with AsyncSessionLocal() as db:
        pending = await _fetch_pending(db)

        for event in pending:
            try:
                await exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(event.payload).encode(),
                        content_type="application/json",
                        message_id=event.id,
                    ),
                    routing_key=event.event_type,
                )
            except Exception:
                logger.exception("Failed publishing event %s, will retry later.", event.id)
                continue

            event.processed_at = datetime.now(UTC)
            await db.commit()
            logger.info("Published %s (%s) -> %s", event.event_type, event.id, event.aggregate_id)


# Cada X segundos busca en outbox_events los que tienen processed_at IS NULL y los procesa.
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
            await _publish_pending_events(exchange)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())
