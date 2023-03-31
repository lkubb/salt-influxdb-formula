"""
Export Salt-internal metrics to an InfluxDB v2 server.
This is a very basic draft and only exports
the count of (accepted|denied|rejected|pending) minion keys currently.

:depends: `influxdb-client` Python module

See the ref:`returner module docs <influxdb2-metrics-config>` for
general configuration details.
"""

import logging
import time

from datetime import datetime
from pathlib import Path

from salt.exceptions import SaltInvocationError

try:
    import influxdb_client
    from influxdb_client.client.exceptions import InfluxDBError
    from influxdb_client.client.write_api import SYNCHRONOUS

    HAS_INFLUXDB = True
except ImportError:
    HAS_INFLUXDB = False

__virtualname__ = "influxdb2_stats"

log = logging.getLogger(__name__)


def start(interval=30, token=None, bucket=None, url=None, org=None, config_profile="influxdb2"):
    """
    Start the InfluxDB2 engine
    """
    config = __salt__["config.get"](config_profile)
    try:
        token = token or config["token"]
    except KeyError as err:
        raise SaltInvocationError(
            f"Missing token: {config_profile}:token"
        ) from err
    bucket = bucket or config.get("bucket", "salt")
    url = url or config.get("url", "http://localhost:8086")
    org = org or config.get("org", "salt")
    engine = InfluxDB2Exporter(config={"token": token, "url": url, "org": org}, bucket=bucket, interval=interval)
    engine.run()


class InfluxDB2Exporter:
    running = True

    def __init__(self, config, bucket="salt", interval=30):
        self.config = config
        self.bucket = bucket
        self.interval = interval

    def run(self):
        pki_dir = Path(__opts__["pki_dir"])

        while self.running:
            record = {
                "measurement": "master",
                "tags": {
                    "master": __opts__["id"],
                    "salt_version": _salt_version(),
                },
                "fields": {
                    "keys_accepted": _num_keys("accepted", pki_dir),
                    "keys_denied": _num_keys("denied", pki_dir),
                    "keys_rejected": _num_keys("rejected", pki_dir),
                    "keys_pending": _num_keys("pre", pki_dir),
                },
                "timestamp": datetime.utcnow(),
            }
            with influxdb_client.InfluxDBClient(**self.config) as client:
                write_api = client.write_api(write_options=SYNCHRONOUS)
                try:
                    write_api.write(self.bucket, record=record)
                except InfluxDBError as err:
                    log.error(f"Failed to store metrics: {err}")
            time.sleep(self.interval)


def _num_keys(status, pki_dir):
    if status == "accepted":
        tgt = "minions"
    else:
        tgt = f"minions_{status}"
    return len(list((pki_dir / tgt).glob("*")))


def _salt_version():
    try:
        version = __grains__["saltversion"]
    except (NameError, KeyError):
        import salt.version

        version = salt.version.__version__
    return version.split("+", maxsplit=1)[0]
