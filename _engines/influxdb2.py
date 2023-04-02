"""
Export Salt-internal metrics to an InfluxDB v2 server.
This is a very basic draft currently.

:depends: `influxdb-client` Python module

See the ref:`returner module docs <influxdb2-metrics-config>` for
general configuration details regarding the InfluxDB connection.

Configuration
-------------

output_template
    A dictionary representing the record to submit to InfluxDB.
    It can be templated as seen in the
    ref:`returner module docs <influxdb2-metrics-config>`.
    See below for available variables.

interval
    Interval between submissions. Defaults to 30 (seconds).

token
    Override the InfluxDB token from the configuration.

bucket
    Override the default bucket from the InfluxDB configuration.

url
    Override the default URL from the InfluxDB configuration.

org
    Override the default organization from the InfluxDB configuration.

config_profile
    The configuration profile name to pull defaults from.
    Defaults to ``influxdb2``.


Templating
----------
Generally, the format should be as follows:

.. code-block:: yaml

    measurement: master
    fields:
      some_field: '{some_templated_value}'
    tags:
      some_tag: '{some_other_value}'

Available variables depend on the context (minion vs master).

General
^^^^^^^
salt_version
    The running daemon's Salt version.

onedir
    Whether the current daemon is a onedir installation.

salt_startup_time
    The ``ctime`` of __opts__["cachedir"], which usually correlates
    with the last startup of the daemon.

daemon_procs_cnt
    The count of running daemon processes for the master/minion daemon,
    depending on context.

daemon_procs_mem
    The amount of memory consumed by all running daemon processes for the
    master/minion daemon, depending on context.

opts
    The __opts__ dict.

pillar
    The pillar dict. For the master, it returns the actual master pillar,
    usually targeted by ``<minion_id>_master``.

grains
    The grains dict. In the master context, this accesses the cached
    master minion's grain data, thus requires a running local minion
    that is bound to the local master.

Master
^^^^^^
keys_accepted
    Number of files in ``<__opts__["pki_dir"]>/minions``.

keys_denied
    Number of files in ``<__opts__["pki_dir"]>/minions_denied``.

keys_rejected
    Number of files in ``<__opts__["pki_dir"]>/minions_rejected``.

keys_pending
    Number of files in ``<__opts__["pki_dir"]>/minions_pre``.

salt_api_procs_cnt
    The count of running salt-api processes.

salt_api_procs_mem
    The amount of memory consumed by all running salt-api processes.

salt_syndic_procs_cnt
    The count of running salt-syndic processes.

salt_syndic_procs_mem
    The amount of memory consumed by all running salt-syndic processes.

mom
    Whether this master is a master of masters.

syndic_master
    Whether this master is part of a syndic.

Default output template
-----------------------
Master
^^^^^^
.. code-block:: yaml

    measurement: master
    fields:
      keys_accepted: '{keys_accepted}'
      keys_denied: '{keys_denied}'
      keys_rejected: '{keys_rejected}'
      keys_pending: '{keys_pending}'
      last_startup: '{last_startup}'
      procs_cnt: '{daemon_procs_cnt}'
      procs_mem: '{daemon_procs_mem}'
    tags:
      master: '{opts[id]}'
      salt_version: '{salt_version}'

Minion
^^^^^^
.. code-block:: yaml

    measurement: minion
    fields:
      last_startup: '{last_startup}'
      procs_cnt: '{daemon_procs_cnt}'
      procs_mem: '{daemon_procs_mem}'
    tags:
      minion: '{opts[id]}'
      salt_version: '{salt_version}'
"""

import logging
import sys
import time

from datetime import datetime
from pathlib import Path

import influxdb2util
import salt.utils.immutabletypes as immutabletypes
import salt.version
from salt.exceptions import SaltInvocationError

try:
    import influxdb_client
    from influxdb_client.client.exceptions import InfluxDBError
    from influxdb_client.client.write_api import SYNCHRONOUS

    HAS_INFLUXDB = True
except ImportError:
    HAS_INFLUXDB = False

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

__virtualname__ = "influxdb2_stats"

log = logging.getLogger(__name__)


DEFAULT_MASTER_POINT = immutabletypes.freeze(
    {
        "measurement": "master",
        "fields": {
            "keys_accepted": "{keys_accepted}",
            "keys_denied": "{keys_denied}",
            "keys_rejected": "{keys_rejected}",
            "keys_pending": "{keys_pending}",
            "last_startup": "{salt_startup_time}",
            "procs_cnt": "{daemon_procs_cnt}",
            "procs_mem": "{daemon_procs_mem}",
        },
        "tags": {
            "master": "{opts[id]}",
            "salt_version": "{salt_version}",
        },
    }
)

DEFAULT_MINION_POINT = immutabletypes.freeze(
    {
        "measurement": "minion",
        "fields": {
            "last_startup": "{salt_startup_time}",
            "procs_cnt": "{daemon_procs_cnt}",
            "procs_mem": "{daemon_procs_mem}",
        },
        "tags": {
            "minion": "{opts[id]}",
            "salt_version": "{salt_version}",
        },
    }
)


def start(
    output_template=None,
    interval=30,
    token=None,
    bucket=None,
    url=None,
    org=None,
    config_profile="influxdb2",
):
    """
    Start the InfluxDB2 engine
    """
    config = __salt__["config.get"](config_profile)
    try:
        token = token or config["token"]
    except KeyError as err:
        raise SaltInvocationError(f"Missing token: {config_profile}:token") from err
    bucket = bucket or config.get("bucket", "salt")
    url = url or config.get("url", "http://localhost:8086")
    org = org or config.get("org", "salt")
    engine = InfluxDB2Exporter(
        config={"token": token, "url": url, "org": org},
        bucket=bucket,
        output_template=output_template,
        interval=interval,
    )
    engine.run()


class InfluxDB2Exporter:
    running = True

    def __init__(self, config, bucket="salt", output_template=None, interval=30):
        self.config = config
        self.bucket = bucket
        self.interval = interval
        self.default_fmt = (
            DEFAULT_MASTER_POINT if _is_master() else DEFAULT_MINION_POINT
        )
        self.fmt = output_template or self.default_fmt

    def run(self):
        data = {
            "opts": __opts__,
        }
        prj = influxdb2util.Projector(self._get_mappings(), data)

        while self.running:
            if not _is_master() and "master_uri" not in __opts__:
                return
            record = {
                "measurement": self.fmt.get(
                    "measurement", self.default_fmt["measurement"]
                ),
                # tag values must be strings
                "tags": {
                    k: str(v)
                    for k, v in prj(
                        self.fmt.get("tags", self.default_fmt["tags"])
                    ).items()
                },
                "fields": prj(self.fmt.get("fields", self.default_fmt["fields"])),
                "time": datetime.utcnow(),
            }

            with influxdb_client.InfluxDBClient(**self.config) as client:
                write_api = client.write_api(write_options=SYNCHRONOUS)
                try:
                    write_api.write(self.bucket, record=record)
                except InfluxDBError as err:
                    log.error(f"Failed to store metrics: {err}")
            time.sleep(self.interval)

    def _get_mappings(self):
        mappings = {
            "salt_version": lambda _: salt.version.__version__.split("+", maxsplit=1)[
                0
            ],
            "onedir": _is_onedir,
        }
        if _is_master():
            mappings.update(self._get_master_mappings())
        else:
            mappings.update(self._get_minion_mappings())
        return mappings

    def _get_master_mappings(self):
        return {
            "keys_accepted": lambda _: _num_keys("accepted"),
            "keys_denied": lambda _: _num_keys("denied"),
            "keys_rejected": lambda _: _num_keys("rejected"),
            "keys_pending": lambda _: _num_keys("pre"),
            "mom": lambda x: bool(x.get("order_masters")),
            "syndic": lambda x: bool(x.get("syndi_master")),
            # grains of the master node require a running local minion
            # the master ID is <minion_id>_master usually
            # Access to execution modules might be possible with __salt__ using
            # a MasterMinion, but this should be faster and might avoid some pitfalls
            "grains": lambda _: __runners__["cache.fetch"](
                "minions/{}/data".format(__opts__["id"].rsplit("_", maxsplit=1)[0]),
                "grains",
            ),
            # "grains": lambda _: next(iter(__runners__["salt.execute"](__opts__["id"].rsplit("_", maxsplit=1)[0], "grains.items"))),
            "pillar": lambda _: __runners__["pillar.show_pillar"](__opts__["id"]),
            "daemon_procs_cnt": lambda _: _procs_cnt("master"),
            "daemon_procs_mem": lambda _: _procs_mem("master"),
            "salt_api_procs_cnt": lambda _: _procs_cnt("api"),
            "salt_api_procs_mem": lambda _: _procs_mem("api"),
            "salt_syndic_procs_cnt": lambda _: _procs_cnt("syndic"),
            "salt_syndic_procs_mem": lambda _: _procs_mem("syndic"),
            # This seems to be updated on restart
            "salt_startup_time": lambda _: __runners__["salt.cmd"](
                "file.stats", __opts__["cachedir"]
            )["ctime"],
            # This only works with recent systemd versions
            # "startup_time_systemd": lambda _: __runners__["salt.cmd"]("cmd.run", "systemctl show salt-master --timestamp=unix | grep ActiveEnterTimestamp= | cut -d'@' -f 2", python_shell=True)
        }

    def _get_minion_mappings(self):
        return {
            # grains are not packed into engines
            "grains": lambda _: __salt__["grains.items"](),
            "pillar": lambda _: __salt__["pillar.items"](),
            "salt_startup_time": lambda _: __salt__["file.stats"](__opts__["cachedir"])[
                "ctime"
            ],
            "daemon_procs_cnt": lambda _: _procs_cnt("minion"),
            "daemon_procs_mem": lambda _: _procs_mem("minion"),
        }


def _num_keys(status):
    pki_dir = Path(__opts__["pki_dir"])
    if status == "accepted":
        tgt = "minions"
    else:
        tgt = f"minions_{status}"
    return len(list((pki_dir / tgt).glob("*")))


def _salt_version():
    return salt.version.__version__.split("+", maxsplit=1)[0]


def _is_master():
    return __opts__.get("__role", "minion") == "master"


def _is_onedir(_=None):
    return getattr(sys, "frozen", False)


def _is_tiamat(_=None):
    return _is_onedir() and hasattr(sys, "_MEIPASS")


def _find_procs(daemon, measurements=None, proc_name=None):
    """
    Count daemon processes for minion/master/...
    This only works on Linux afaict
    """
    measurements = measurements or []
    ret = []
    if _is_tiamat():
        # Usually as /opt/saltstack/salt/run/run (minion|master) [...]
        # name is /opt/saltstack
        # exe is /opt/saltstack/salt/run/run
        # we need the cmdline to differentiate minion from master
        for proc in psutil.process_iter(["cmdline"] + measurements):
            try:
                if proc.info["cmdline"][:2] == [sys.executable, daemon]:
                    ret.append(proc)
            except IndexError:
                continue
        return ret

    # not sure about relenv @TODO
    for proc in psutil.process_iter(["name"] + measurements):
        if proc.info["name"] in (
            (proc_name,) if proc_name else (f"salt-{daemon}", f"salt_{daemon}")
        ):
            ret.append(proc)
    return ret


def _procs_cnt(daemon, proc_name=None):
    """
    Count daemon processes for minion/master/...
    This only works on Linux afaict
    """
    return len(_find_procs(daemon, proc_name=proc_name))


def _procs_mem(daemon, proc_name=None):
    """
    Count daemon process memory consumption for minion/master/...
    This only works on Linux afaict
    """
    count = 0
    for proc in _find_procs(
        daemon, measurements=["memory_full_info"], proc_name=proc_name
    ):
        count += proc.info["memory_full_info"].uss
    return count
