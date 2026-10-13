from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.workers.outbox_publisher import _fetch_pending, _publish_pending_events

# run() abre una conexion real a RabbitMQ y corre en loop infinito
# Testeamos la logica de negocio del worker, que evento levanta, que
# le manda al exchange, y que hace cuando falla la publicacion.


class FakeExchange:
    def __init__(self, fail_for: set[str] | None = None):
        self.published = []
        self.fail_for = fail_for or set()

    async def publish(self, message, routing_key):
        if routing_key in self.fail_for:
            raise ConnectionError("rabbitmq no responde")
        self.published.append((routing_key, message))


async def _add_event(db_session: AsyncSession, event_type: str, aggregate_id: str = "agg-1") -> OutboxEvent:
    event = OutboxEvent(
        aggregate_type="user",
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload={"aggregate_id": aggregate_id},
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


@pytest.mark.asyncio
async def test_fetch_pending_only_returns_unprocessed_events(db_session: AsyncSession):
    pending = await _add_event(db_session, "user.registered")
    processed = await _add_event(db_session, "user.registered", aggregate_id="agg-2")
    processed.processed_at = datetime.now(UTC)
    await db_session.commit()

    result = await _fetch_pending(db_session)

    ids = {e.id for e in result}
    assert pending.id in ids
    assert processed.id not in ids


@pytest.mark.asyncio
async def test_fetch_pending_respects_batch_size(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr("app.workers.outbox_publisher.BATCH_SIZE", 2)
    for i in range(5):
        await _add_event(db_session, "user.registered", aggregate_id=f"agg-{i}")

    result = await _fetch_pending(db_session)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_publish_pending_events_marks_processed_on_success(db_session: AsyncSession, monkeypatch):
    event = await _add_event(db_session, "user.registered")
    exchange = FakeExchange()

    # _publish_pending_events abre su propia sesion via AsyncSessionLocal, asi que
    # apuntamos ese sessionmaker al motor de test en lugar de a Postgres real.
    monkeypatch.setattr("app.workers.outbox_publisher.AsyncSessionLocal", _session_factory_for(db_session))

    await _publish_pending_events(exchange)

    assert len(exchange.published) == 1
    assert exchange.published[0][0] == "user.registered"

    await db_session.refresh(event)
    assert event.processed_at is not None


@pytest.mark.asyncio
async def test_publish_pending_events_keeps_event_pending_on_publish_failure(db_session: AsyncSession, monkeypatch):
    # Si falla la publicacion se corta el ciclo (run() lo loguea y reintenta): asi no se publican
    # los eventos siguientes antes que el que fallo y se respeta el orden.
    published_before = await _add_event(db_session, "user.registered")
    failing = await _add_event(db_session, "user.profile.updated")
    # created_at de SQLite tiene precision de segundos: se fija para que el orden no dependa del id (uuid)
    published_before.created_at = datetime(2000, 1, 1, tzinfo=UTC)
    await db_session.commit()
    exchange = FakeExchange(fail_for={"user.profile.updated"})

    monkeypatch.setattr("app.workers.outbox_publisher.AsyncSessionLocal", _session_factory_for(db_session))

    with pytest.raises(ConnectionError):
        await _publish_pending_events(exchange)

    assert [routing_key for routing_key, _ in exchange.published] == ["user.registered"]
    await db_session.refresh(published_before)
    await db_session.refresh(failing)
    assert published_before.processed_at is not None
    assert failing.processed_at is None


def _session_factory_for(db_session: AsyncSession):
    """Devuelve un 'factory' compatible con `async with AsyncSessionLocal() as db:`
    que siempre entrega la misma sesion de test (misma conexion sqlite en memoria)."""

    class _Ctx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    class _Factory:
        def __call__(self):
            return _Ctx()

    return _Factory()


# No probamos contra un RabbitMQ real. Lo que si podemos


class _StopLoop(Exception):
    """Excepcion centinela solo para cortar el `while True` de run() en el test."""


class FakeRobustConnection:
    def __init__(self, channel):
        self._channel = channel

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def channel(self):
        return self._channel


class FakeChannel:
    def __init__(self, exchange):
        self._exchange = exchange
        self.declared_with = None

    async def declare_exchange(self, name, exchange_type, durable=False):
        self.declared_with = {"name": name, "exchange_type": exchange_type, "durable": durable}
        return self._exchange


@pytest.mark.asyncio
async def test_run_connects_declares_exchange_and_polls(monkeypatch):
    import asyncio

    from app.workers import outbox_publisher as outbox_publisher_module

    exchange = FakeExchange()
    channel = FakeChannel(exchange)
    connection = FakeRobustConnection(channel)

    connect_calls = []

    async def fake_connect_robust(url):
        connect_calls.append(url)
        return connection

    publish_calls = []

    async def fake_publish_pending_events(exch):
        publish_calls.append(exch)

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise _StopLoop()  # cortamos despues de la primera vuelta del while True

    monkeypatch.setattr(outbox_publisher_module.aio_pika, "connect_robust", fake_connect_robust)
    monkeypatch.setattr(outbox_publisher_module, "_publish_pending_events", fake_publish_pending_events)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        await outbox_publisher_module.run()

    assert connect_calls == [outbox_publisher_module.settings.rabbitmq_url]
    assert channel.declared_with == {
        "name": outbox_publisher_module.settings.rabbitmq_exchange,
        "exchange_type": outbox_publisher_module.aio_pika.ExchangeType.TOPIC,
        "durable": True,
    }
    assert publish_calls == [exchange]
    assert sleep_calls == [outbox_publisher_module.POLL_INTERVAL_SECONDS]
