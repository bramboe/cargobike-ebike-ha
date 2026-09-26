"""MQTT start-up, reconnects and restoring the alarm state."""

from __future__ import annotations

import asyncio
import socket
import threading
import time

from conftest import FakeMqtt

# ------------------------------------------------------------ alarm restore


async def test_alarm_waits_for_the_broker_before_asserting(r, fake_mqtt, monkeypatch):
    """The old code published "disarmed" after a blind 2 s sleep, overwriting an
    armed state whenever the broker was slow."""
    monkeypatch.setattr(r, "ALARM_RESTORE_WAIT", 0.3)
    task = asyncio.create_task(r._alarm_restore())
    await asyncio.sleep(0.8)                         # broker still unreachable
    assert not task.done()
    assert fake_mqtt.topic(r.ALARM_STATE_TOPIC) == []
    r._mqtt_up.set()                                 # connected ...
    r._handle_mqtt_message(r.ALARM_STATE_TOPIC, "armed_away")   # ... retained state
    await asyncio.wait_for(task, 2)
    assert r._alarm["state"] == "armed_away"
    assert fake_mqtt.topic(r.ALARM_STATE_TOPIC) == ["armed_away"]


async def test_alarm_defaults_when_nothing_retained(r, fake_mqtt, monkeypatch):
    monkeypatch.setattr(r, "ALARM_RESTORE_WAIT", 0.2)
    r._mqtt_up.set()
    await asyncio.wait_for(r._alarm_restore(), 2)
    assert r._alarm["restored"] is True
    assert fake_mqtt.topic(r.ALARM_STATE_TOPIC) == ["disarmed"]


def test_command_wins_over_a_late_retained_state(r, fake_mqtt):
    r._handle_mqtt_message(r.ALARM_CMD_TOPIC, "ARM_AWAY")
    r._handle_mqtt_message(r.ALARM_STATE_TOPIC, "disarmed")    # stale retained copy
    assert r._alarm["state"] == "armed_away"


def test_reconnect_reasserts_the_alarm(r, fake_mqtt):
    r._alarm.update(state="armed_home", restored=True)
    client = FakeMqtt()
    r._on_connect(client, None, None, 0)
    assert client.topic(r.ALARM_STATE_TOPIC) == ["armed_home"]
    assert r._mqtt_up.is_set()
    r._on_disconnect(client, None, None, 7, None)
    assert not r._mqtt_up.is_set()


async def test_messages_are_handled_on_the_event_loop(r, fake_mqtt, monkeypatch):
    loop_thread = threading.get_ident()
    seen = []
    monkeypatch.setattr(r, "_loop", asyncio.get_running_loop())
    monkeypatch.setattr(r, "_handle_mqtt_message",
                        lambda topic, payload: seen.append((threading.get_ident(), payload)))

    class Msg:
        topic = r.ALARM_CMD_TOPIC
        payload = b"ARM_AWAY"

    t = threading.Thread(target=r._on_message, args=(None, None, Msg()))
    t.start()
    t.join()
    await asyncio.sleep(0.05)
    assert seen == [(loop_thread, "ARM_AWAY")]


# ------------------------------------------------- real paho vs. a late broker


class TinyBroker:
    """Just enough MQTT 3.1.1 for paho: CONNACK, SUBACK, PINGRESP, record
    PUBLISHes, and send one retained message on subscribe."""

    def __init__(self, retained: dict[str, bytes]):
        self.retained = retained
        self.published: list[tuple[str, bytes, bool]] = []
        self.server: asyncio.base_events.Server | None = None

    async def start(self, port: int) -> None:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", port)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    @staticmethod
    async def _read_packet(reader):
        head = (await reader.readexactly(1))[0]
        mult, length = 1, 0
        while True:
            b = (await reader.readexactly(1))[0]
            length += (b & 0x7F) * mult
            mult *= 128
            if not b & 0x80:
                break
        return head, await reader.readexactly(length)

    @staticmethod
    def _publish_packet(topic: str, payload: bytes, retain: bool) -> bytes:
        t = topic.encode()
        body = len(t).to_bytes(2, "big") + t + payload
        head = bytes([0x30 | (1 if retain else 0)])
        length, enc = len(body), b""
        while True:
            byte, length = length % 128, length // 128
            enc += bytes([byte | (0x80 if length else 0)])
            if not length:
                break
        return head + enc + body

    async def _client(self, reader, writer):
        try:
            while True:
                head, body = await self._read_packet(reader)
                kind = head & 0xF0
                if kind == 0x10:                                   # CONNECT
                    writer.write(b"\x20\x02\x00\x00")
                elif kind == 0x80:                                 # SUBSCRIBE
                    pid, pos, topics = body[:2], 2, []
                    while pos < len(body):
                        n = int.from_bytes(body[pos:pos + 2], "big")
                        topics.append(body[pos + 2:pos + 2 + n].decode())
                        pos += 2 + n + 1
                    writer.write(bytes([0x90, 2 + len(topics)]) + pid + b"\x00" * len(topics))
                    for topic in topics:
                        if topic in self.retained:
                            writer.write(self._publish_packet(topic, self.retained[topic], True))
                elif kind == 0x30:                                 # PUBLISH (qos 0)
                    n = int.from_bytes(body[:2], "big")
                    self.published.append((body[2:2 + n].decode(), body[2 + n:],
                                           bool(head & 1)))
                elif kind == 0xC0:                                 # PINGREQ
                    writer.write(b"\xd0\x00")
                elif kind == 0xE0:                                 # DISCONNECT
                    break
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_addon_survives_a_late_broker_and_restores_the_alarm(r, monkeypatch):
    port = _free_port()
    monkeypatch.setattr(r, "MQTT_HOST", "127.0.0.1")
    monkeypatch.setattr(r, "MQTT_PORT", port)
    monkeypatch.setattr(r, "MQTT_USER", "")
    monkeypatch.setattr(r, "_loop", asyncio.get_running_loop())
    client = r.make_mqtt()                 # broker down: must not raise
    monkeypatch.setattr(r, "_mqtt", client)
    broker = TinyBroker({r.ALARM_STATE_TOPIC: b"armed_away"})
    try:
        restore = asyncio.create_task(r._alarm_restore())
        await asyncio.sleep(1.5)
        assert not restore.done() and not r._mqtt_up.is_set()
        await broker.start(port)           # the broker comes up late
        await asyncio.wait_for(restore, 15)
        assert r._alarm["state"] == "armed_away"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (
                (r.ALARM_STATE_TOPIC, b"armed_away", True) not in broker.published):
            await asyncio.sleep(0.05)
        assert (r.ALARM_STATE_TOPIC, b"armed_away", True) in broker.published
        assert any(t.startswith("homeassistant/") for t, _p, _r in broker.published)
    finally:
        client.loop_stop()
        client.disconnect()
        await broker.stop()
