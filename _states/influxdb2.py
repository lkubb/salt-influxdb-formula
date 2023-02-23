"""
Manage an InfluxDB v2 server.

:depends: ``influxdb-client`` Python module

For configuration instructions, the see ref:`execution module docs <influxdb2-setup>`.
Mind that all functions take additional keyword arguments to override
the configured/default parameters:

influxdb_profile
    By default, will pull configuration using ``salt["config.get"]("influxdb2")``.
    Override the configuration key.

influxdb_url
    Override the configured URL. If not configured, defaults to ``http://localhost:8086``

influxdb_token
    Override the configured token. If unconfigured, needs to be set.

influxdb_org
    Override the configured default organization. If not configured, defaults to ``salt``.
"""

from influxdb2util import FluxQuery, Task, timestring_map
from salt.exceptions import CommandExecutionError, SaltInvocationError

__virtualname__ = "influxdb2"


def __virtual__():
    """
    Only load if influxdb lib is present
    """
    try:
        __salt__["influxdb2.query"]
    except KeyError:
        return (
            False,
            "The influxdb2 execution module was not loaded",
        )
    return __virtualname__


def bucket_present(name, expire="30d", description="", org=None, **kwargs):
    """
    Ensure an InfluxDB v2 bucket is present.

    name
        Name of the bucket to manage.

    expire
        Set data expiration time, either as an integer (seconds) or a
        time string like ``6h``. 0 disables expiration. Defaults to ``30d``.

    description
        A description for the bucket.

    org
        Override the default organization set in the configuration.
    """
    ret = {
        "name": name,
        "comment": "The bucket is already in the correct state",
        "changes": {},
        "result": True,
    }

    try:
        expire = timestring_map(expire)
        existing = __salt__["influxdb2.fetch_bucket"](name, org=org, **kwargs)
        changes = {}
        if existing is None:
            verb = "create"
            changes["created"] = name
        else:
            verb = "update"
            if existing["description"] != description and (
                description or existing["description"] is not None
            ):
                changes["description"] = {
                    "old": existing["description"],
                    "new": description,
                }
            if (
                len(existing["retention_rules"]) != 1
                or existing["retention_rules"][0]["type"] != "expire"
                or existing["retention_rules"][0]["every_seconds"] != expire
            ):
                changes["retention_rules"] = {
                    "old": existing["retention_rules"],
                    "new": {"type": "expire", "every_seconds": expire},
                }
        if not changes:
            return ret
        ret["changes"] = changes

        if __opts__["test"]:
            ret["result"] = None
            ret["comment"] = f"Would have {verb}d the bucket"
            return ret

        __salt__[f"influxdb2.{verb}_bucket"](
            name, expire=expire, description=description, org=org, **kwargs
        )
        ret["comment"] = f"Successfully {verb}d the bucket"

    except (CommandExecutionError, SaltInvocationError) as err:
        ret["result"] = False
        ret["comment"] = str(err)
        ret["changes"] = {}
    return ret


def bucket_absent(name, org=None, **kwargs):
    """
    Ensure an InfluxDB v2 bucket is absent.

    name
        Name of the bucket to ensure absence of.

    org
        Override the default organization set in the configuration.
    """
    ret = {
        "name": name,
        "comment": "The bucket is already absent",
        "changes": {},
        "result": True,
    }

    try:
        existing = __salt__["influxdb2.fetch_bucket"](name, org=org, **kwargs)
        if existing is None:
            return ret

        ret["changes"]["deleted"] = name

        if __opts__["test"]:
            ret["result"] = None
            ret["comment"] = "Would have deleted the bucket"
            return ret

        __salt__["influxdb2.delete_bucket"](name, org=org, **kwargs)
        ret["comment"] = "Successfully deleted the bucket"

    except (CommandExecutionError, SaltInvocationError) as err:
        ret["result"] = False
        ret["comment"] = str(err)
        ret["changes"] = {}
    return ret


def task_present(
    name,
    query,
    every=None,
    cron=None,
    offset=None,
    description="",
    active=True,
    org=None,
    **kwargs,
):
    """
    Ensure an InfluxDB v2 task is present.

    name
        Name of the task to manage.

    query
        Flux query to execute, excluding ``option task = {...}``.

    every
        Set repeating task period.

    cron
        Set scheduled task cron string.

    offset
        Set time offset

    description
        A description for the task.

    active
        Whether the task should be active. Defaults to true.

    org
        Override the default organization set in the configuration.
    """
    ret = {
        "name": name,
        "comment": "The task is already in the correct state",
        "changes": {},
        "result": True,
    }

    try:
        existing = __salt__["influxdb2.fetch_task"](name, org=org, **kwargs)
        changes = {}
        if existing is None:
            verb = "create"
            changes["created"] = name
        else:
            verb = "update"
            current_query = Task.from_flux(existing["flux"]).query
            new_query = str(FluxQuery.from_string(query))
            if current_query != new_query:
                changes["query"] = {"old": current_query, "new": new_query}
            for param, var in (
                ("every", every),
                ("cron", cron),
                ("offset", offset),
                ("description", description),
            ):
                if existing.get(param) != var and (
                    param != "description" or (var or existing.get(param) is not None)
                ):
                    changes[param] = {"old": existing.get(param), "new": var}
                if (existing["status"] == "active") is not active:
                    changes["active"] = active
        if not changes:
            return ret
        ret["changes"] = changes

        if __opts__["test"]:
            ret["result"] = None
            ret["comment"] = f"Would have {verb}d the task"
            return ret

        __salt__[f"influxdb2.{verb}_task"](
            name,
            query=query,
            every=every,
            cron=cron,
            offset=offset,
            description=description,
            active=active,
            org=org,
            **kwargs,
        )
        ret["comment"] = f"Successfully {verb}d the task"

    except (CommandExecutionError, SaltInvocationError) as err:
        ret["result"] = False
        ret["comment"] = str(err)
        ret["changes"] = {}
    return ret


def task_absent(name, org=None, **kwargs):
    """
    Ensure an InfluxDB v2 task is absent.

    name
        Name of the task to ensure absence of.

    org
        Override the default organization set in the configuration.
    """
    ret = {
        "name": name,
        "comment": "The task is already absent",
        "changes": {},
        "result": True,
    }

    try:
        existing = __salt__["influxdb2.fetch_task"](name, org=org, **kwargs)
        if existing is None:
            return ret

        ret["changes"]["deleted"] = name

        if __opts__["test"]:
            ret["result"] = None
            ret["comment"] = "Would have deleted the task"
            return ret

        __salt__["influxdb2.delete_task"](name, org=org, **kwargs)
        ret["comment"] = "Successfully deleted the task"

    except (CommandExecutionError, SaltInvocationError) as err:
        ret["result"] = False
        ret["comment"] = str(err)
        ret["changes"] = {}
    return ret
