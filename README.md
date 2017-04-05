# mqtt-locust

MQTT Load Testing with Locust

This extends [Locust](http://locust.io) to load test MQTT (publishing only, currently).

It relies on the [Python Paho](https://eclipse.org/paho/clients/python/) MQTT Client library.

The `mqtt_locust.py` provides a **MQTTLocust** class that your `locustfile.py` should include. Here is a short exampe:

```python
import json
import random
import resource

from locust import TaskSet, task

from mqtt_locust import MQTTLocust


TIMEOUT = 6
REPEAT = 100


class MyTaskSet(TaskSet):
    def qos0(self):
        self.client.publish(
                'sometopic', self.payload(), qos=0, timeout=TIMEOUT,
                repeat=REPEAT, name='qos0 publish'
                )

    def payload(self):
        payload = {
            'hello': 'world'
        }
        return json.dumps(payload)


class MyLocust(MQTTLocust):
    task_set = MyTaskSet
    min_wait = 5000
    max_wait = 15000

```

Messages may be sent rapidly using the 'repeat' keyword argument, as seen in the example above.

Messages that are not acknowledged within the 'timeout' period are recorded as failures (this really only applies to messages published with a QoS of 1 or 2).

## Starting Locust

To start MQTT Locust, specify a host with a URL scheme of "mqtt://", like:

```bash
locust --host=mqtt://somedomain.com:1883
```
