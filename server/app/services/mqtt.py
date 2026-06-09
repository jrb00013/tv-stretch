from __future__ import annotations

import json
import uuid

import paho.mqtt.client as mqtt
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class MqttService:
    def __init__(self) -> None:
        self.client: mqtt.Client | None = None
        self._connected = False

    def start(self) -> None:
        if not settings.mqtt_enabled:
            logger.info("mqtt_disabled_by_config")
            return
        self.client = mqtt.Client(client_id="tv-stretch-server", protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        try:
            self.client.connect(settings.mqtt_broker_url, settings.mqtt_broker_port, keepalive=60)
            self.client.loop_start()
            logger.info(
                "mqtt_started",
                broker=settings.mqtt_broker_url,
                port=settings.mqtt_broker_port,
            )
        except Exception as exc:
            logger.error("mqtt_connect_failed", error=str(exc))
            self.client = None

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: object,
        _flags: dict[str, int],
        rc: int,
    ) -> None:
        self._connected = rc == 0
        if self._connected:
            logger.info("mqtt_connected")
        else:
            logger.error("mqtt_connect_failed", rc=rc)

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            logger.info("mqtt_stopped")

    @property
    def connected(self) -> bool:
        return self._connected

    def publish(
        self,
        topic_suffix: str,
        payload: dict,
        home_id: uuid.UUID | str | None = None,
    ) -> None:
        if not self.client or not self._connected:
            return
        hid = str(home_id) if home_id else ""
        prefix = settings.mqtt_prefix
        topic = f"{prefix}/{hid}/{topic_suffix}" if home_id else f"{prefix}/{topic_suffix}"
        self.client.publish(topic, json.dumps(payload), qos=1)
        logger.debug("mqtt_published", topic=topic)


_service = MqttService()


def get_mqtt() -> MqttService:
    return _service
