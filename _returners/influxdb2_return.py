"""
Return data to an InfluxDB v2 server.

Note that this returner is not intended nor working as a job cache,
but for metrics collection about Salt internals.

:depends: `influxdb-client` Python module

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
      event_point_fmt_tag: {}

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

The templates values can be a simple ``{var}``, for which the raw value of the
return dictionary is returned if it is compatible with InfluxDB for the scope, otherwise
it is dumped as a JSON string. For this simple case, you can even traverse the
return dict like ``{return:value}``. Note the quotes around the YAML values!

The template values can also be Python format strings, in which case you cannot
traverse dictionaries and only have access to the top keys.

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
    The current version of Salt as reported in grains, split on the first "+".


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
from collections.abc import Mapping
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
        "salt/auth": {
            "measurement": "events",
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
            }
        },
        r"salt/job/\d+/ret/[^/\\]+": {
            "tags": {
                "tag": "{tag}",
                "event_type": "job",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "success": "{data:success}",
            }
        },
        r"salt/run/\d+/new": {
            "tags": {
                "tag": "{tag}",
                "event_type": "run",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "user": "{data:user}",
            }
        },
        r"salt/run/\d+/ret": {
            "tags": {
                "tag": "{tag}",
                "event_type": "run",
                "jid": "{data:jid}",
                "fun": "{data:fun}",
                "user": "{data:user}",
                "success": "{data:success}",
            }
        },
        r"minion/refresh/[^/\\]+": {
            "tags": {
                "tag": "{tag}",
                "event_type": "minion_data_refresh",
            }
        },
    }
)

STATE_FUNCTIONS = ("state.apply", "state.highstate", "state.sls")
EVENT_MAP = None
EVENT_ALLOW_REGEX = None
EVENT_BLOCK_REGEX = None


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
        "event_point_fmt_tag": copy.deepcopy(INBUILT_EVENT_POINTS),
        "events_allowlist": [],
        # By default, do not include events that are only tagged with a jid (purpose?)
        "events_blocklist": [r"\d{20}"],
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

    prj = Projector(mappings, ret)
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
        log.error(f"Failed to store return: {err}")


def event_return(events):
    """
    Write event to an InfluxDB bucket
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
                "|".join(
                    f"({ptrn})" for ptrn in (options["events_allowlist"] or [".*"])
                )
            )

        filtered = [
            evt for evt in events if __context__[event_allow_ckey].fullmatch(evt["tag"])
        ]

        if options["events_blocklist"]:
            if event_block_ckey not in __context__:
                __context__[event_block_ckey] = re.compile(
                    "|".join(f"({ptrn})" for ptrn in options["events_blocklist"])
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
                prj = Projector(mappings, event)
                fmt = __context__[event_map_ckey][event["tag"]]
                try:
                    timestamp = datetime.fromisoformat(event["data"].pop("_stamp"))
                except KeyError:
                    timestamp = datetime.utcnow()
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
                        ).items()
                    },
                    "fields": _project(
                        prj,
                        fmt.get("fields", DEFAULT_EVENT_POINT["fields"]),
                    ),
                    "time": timestamp,
                }
                _write_client.write(options["bucket"], record=record)
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
            log.error(f"Invalid regular expression: {err}")
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
        if "{" not in val:
            # allow for static values
            ret[key] = val
            continue
        try:
            try:
                # raw values if not a format string other than ~ "{value}"
                ret[key] = projector[val[1:-1]]
                continue
            except KeyError:
                pass
            # custom mappings and top-level keys only
            ret[key] = val.format(**projector)
            continue
        except Exception as err:  # pylint: disable=broad-except
            log.warning(
                f"Failed rendering point template for {key}: '{val}'. "
                f"{err.__class__.__name__}: {err}"
            )
        ret[key] = None

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
    except (NameError, IndexError):
        import salt.version

        version = salt.version.__version__
    return version.split("+", maxsplit=1)[0]
