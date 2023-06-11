r"""
Return data to an InfluxDB v2 server.

Note that this returner is not intended nor working as a job cache,
but for metrics collection about Salt internals.

:depends: ``influxdb-client`` Python module

Configuration
-------------

You can set it as a default returner in the minion configuration

.. code-block:: yaml

    # for everything except scheduled tasks
    return:
      - influxdb2

    # for scheduled tasks
    schedule_returners:
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
This crutch can be removed once issue #54123 is closed.

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
      # Tags are keys (regular expressions), values as in the default transformation.
      # If a necessary value is unset, it will be taken from the default one.
      # The order matters - only the first match will be processed.
      # You can also map one event to a list of several templates. In this case,
      # there is a third key called ``match``, which should be a dictionary of
      # key access strings (like ``data:args:tgt_type``) to a single regular expression each.
      # The first template for which all conditions are met will be chosen as the actual template.
      # If a template in this list does not include a ``match`` key, it will be chosen
      # as the default template if none of the other ones match.
      event_point_fmt_tag:
        my/custom/event:
          tags:
            minion: '{data:id}'
            tag: '{tag}'
            event_type: custom_event
        my/other/event:
          - match:
              'data:id': '(db|app)\d+'
              'type': 'special'
            tags:
              event_type: special_type
              minion: '{data:id}'
          - tags:
              event_type: normal_type
              minion: '{data:id}'

      # Default transformation for returns
      function_point_fmt:
        measurement: returns
        fields:
          jid: '{jid}'
          return: '{ret_str}'
          retcode: '{retcode}'
        tags:
          fun: '{fun}'
          minion: '{id}'
          salt_version: '{salt_version}'

      # Transformations for particular functions
      # Functions are keys (regular expressions), values as in the default transformation
      # If a necessary value is unset, it will be taken from the default one.
      # The order matters - only the first match will be processed.
      # This has the highest priority, before state-specific and default transformations.
      function_point_fmt_fun: {}

      # Transformation for `state.[apply|highstate|sls]` in particular
      function_point_fmt_state:
        measurement: returns
        fields:
          jid: '{jid}'
          retcode: '{retcode}'
          states_failed: '{states_failed}'
          states_total: '{states_total}'
          states_changed: '{states_changed}'
          states_duration: '{states_duration}'
        tags:
          fun: '{fun}'
          minion: '{id}'
          salt_version: '{salt_version}'
          state_name: '{state_name}'

The templates behave as Python format strings.
In the special case where the template is just a single variable access (``{var}``),
the raw value is returned (if it is compatible with InfluxDB for the scope),
otherwise it is dumped as a JSON string.

You can also traverse the return dict like ``{return:value}``. This works for both
raw values and Python format strings.

.. note::

    * Using ``{return[value]}`` always renders as a string, since it relies on
      Python string formatting behavior.

    * Note the quotes around the YAML values!

Depending on the type, there are miscellaneous template vars available.

General
^^^^^^^
full_ret
    full return dict, excluding ``result``

ret_str
    return cast to str

module
    the module part of ``fun``

salt_version
    The current version of Salt as reported in grains, split on the first ``+``.


State functions
^^^^^^^^^^^^^^^
All general vars are available.

state_name
    The name of the state that was run. ``highstate`` for
    highstates, otherwise the first positional argument to
    state.apply/sls.

states_succeeded
    Number of succeeded states during this state run.

states_succeeded_pct
    Percentage of succeeded states during this state run.

states_failed
    Number of failed states during this state run.

states_failed_pct
    Percentage of failed states during this state run.

states_changed
    Number of states reporting changes during this state run.

states_changed_pct
    Percentage of states reporting changes during this state run.

states_total
    Number of all states during this state run.

states_duration
    Sum of all reported invididual state durations.

Events
^^^^^^
master
    ``opts["id"]`` of the master posting the event

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

.. _influxdb2-metrics-config:
"""

import copy
import logging
import re
from datetime import datetime

import influxdb2util
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
            "return": "{ret_str}",
            "retcode": "{retcode}",
        },
        "tags": {
            "fun": "{fun}",
            "minion": "{id}",
            "salt_version": "{salt_version}",
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
            "event_type": "unknown",
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
            "states_changed": "{states_changed}",
            "states_duration": "{states_duration}",
        },
        "tags": {
            "fun": "{fun}",
            "state": "{state_name}",
            "minion": "{id}",
            "salt_version": "{salt_version}",
        },
    }
)

INBUILT_EVENT_POINTS = immutabletypes.freeze(
    {
        r"\w+\.\w+": {
            "tags": {
                "tag": "{tag}",
                "event_type": "failed_state",
                "state_id": "{data:__id__}",
                "sls": "{data:__sls__}",
            },
        },
        "_salt_error": {
            "tags": {
                "tag": "{tag}",
                "event_type": "daemon_exception",
                "minion": "{data:id}",
            },
        },
        "salt/auth": {
            "tags": {
                "tag": "{tag}",
                "act": "{data:act}",
                "event_type": "auth",
                "minion": "{data:id}",
            },
        },
        r"salt/job/\d+/new": {
            "tags": {
                "tag": "{tag}",
                "event_type": "job",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "tgt": "{data:tgt}",
                "user": "{data:user}",
            },
        },
        r"salt/job/\d+/ret/[^/\\]+": {
            "tags": {
                "tag": "{tag}",
                "event_type": "job",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "success": "{data:success}",
                "minion": "{data:id}",
            },
        },
        "salt/key": {
            "tags": {
                "tag": "{tag}",
                "act": "{data:act}",
                "event_type": "key",
                "minion": "{data:id}",
                "success": "{data:result}",
            },
        },
        "key": {
            "tags": {
                "tag": "{tag}",
                "event_type": "key",
            },
        },
        r"salt/minion/[^/\\]+/start": {
            "tags": {
                "tag": "{tag}",
                "event_type": "minion_start",
                "minion": "{data:id}",
            },
        },
        r"minion/refresh/[^/\\]+": {
            "tags": {
                "tag": "{tag}",
                "event_type": "minion_data_refresh",
                "minion": "{data:Minion data cache refresh}",
            },
        },
        r"salt/run/\d+/args": [
            {
                "match": {
                    "data:type": "(state|function)",
                },
                "tags": {
                    "tag": "{tag}",
                    "event_type": "orch_{data:type}",
                    "tgt": "{data:tgt}",
                    "tgt_type": "{data:args:tgt_type}",
                    "ssh": "{data:args:ssh}",
                    "name": "{data:name}",
                },
            },
            {
                "tags": {
                    "tag": "{tag}",
                    "event_type": "orch_{data:type}",
                    "name": "{data:name}",
                },
            },
        ],
        r"salt/run/\d+/new": {
            "tags": {
                "tag": "{tag}",
                "event_type": "run",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "user": "{data:user}",
            },
        },
        r"salt/run/\d+/ret": {
            "tags": {
                "tag": "{tag}",
                "event_type": "run",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "user": "{data:user}",
                "success": "{data:success}",
            },
        },
        r"salt/wheel/\d+/new": {
            "tags": {
                "tag": "{tag}",
                "event_type": "wheel",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "user": "{data:user}",
            },
        },
        r"salt/wheel/\d+/ret": {
            "tags": {
                "tag": "{tag}",
                "event_type": "wheel",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "user": "{data:user}",
                "success": "{data:success}",
            },
        },
        r"vault/cache/\w+/clear": {
            "tags": {
                "tag": "{tag}",
                "event_type": "vault_expire",
            },
        },
        r"vault/security/unwrapping/error": {
            "tags": {
                "tag": "{tag}",
                "event_type": "vault_unwrap",
                "url": "{data:url}",
                "expected": "{data:expected}",
            },
        },
    }
)

DEFAULT_EVENTS_BLOCKLIST = immutabletypes.freeze(
    [
        # By default, do not include events that are only tagged with a jid (purpose?)
        r"\d{20}",
        # Minion data refreshes cause a lot of noise
        r"minion/refresh/[^/\\]+",
    ]
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
        "events_blocklist": DEFAULT_EVENTS_BLOCKLIST,
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
    for tag, conf in INBUILT_EVENT_POINTS.items():
        if tag not in _options["event_point_fmt_tag"]:
            _options["event_point_fmt_tag"][tag] = copy.deepcopy(conf)
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

    mappings = {
        # These are special-purpose mappings, otherwise
        # typical `nested:value` notation can be used.
        "module": lambda x: x["fun"].split(".")[0],
        "ret_str": lambda x: str(x["return"]),
        # Just dumping the data as JSON causes issues with bytes:
        # https://github.com/saltstack/salt/issues/59012
        # @FIXMEMAYBE
        "full_ret": lambda x: json.dumps({k: v for k, v in x.items() if k != "return"}),
        "salt_version": _salt_version,
    }

    fmt = None
    if options["function_point_fmt_fun"]:
        try:
            # function-specific formats take precedence before state-specific and global
            fmt = influxdb2util.RegexDict(
                options["function_point_fmt_fun"], compile_ptrn=False
            )[ret["fun"]]
        except KeyError:
            pass

    # State returns can render more specific insights.
    # ret["return"] can be a list in case rendering the highstate failed,
    # in that case skip treating it as a state run
    if ret["fun"] in STATE_FUNCTIONS and isinstance(ret["return"], dict):
        ssum = StateSum(ret)
        mappings["states_total"] = ssum.total
        mappings["states_succeeded"] = ssum.succeeded
        mappings["states_succeeded_pct"] = ssum.succeeded_pct
        mappings["states_failed"] = ssum.failed
        mappings["states_failed_pct"] = ssum.failed_pct
        mappings["states_changed"] = ssum.changed
        mappings["states_changed_pct"] = ssum.changed_pct
        mappings["states_duration"] = ssum.duration
        mappings["state_name"] = (
            lambda x: "highstate"
            if x["fun"] == "state.highstate"
            or (
                x["fun"] == "state.apply"
                and (not ret["fun_args"] or "=" in ret["fun_args"][0])
            )
            else ret["fun_args"][0]
        )
        # fmt for state.[apply|highstate|sls]
        # alternatives: allow per module or matching regex
        # (former might be incorrect, latter expensive)
        fmt = fmt or options["function_point_fmt_state"]

    # in case no more specific format was defined, render default one
    fmt = fmt or options["function_point_fmt"]

    prj = influxdb2util.Projector(mappings, ret)
    record = {
        "measurement": fmt.get("measurement", DEFAULT_FUNCTION_POINT["measurement"]),
        # tag values must be strings
        "tags": {
            k: str(v)
            for k, v in prj(fmt.get("tags", DEFAULT_FUNCTION_POINT["tags"])).items()
        },
        "fields": prj(fmt.get("fields", DEFAULT_FUNCTION_POINT["fields"])),
        "time": datetime.utcnow(),
    }

    write_api = client.write_api(write_options=SYNCHRONOUS)

    try:
        write_api.write(options["bucket"], record=record)
    except InfluxDBError as err:
        log.error(f"Failed to store return: {err}")


def event_return(events):
    """
    Write events to an InfluxDB bucket
    """
    try:
        event_allow_ckey = "_influxdb2_event_allow"
        event_block_ckey = "_influxdb2_event_block"
        event_map_ckey = "_influxdb2_event_map"

        options = _get_options()
        client = _client(options)
        mappings = {
            "master": __opts__["id"],
        }

        # This whole function operates under the assumption that the event returner
        # process is long-lived @TODO check that that's the case
        if event_allow_ckey not in __context__:
            __context__[event_allow_ckey] = re.compile(
                _join_regex(options["events_allowlist"] or [".*"])
            )

        filtered = [
            evt for evt in events if __context__[event_allow_ckey].fullmatch(evt["tag"])
        ]

        if options["events_blocklist"]:
            if event_block_ckey not in __context__:
                __context__[event_block_ckey] = re.compile(
                    _join_regex(options["events_blocklist"])
                )
            filtered = [
                evt
                for evt in events
                if not __context__[event_block_ckey].fullmatch(evt["tag"])
            ]

        if not filtered:
            return

        if event_map_ckey not in __context__:
            if ".*" not in options["event_point_fmt_tag"]:
                options["event_point_fmt_tag"][".*"] = DEFAULT_EVENT_POINT
            __context__[event_map_ckey] = influxdb2util.RegexDict(
                options["event_point_fmt_tag"]
            )

        def error_callback(conf, _, exception):
            log.error(f"Could not write batch {conf}: {exception}")

        with client.write_api(error_callback=error_callback) as _write_client:
            for event in filtered:
                try:
                    prj = influxdb2util.Projector(mappings, event)
                    fmt = __context__[event_map_ckey][event["tag"]]
                    try:
                        timestamp = datetime.fromisoformat(event["data"].pop("_stamp"))
                    except KeyError:
                        timestamp = datetime.utcnow()
                    # Some events carry very different data and can only be differentiated
                    # using those (looking at you, orchestration). It would be possible to
                    # just map everything possible and rely on None return values, but
                    # that a) is dirty and b) causes lots of warning logs.
                    if isinstance(fmt, list):
                        default_fmt = {}
                        for match_fmt in fmt:
                            if "match" not in match_fmt:
                                default_fmt = match_fmt
                                continue
                            for key, pattern in match_fmt["match"].items():
                                key_data = salt.utils.data.traverse_dict_and_list(
                                    event, key, default=KeyError
                                )
                                if key_data is KeyError:
                                    break
                                if not re.fullmatch(pattern, key_data):
                                    break
                            else:
                                fmt = match_fmt
                                break
                        else:
                            fmt = default_fmt
                    record = {
                        "measurement": fmt.get(
                            "measurement", DEFAULT_EVENT_POINT["measurement"]
                        ),
                        # tag values must be strings
                        "tags": {
                            k: str(v) if v is not None else ""
                            for k, v in prj(
                                fmt.get("tags", DEFAULT_EVENT_POINT["tags"])
                            ).items()
                        },
                        "fields": prj(fmt.get("fields", DEFAULT_EVENT_POINT["fields"])),
                        "time": timestamp,
                    }
                    _write_client.write(options["bucket"], record=record)
                except Exception as err:
                    log.exception(err)
    except Exception as err:
        log.exception(err)


def _client(options):
    """
    Return a client for a specific url/org/token combination
    """
    # TODO: Maybe just instantiate a new client per request instead of
    # this magic, at least for the returner?
    ckey = "influxdb2_conn"
    global __context__
    __context__ = __context__ or {}

    def conn(url, org, token):
        try:
            with influxdb_client.InfluxDBClient(
                url=client_kwargs[0], org=client_kwargs[1], token=client_kwargs[2]
            ) as client:
                while True:
                    yield client
        except InfluxDBError as err:
            log.error(err)
            raise
        finally:
            try:
                __context__[ckey].pop(client_kwargs)
            except (AttributeError, TypeError):
                pass

    client_kwargs = tuple(options.get(k) for k in ("url", "org", "token"))

    if ckey not in __context__:
        __context__[ckey] = {}

    if client_kwargs not in __context__[ckey]:
        # ensure the generator is not garbage-collected too early
        __context__[ckey][client_kwargs] = conn(*client_kwargs)

    return next(__context__[ckey][client_kwargs])


class StateSum:
    """
    Instead of using separate lambdas for summing different aspects,
    do it once for all possible attributes.
    """

    def __init__(self, data):
        self.data = data
        self._succeeded = None
        self._failed = None
        self._total = None
        self._changed = None
        self._duration = None

    def succeeded(self, _):
        """
        Return the sum of succeeded state runs,
        where None results from tests count as succeeded
        """
        if self._succeeded is None:
            self._sum()
        return self._succeeded

    def succeeded_pct(self, _):
        """
        Return the percentage of state runs that reported success,
        where None from test runs counts as succeeded
        """
        if self._succeeded is None:
            self._sum()
        return round(self._succeeded / self._total * 100, 2)

    def failed(self, _):
        """
        Return the sum of failed state runs
        """
        if self._failed is None:
            self._sum()
        return self._failed

    def failed_pct(self, _):
        """
        Return the percentage of state runs that reported failure
        """
        if self._failed is None:
            self._sum()
        return round(self._failed / self._total * 100, 2)

    def total(self, _):
        """
        Return the sum of state runs regardless of result
        """
        if self._total is None:
            self._sum()
        return self._total

    def changed(self, _):
        """
        Return the sum of state runs that reported changes
        """
        if self._changed is None:
            self._sum()
        return self._changed

    def changed_pct(self, _):
        """
        Return the percentage of state runs that reported changes
        """
        if self._changed is None:
            self._sum()
        return round(self._changed / self._total * 100, 2)

    def duration(self, _):
        """
        Return the sum of all reported state run durations
        """
        if self._duration is None:
            self._sum()
        return self._duration

    def _sum(self):
        failed = succeeded = total = changed = duration = 0
        for single in self.data.get("return", {}).values():
            total += 1
            if single["result"] is False:
                failed += 1
            else:
                succeeded += 1
            if single.get("changes"):
                changed += 1
            duration += single.get("duration", 0)
        self._failed = failed
        self._succeeded = succeeded
        self._total = total
        self._changed = changed
        self._duration = round(duration, 2)


def _salt_version(_):
    try:
        version = __grains__["saltversion"]
    except (NameError, KeyError):
        import salt.version

        version = salt.version.__version__
    return version.split("+", maxsplit=1)[0]


def _re_match(patterns, data):
    """
    Given a list of patterns, check if data matches any.
    Used for allowlist/blocklist support for functions.
    Events are processed separately in a single compiled long-lived pattern.

    Note that if a single pattern is invalid, this always
    returns False.
    """
    try:
        return bool(re.fullmatch(_join_regex(patterns), data))
    except Exception as err:
        log.error(f"Invalid regular expression: {err}")
    return False


def _join_regex(patterns):
    return "|".join(f"({ptrn})" for ptrn in patterns)
