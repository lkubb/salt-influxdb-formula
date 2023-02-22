import re

from salt.exceptions import SaltInvocationError, CommandExecutionError


class Task:
    """
    Represents task settings. The influxdb library objects do not expose
    task options as attributes.
    """

    def __init__(self, name, query, every=None, cron=None, offset=None):
        self.name = name
        self.query = query
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
        options = 'option task = {{{}}}'.format(", ".join(f"{k}: {v}" if k not in ("name", "cron") else f'{k}: "{v}"' for k, v in task_opts.items()))
        return options + "\n\n" + self.query

    @classmethod
    def from_flux(cls, flux):
        try:
            options = re.findall(r"option task = {(.*?)}", flux)[0]
        except IndexError:
            raise CommandExecutionError("Could not parse task options")
        query = "\n".join(re.split(r"option task = {.*?}", flux, maxsplit=1)).strip()
        parsed = dict(re.findall(r'(\w+): "?(\w+)"?', options))
        return cls(query=query, **parsed)


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
