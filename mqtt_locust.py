import random
import time
import sys
from urllib.parse import urlparse
import gc

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTT_ERR_SUCCESS, error_string
from locust import Locust
from locust import task
from locust import TaskSet
from locust import events


def time_delta(t1, t2):
    return int((t2 - t1) * 1000)


def round_seconds_to_microseconds(t):
    return round(t, 6)


def fire_locust_failure(**kwargs):
    if 'response_time' in kwargs:
        rt = round_seconds_to_microseconds(kwargs['response_time'])
        kwargs['response_time'] = rt
    events.request_failure.fire(**kwargs)


def fire_locust_success(**kwargs):
    if 'response_time' in kwargs:
        rt = round_seconds_to_microseconds(kwargs['response_time'])
        kwargs['response_time'] = rt
    events.request_success.fire(**kwargs)


class LocustError(Exception):
    pass


class TimeoutError(ValueError):
    pass


class DisconnectError(Exception):
    pass


class PendingMqttMessage(object):

    def __init__(self, start_time, timeout, name, payload_size):
        self.start_time = start_time
        self.timeout = timeout
        self.name = name
        self.payload_size = payload_size

    def timed_out(self, total_time):
        return self.timeout is not None and total_time > self.timeout


class MQTTClient:

    def __init__(self, *args, **kwargs):
        self._count_of_on_publish = 0
        self.mqtt = mqtt.Client(*args, **kwargs)
        self.mqtt.on_publish = self._on_publish
        self.mqtt.on_disconnect = self._on_disconnect
        self.mmap = {}

    def connect_and_start_loop(self):
        self.mqtt.connect(self.mqtt_host, self.mqtt_port)
        self.mqtt.loop_start()

    def is_connected(self):
        # this is crude
        return self.mqtt._sock is not None

    def connect_if_necessary(self):
        if not self.is_connected():
            self.connect_and_start_loop()

    def publish(self, topic, payload=None, repeat=1, name='mqtt', **kwargs):
        # this is a kludge - should not be necessary
        self.connect_if_necessary()
        timeout = kwargs.pop('timeout', 5)
        for i in range(repeat):
            start_time = time.time()
            try:
                msginfo = self.mqtt.publish(
                    topic,
                    payload=payload,
                    **kwargs
                )
                if msginfo.rc != MQTT_ERR_SUCCESS:
                    raise Exception(error_string(msginfo.rc))
                self.mmap[msginfo.mid] = PendingMqttMessage(
                        start_time, timeout, name, len(payload),
                        )
            except Exception as e:
                total_time = time.time() - start_time
                fire_locust_failure(
                    request_type='mqtt',
                    name=name,
                    response_time=total_time,
                    exception=e,
                )

    def _on_publish(self, client, userdata, mid):
        end_time = time.time()
        self._count_of_on_publish += 1
        message = self.mmap.pop(mid, None)
        if message is None:
            return
        total_time = end_time - message.start_time
        if message.timed_out(total_time):
            fire_locust_failure(
                request_type='mqtt',
                name=message.name,
                response_time=total_time,
                exception=TimeoutError("publish timed out"),
            )
        else:
            fire_locust_success(
                request_type='mqtt',
                name=message.name,
                response_time=total_time,
                response_length=message.payload_size,
            )

        # periodically check all pending messages for timeouts
        if self._count_of_on_publish % 1000 == 0:
            self.check_for_locust_timeouts(end_time)
            # periodic force garbage collection
            gc.collect()

    def _on_disconnect(self, client, userdata, rc):
        fire_locust_failure(
            request_type='mqtt',
            name=client,
            response_time=0,
            exception=DisconnectError("disconnected"),
        )
        self.mqtt.reconnect()

    def check_for_locust_timeouts(self, end_time):
        timed_out = [mid for mid, msg in dict(self.mmap).items()
                     if msg.timed_out(end_time - msg.start_time)]
        for mid in timed_out:
            msg = self.mmap.pop(mid)
            total_time = end_time - msg.start_time
            fire_locust_failure(
                request_type='mqtt',
                name=msg.name,
                response_time=total_time,
                exception=TimeoutError(
                    "message not received in %s s" % msg.timeout
                    ),
            )


class MQTTLocust(Locust):

    def __init__(self, *args, **kwargs):
        super(Locust, self).__init__(*args, **kwargs)

        host_error = False

        if self.host is None:
            host_error = True
        else:
            urlparts = urlparse(self.host)
            if urlparts.scheme.lower() != 'mqtt':
                host_error = True
            elif not urlparts.netloc:
                host_error = True
            else:
                try:
                    [host, port] = urlparts.netloc.split(":")
                    port = int(port)
                except ValueError:
                    host, port = urlparts.netloc, 1883

        if host_error:
            raise LocustError("You must specify a host of the form "
                              "mqtt://hostname[:port]")

        self.client = MQTTClient()
        self.client.mqtt_host = host
        self.client.mqtt_port = port
