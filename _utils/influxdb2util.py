import json
import logging
import re
import string
from collections.abc import Mapping

import salt.utils.data
from salt.exceptions import CommandExecutionError, SaltInvocationError

log = logging.getLogger(__name__)


class Task:
    """
    Represents task settings. The influxdb library objects do not expose
    task options as attributes.
    """

    def __init__(self, name, query, every=None, cron=None, offset=None):
        self.name = name
        if isinstance(query, str):
            query = FluxQuery.from_string(query)
        self.query = str(query)
        self.every = every
        self.cron = cron
        self.offset = offset

    def to_flux(self):
        task_opts = {"name": self.name}
        if self.every is not None:
            task_opts["every"] = self.every
        if self.cron is not None:
            task_opts["cron"] = self.cron
        if self.offset is not None:
            task_opts["offset"] = self.offset
        query = FluxQuery.from_string(self.query)
        # imports need to precede the option task statement
        imports = query.imports
        if imports:
            imports += "\n\n"
        options = "option task = {{{}}}".format(
            ", ".join(
                f"{k}: {v}" if k not in ("name", "cron") else f'{k}: "{v}"'
                for k, v in task_opts.items()
            )
        )
        return imports + options + "\n\n" + query.query + "\n"

    @classmethod
    def from_flux(cls, flux):
        try:
            options = re.findall(r"option task = {(.*?)}", flux)[0]
        except IndexError:
            raise CommandExecutionError("Could not parse task options")
        query = "\n".join(
            line for line in flux.splitlines() if not line.startswith("option task = {")
        ).strip()
        parsed = dict(re.findall(r'(\w+): "?([^,"]+)"?', options))
        return cls(query=query, **parsed)


class FluxQuery:
    def __init__(self, query, imports=""):
        self.query = query.strip()
        self.imports = imports.strip()

    def __str__(self):
        imports = self.imports
        if imports:
            imports += "\n\n"
        return imports + self.query + "\n"

    @classmethod
    def from_string(cls, query):
        imports = re.findall(r'^import ".*"$', query, flags=re.MULTILINE)
        query_without_imports = "\n".join(
            line for line in query.splitlines() if line not in imports
        ).strip()
        return cls(query_without_imports, imports="\n".join(imports))


def timestring_map(val):
    """
    Turn a time string (like ``60m``) into an int with seconds as a unit.
    """
    if val is None:
        return val
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(val)
    except ValueError:
        pass
    if not isinstance(val, str):
        raise SaltInvocationError("Expected integer or time string")
    if not re.match(r"^\d+(?:\.\d+)?[smhd]$", val):
        raise SaltInvocationError(f"Invalid time string format: {val}")
    raw, unit = float(val[:-1]), val[-1]
    if unit == "s":
        return raw
    raw *= 60
    if unit == "m":
        return raw
    raw *= 60
    if unit == "h":
        return raw
    raw *= 24
    if unit == "d":
        return raw
    raise RuntimeError("This path should not have been hit")


class RegexDict(Mapping):
    """
    A dictionary whose keys are represented by regular expressions.
    Key access matches the first of possibly multiple regular expressions
    and returns the associated dictionary.

    This is used by the event returner to match event tags to custom
    data output.
    """

    def __init__(self, mappings, compile_ptrn=True):
        """
        mappings
            Ordered (!) mapping of regular expressions to return data.

        compile_ptrn
            Compile the pattern for multi-use. Defaults to True.
        """
        self._patterns = list(mappings)
        self._data = [mappings[ptrn] for ptrn in self._patterns]
        self._regex = "|".join(f"({ptrn})" for ptrn in self._patterns)
        if compile_ptrn:
            self._ptrn = re.compile(self._regex)
        else:
            self._ptrn = None

    def __getitem__(self, key):
        if self._ptrn is not None:
            match = self._ptrn.fullmatch(key)
        else:
            match = re.fullmatch(self._regex, key)
        if match is not None:
            return self._data[match.lastindex - 1]
        raise KeyError(key)

    def __iter__(self):
        yield from self._patterns

    def __len__(self):
        return len(self._patterns)


class Projector(Mapping):
    """
    Given a mapping of template variables to processing functions
    and a dictionary of data, render a dict template.
    Used for ``tags`` and ``fields`` templating.

    If raw values cannot be represented by InfluxDB, they will
    be encoded as JSON strings.
    """

    def __init__(self, mappings, data, formatter=None):
        """
        mappings
            Dict of template keys to functions: fn(data) -> Any
            that should be evaluated (lazily).

        data
            Dictionary of values that should be processed according
            to a template. This will be passed to the requested functions
            in ``mappings`` and its raw values will be available as well.
        """
        self.mappings = mappings
        self.data = data
        if formatter is None:
            formatter = JsonFormatter()
        self.formatter = formatter
        self._flattened = None

    def __getitem__(self, key):
        """
        If a key refers to a function, return its output,
        """
        if key in self.mappings:
            return self._ensure_type(self.mappings[key](self.data))

        trav = salt.utils.data.traverse_dict_and_list(self.data, key, default=KeyError)
        if trav is not KeyError:
            return trav
        raise KeyError(key)

    def _ensure_type(self, val):
        """
        Field values should be integers, floats, strings or booleans.
        If they are not, dump them to a json string.
        This might have some issues (byte returns are OK though), but is
        the way most of the returners do it atm.
        https://github.com/saltstack/salt/issues/59012
        """
        if isinstance(val, (int, float, str, bool)):
            return val
        return json.dumps(val, cls=BytesEncoder)

    def __call__(self, structure):
        """
        Render a dict template.

        Template variables can be

          * ``mapping`` keys that run associated functions on the data
          * ``data`` top-level keys
          * ``data`` deeply nested keys (``{some:deeply:nested:value}``)

        If the raw value is desired – not its json/string representation – ensure
        the "template" only consists of the access to the single key.

        structure
            Dictionary of keys to templated values to be rendered.
        """
        ret = {}
        for key, val in structure.items():
            if "{" not in val:
                # allow for static values
                ret[key] = val
                continue
            try:
                try:
                    # It should be possible to get to the raw values, hence
                    # try if a key is just ``{<key>}`` before running format
                    # on the possible format string, which casts everything to a string.
                    ret[key] = self._ensure_type(self[val[1:-1]])
                    continue
                except KeyError:
                    pass
                # do not use .format since **kwargs evaluates all mappings
                ret[key] = self.formatter.vformat(val, args=(), kwargs=self)
                continue
            except Exception as err:  # pylint: disable=broad-except
                log.warning(
                    f"Failed rendering point template for {key}: '{val}'. "
                    f"{type(err).__name__}: {err}"
                )
            ret[key] = None

        return ret

    def __iter__(self):
        for item in list(self.mappings) + self._flatten_data():
            yield item

    def __len__(self):
        return len(self.mappings) + len(self._flatten_data())

    def _flatten_data(self):
        if self._flattened is None:

            def key_iter(cur, prefix):
                prefixes = []
                for key, val in cur.items():
                    prefixes.append(f"{prefix}{key}")
                    if isinstance(val, dict):
                        prefixes.extend(key_iter(f"{key}:", val))
                return prefixes

            self._flattened = key_iter(self.data, "")
        return self._flattened


class JsonFormatter(string.Formatter):
    def parse(self, format_string):
        """
        Monkeypatch the ``:`` format_spec syntax.
        Otherwise, formatting does not work with subdict access.
        Changing to a different subdict key delimiter would be possible,
        but this is more intuitive and format_spec should not be used here anyways.
        """
        for parsed in super().parse(format_string):
            if parsed[2]:
                parsed = parsed[0], ":".join((parsed[1], parsed[2])), "", parsed[3]
            yield parsed

    def format_field(self, value, format_spec):
        if isinstance(value, (int, float, str, bool)):
            return super().format_field(value, format_spec)
        return json.dumps(value, cls=BytesEncoder)


class BytesEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, bytes):
            # Dump as Python string-casted bytes and cut b''. for now.
            # Alternatively, this could use .hex() or base64.
            return str(o)[2:-1]
        return json.JSONEncoder.default(self, o)
