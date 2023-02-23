import re

from salt.exceptions import CommandExecutionError, SaltInvocationError


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
