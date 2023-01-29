"""
Return data to an InfluxDB v2 server.

Note that this returner is not intended nor working as a job cache,
but for metrics collection about Salt internals.

:depends: `influxdb-client` Python module

Configuration
-------------

You can set it as a default returner in the minion configuration

.. code-block:: yaml

    return:
      - influxdb2


as well as an event returner in the master config

.. code-block:: yaml

    event_return:
      - influxdb2

Connection parameters
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

    influxdb2:
      url: http://localhost:8086
      org: salt
      bucket: salt
      token: my-token

Filtering
~~~~~~~~~
You can filter returns/events based on a list of regular expressions.
Note that for events, there are global settings ``event_return_whitelist``/``event_return_blacklist``.
The event filter functionality exists in case you use multiple event returners
and are only interested in a subset for InfluxDB specifically.
This clutch can be removed once issue #54123 is closed.

.. code-block:: yaml

    influxdb2:
      # Only record events matching at least one regular expression.
      events_allowlist: []

      # Record all events except those matching at least one regular expression
      events_blocklist: []

      # Only record returns of functions matching at least one regular expression
      functions_allowlist: []

      # Record returns of all functions except those matching at least one regular expression
      functions_blocklist: []


Templates
~~~~~~~~~
You can influence how return/event data is transformed into a point record.
This can be configured for all returns/events or specific to the function/
event tag.

.. code-block:: yaml

    influxdb2:
      # default transformation for events
      event_point_fmt:
        measurement: events
        fields:
          data: '{data}'
        tags:
          tag: '{tag}'

      # Transformations for particular event tags
      # Tags are keys (literal), values as in the default transformation
      event_point_fmt_tag: {}

      # Default transformation for returns
      function_point_fmt:
        measurement: returns
        fields:
          jid: '{jid}'
          return: '{return}'
          retcode: '{retcode}'
        tags:
          fun: '{fun}'
          minion: '{id}'

      # Transformations for particular functions
      # Functions are keys (literal), values as in the default transformation
      function_point_fmt_fun: {}

      # Transformation for `state.[apply|highstate|sls]` in particular
      function_point_fmt_state:
        measurement: returns
        fields:
          jid: '{jid}'
          retcode: '{retcode}'
          states_failed: '{states_failed}'
          states_total: '{states_total}'
        tags:
          fun: '{fun}'
          minion: '{id}'

The templates values can be a simple ``{var}``, for which the raw value of the
dictionary is returned if it is compatible with InfluxDB for the scope, otherwise
it is dumped as a JSON string. For this simple case, you can even traverse the
dict like ``{return:value}``. Note the quotes around the YAML values!

The template values can also be Python format strings, in which case you cannot
traverse the dictionaries and only have access to the top keys.

Depending on the type, there are miscellaneous template vars available.

returns
    ``full_ret`` (full return dict, excluding ``result``) and
    ``module`` (the module part of ``fun``)

returns for state functions
    In addition, ``states_succeeded``, ``states_failed`` and ``states_total``,
    which each report the sum, not the state IDs.

events
    ``master``, which is ``opts["id"]`` of the master posting the event

Alternatives
~~~~~~~~~~~~

Alternative configuration values can be used by prefixing the configuration value(s).
Any values not found in the alternative configuration will be pulled from
the default location:

.. code-block:: yaml

    alternative.influxdb2.host: influxdb_alt
    alternative.influxdb2.port: 6379
    alternative.influxdb2.org: salt_alt
    alternative.influxdb2.bucket: salt_alt
    alternative.influxdb2.token: my-alt-token
"""

import logging
import re
from collections.abc import Mapping
from datetime import datetime

import salt.returners
import salt.utils.immutabletypes as immutabletypes
import salt.utils.json as json

try:
    import influxdb_client
    from influxdb_client.client.exceptions import InfluxDBError
    from influxdb_client.client.write_api import SYNCHRONOUS

    HAS_INFLUXDB = True
except ImportError:
    HAS_INFLUXDB = False

__virtualname__ = "influxdb2"

log = logging.getLogger(__name__)


DEFAULT_FUNCTION_POINT = immutabletypes.freeze(
    {
        "measurement": "returns",
        "fields": {
            "jid": "{jid}",
            "return": "{return}",
            "retcode": "{retcode}",
        },
        "tags": {
            "fun": "{fun}",
            "minion": "{id}",
        },
    }
)

DEFAULT_EVENT_POINT = immutabletypes.freeze(
    {
        "measurement": "events",
        "fields": {
            "data": "{data}",
        },
        "tags": {
            "tag": "{tag}",
        },
    }
)

DEFAULT_STATE_POINT = immutabletypes.freeze(
    {
        "measurement": "returns",
        "fields": {
            "jid": "{jid}",
            "retcode": "{retcode}",
            "states_failed": "{states_failed}",
            "states_total": "{states_total}",
        },
        "tags": {
            "fun": "{fun}",
            "minion": "{id}",
        },
    }
)

STATE_FUNCTIONS = ("state.apply", "state.highstate", "state.sls")


def __virtual__():
    if HAS_INFLUXDB:
        return __virtualname__
    return (
        False,
        "The influxdb2 returner requires the influxdb-client Python library",
    )


def _get_options(ret=None):
    """
    Get the influxdb options from salt.
    """
    attrs = {
        "url": "url",
        "org": "org",
        "bucket": "bucket",
        "token": "token",
        "event_point_fmt": "event_point_fmt",
        "event_point_fmt_tag": "event_point_fmt_tag",
        "events_allowlist": "events_allowlist",
        "events_blocklist": "events_blocklist",
        "function_point_fmt": "function_point_fmt",
        "function_point_fmt_fun": "function_point_fmt_fun",
        "function_point_fmt_state": "function_point_fmt_state",
        "functions_allowlist": "functions_allowlist",
        "functions_blocklist": "functions_blocklist",
    }

    defaults = {
        "url": "http://localhost:8086",
        "org": "salt",
        "bucket": "salt",
        "event_point_fmt": DEFAULT_EVENT_POINT,
        "event_point_fmt_tag": {},
        "events_allowlist": [],
        "events_blocklist": [],
        "function_point_fmt": DEFAULT_FUNCTION_POINT,
        "function_point_fmt_fun": {},
        "function_point_fmt_state": DEFAULT_STATE_POINT,
        "functions_allowlist": [],
        "functions_blocklist": [],
    }

    _options = salt.returners.get_returner_options(
        __virtualname__,
        ret,
        attrs,
        __salt__=__salt__,
        __opts__=__opts__,
        defaults=defaults,
    )
    return _options


def returner(ret):
    """
    Write return to an InfluxDB bucket
    """
    options = _get_options(ret)

    if (
        _re_match(options["functions_blocklist"], ret["fun"])
        or options["functions_allowlist"]
        and not _re_match(options["functions_allowlist"], ret["fun"])
    ):
        log.info(
            f"Skipping InfluxDB2 return for job {ret['jid']}: {ret['fun']} is filtered"
        )
        return

    client = _client(options)

    # Just dumping the data as JSON causes issues with bytes:
    # https://github.com/saltstack/salt/issues/59012
    # @FIXMEMAYBE
    mappings = {
        # These are special-purpose mappings, otherwise
        # typical `nested:value` notation can be used.
        "full_ret": lambda x: json.dumps({k: v for k, v in x.items() if k != "return"}),
        "module": lambda x: x["fun"].split(".")[0],
    }

    prj = Projector(mappings, ret)
    fmt = options["function_point_fmt_fun"].get(ret["fun"])

    if ret["fun"] in STATE_FUNCTIONS:
        ssum = StateSum(ret)
        mappings["states_succeeded"] = ssum.succeeded
        mappings["states_failed"] = ssum.failed
        mappings["states_total"] = ssum.total
        # fmt for state.[apply|highstate|sls]
        # alternatives: allow per module or matching regex
        # (former might be incorrect, latter expensive)
        fmt = fmt or options["function_point_fmt_state"]

    fmt = fmt or options["function_point_fmt"]

    record = {
        "measurement": fmt.get("measurement", DEFAULT_FUNCTION_POINT["measurement"]),
        # tag values must be strings
        "tags": {
            k: str(v)
            for k, v in _project(
                prj,
                fmt.get("tags", DEFAULT_FUNCTION_POINT["tags"]),
            ).items()
        },
        "fields": _project(
            prj,
            fmt.get("fields", DEFAULT_FUNCTION_POINT["fields"]),
        ),
        "time": datetime.utcnow(),
    }

    write_api = client.write_api(write_options=SYNCHRONOUS)

    try:
        write_api.write(options["bucket"], record=record)
    except InfluxDBError as err:
        log.exception(f"Failed to store return: {err}")


def event_return(events):
    """
    Write event to an InfluxDB bucket
    """
    options = _get_options()
    client = _client(options)
    mappings = {
        "master": __opts__["id"],
    }

    def error_callback(conf, _, exception):
        log.error(f"Could not write batch {conf}: {exception}")

    with client.write_api(error_callback=error_callback) as _write:
        for event in events:
            # Doing the filtering after connecting might be suboptimal
            # if most events are filtered @FIXME?
            if (
                _re_match(options["events_blocklist"], event["tag"])
                or options["events_allowlist"]
                and not _re_match(options["events_allowlist"], event["tag"])
            ):
                log.info(
                    f"Skipping InfluxDB2 event return for event {event['tag']} because it is filtered"
                )
                continue
            prj = Projector(mappings, event)
            fmt = options["event_point_fmt_tag"].get(
                event["tag"], options["event_point_fmt"]
            )
            record = {
                "measurement": fmt.get(
                    "measurement", DEFAULT_EVENT_POINT["measurement"]
                ),
                # tag values must be strings
                "tags": {
                    k: str(v)
                    for k, v in _project(
                        prj,
                        fmt.get("tags", DEFAULT_EVENT_POINT["tags"]),
                    )
                },
                "fields": _project(
                    prj,
                    fmt.get("fields", DEFAULT_EVENT_POINT["fields"]),
                ),
                "time": datetime.utcnow(),
            }
            _write(options["bucket"], record=record)


def _client(options):
    """
    Return an influxdb client object
    """
    client_kwargs = {k: options.get(k) for k in ("url", "org", "token")}

    try:
        with influxdb_client.InfluxDBClient(**client_kwargs) as client:
            yield client
    except InfluxDBError as err:
        log.exception(err)


def _re_match(patterns, data):
    """
    Given a list of patterns, check if data matches any.
    Used for allowlist/blocklist support for functions and events
    """
    matches = []

    for ptrn in patterns:
        try:
            match = bool(re.match(ptrn, data))
        except Exception as err:
            log.exception(f"Invalid regular expression: {err}")
            match = False
        matches.append(match)

    if not matches:
        return False
    return any(matches)


def _project(projector, structure):
    """
    Render a dict template with a Projector object.
    It should be possible to get to the raw values, hence
    try if a key is just ``{val}`` before running format
    on the possible format string.
    """
    ret = {}
    for key, val in structure.items():
        try:
            # raw values if not a format string other than ~ "{value}"
            ret[key] = projector[val[1:-1]]
            continue
        except KeyError:
            pass
        try:
            # custom mappings and top-level keys only
            ret[key] = val.format(**projector)
            continue
        except (KeyError, ValueError):
            pass
        log.warning(f"Failed rendering point template for {key}: '{val}'")

    return ret


class Projector(Mapping):
    """
    Given a mapping of template variables and a dictionary of data,
    render a dict template. Used for ``tags`` and ``fields`` templating.
    """

    def __init__(self, mappings, data):
        self.mappings = mappings
        self.data = data

    def __getitem__(self, key):
        if key in self.mappings:
            return self._ensure_type(self.mappings[key](self.data))

        trav = salt.utils.data.traverse_dict_and_list(self.data, key)
        if trav is not None:
            return self._ensure_type(trav)
        raise KeyError(key)

    def __iter__(self):
        for item in list(self.mappings) + list(self.data):
            yield item

    def __len__(self):
        return len(self.mappings)

    def _ensure_type(self, val):
        """
        Field values should be integers, floats, strings or booleans.
        If they are not, dump them to a json string.
        This might have issues with byte returns for example, but is
        the way most of the returners do it atm.
        https://github.com/saltstack/salt/issues/59012
        """
        if isinstance(val, (int, float, str, bool)):
            return val
        return json.dumps(val)


class StateSum:
    """
    Instead of using separate lambdas for summing different aspects,
    do it once for all possible attributes.
    """

    def __init__(self, data):
        self.data = data
        self.succeeded = None
        self.failed = None
        self.total = None

    def succeeded(self, _):
        """
        Return the sum of succeeded state runs,
        where None results from tests count as succeeded
        """
        if self.succeeded is None:
            self._sum()
        return self.succeeded

    def failed(self, _):
        """
        Return the sum of failed state runs
        """
        if self.failed is None:
            self._sum()
        return self.failed

    def total(self, _):
        """
        Return the sum of state runs regardless of result
        """
        if self.total is None:
            self._sum()
        return self.total

    def _sum(self):
        failed = succeeded = total = 0
        for single in self.data["return"].values():
            total += 1
            if single["result"] is False:
                failed += 1
            else:
                succeeded += 1
        self.failed = failed
        self.succeeded = succeeded
        self.total = total
