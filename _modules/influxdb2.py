"""
Interface with an InfluxDB v2 server.

:depends: ``influxdb-client`` Python module

Configuration
-------------

Connection parameters
~~~~~~~~~~~~~~~~~~~~~

This module accepts connection configuration details either as
parameters or as configuration settings retrievable by
:py:func:`config.option <salt.modules.config.option>`.

.. code-block:: yaml

    influxdb2:
      url: http://localhost:8086
      org: salt # default organization
      bucket: salt # default bucket
      token: my-token

To override url/token/org during a function call, you can pass
``influxdb_url``/``influxdb_token``/``influxdb_org`` as kwargs.

Each function also takes ``client_kwargs`` as an argument. This
specifies miscellaneous arguments that should be passed to
``influxdb_client.InfluxDBClient``.
.. _influxdb2-cofig:
"""

import logging
import shlex
from functools import wraps

import salt.utils.path
from influxdb2util import Task, timestring_map
from salt.exceptions import CommandExecutionError, SaltException, SaltInvocationError

try:
    import influxdb_client
    from influxdb_client.client.exceptions import InfluxDBError
    from influxdb_client.rest import ApiException

    HAS_INFLUXDB = True
except ImportError:
    HAS_INFLUXDB = False


try:
    from salt.config import NOT_SET
except ImportError:
    NOT_SET = "__unset__"

__virtualname__ = "influxdb2"

log = logging.getLogger(__name__)


def __virtual__():
    """
    Only load if influxdb lib is present
    """
    if HAS_INFLUXDB:
        return __virtualname__
    return (
        False,
        "The influxdb2 execution module requires the influxdb-client Python library",
    )


def _client_args(profile, token, url, org, extra):
    profile = profile or "influxdb2"
    config = __salt__["config.get"](profile)
    try:
        token = token or config["token"]
    except KeyError as err:
        raise SaltInvocationError(
            f"Missing token: {profile}:token / influxdb_token"
        ) from err
    url = url or config.get("url", "http://localhost:8086")
    org = org or config.get("org", "salt")
    extra = extra or {}
    extra.update({"token": token, "url": url, "org": org})
    return extra


def _with_client(func):
    @wraps(func)
    def wrapper(
        *args,
        influxdb_token=None,
        influxdb_org=None,
        influxdb_url=None,
        influxdb_profile=None,
        influxdb_extra_args=None,
        **kwargs,
    ):
        if "_client" in kwargs and kwargs["_client"] is not None:
            return func(*args, **kwargs)
        client_args = _client_args(
            profile=influxdb_profile,
            token=influxdb_token,
            url=influxdb_url,
            org=influxdb_org,
            extra=influxdb_extra_args,
        )
        try:
            with influxdb_client.InfluxDBClient(**client_args) as client:
                return func(_client=client, *args, **kwargs)
        except InfluxDBError as err:
            raise CommandExecutionError(err) from err

    return wrapper


def _list_buckets(_client, name=None, org=None):
    """
    Helper to list buckets (as objects)
    """
    # 100 is the max value for limit.
    # The loop should usually be unnecessary because more than 20 buckets
    # are a problem anyways.
    payload = {
        "limit": 100,
    }
    for val, param in ((name, "name"), (org, "org")):
        if val is not None:
            payload[param] = val

    api = _client.buckets_api()
    buckets = []

    while True:
        try:
            new_buckets = api.find_buckets(**payload).buckets
        except ApiException as err:
            if err.status != 404:
                raise
            new_buckets = None
        if not new_buckets:
            break
        buckets.extend(new_buckets)
        if len(new_buckets) < 100:
            break
        payload["after"] = new_buckets[-1].id
    return buckets


def _fetch_bucket(_client, name, org=None):
    """
    Helper to fetch a single Bucket object or None
    """
    res = _list_buckets(_client, name=name, org=org)
    if len(res) > 1:
        raise CommandExecutionError("Query returned multiple buckets")
    try:
        return res[0]
    except IndexError:
        return None


def _get_bucket(_client, name, org=None):
    """
    Helper to get a single Bucket object
    """
    bucket = _fetch_bucket(_client, name, org=org)
    if bucket is None:
        raise CommandExecutionError(
            f"Could not find bucket with name {name} in org {org or 'default org'}"
        )
    return bucket


@_with_client
def create_bucket(name, expire="30d", description=None, org=None, **kwargs):
    """
    Create a bucket.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.create_bucket mybucket

    name
        Name of the bucket to create. Required.

    expire
        Set data expiration time, either as an integer (seconds) or a
        time string like ``6h``. 0 disables expiration. Defaults to ``30d``.

    description
        A description for the bucket.

    org
        Override the default organization set in the configuration.
    """
    try:
        # We need to accept **kwargs, otherwise Salt will refuse to run this
        # function with overridden parameters.
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _fetch_bucket(_client, name=name, org=org)
    if existing is not None:
        raise CommandExecutionError(
            f"Bucket {name} already exists in {org or 'default org'}"
        )
    expire = timestring_map(expire)
    retention_rules = [
        influxdb_client.BucketRetentionRules(type="expire", every_seconds=expire)
    ]
    return (
        _client.buckets_api()
        .create_bucket(bucket_name=name, retention_rules=retention_rules, org=org)
        .to_dict()
    )


@_with_client
def delete_bucket(name, org=None, **kwargs):
    """
    Drop a bucket.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.delete_bucket mybucket

    name
        Name of the bucket to delete.

    org
        Override the default organization set in the configuration.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _get_bucket(_client, name=name, org=org)
    return _client.buckets_api().delete_bucket(existing) or True


@_with_client
def fetch_bucket(name, org=None, **kwargs):
    """
    Returns a bucket or None.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.fetch_bucket mybucket

    name
        Name of the bucket to fetch.

    org
        Override the default organization set in the configuration.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    bucket = _fetch_bucket(_client, name, org=org)
    if bucket is None:
        return bucket
    return bucket.to_dict()


@_with_client
def list_buckets(name=None, org=None, **kwargs):
    """
    List all InfluxDB buckets.

    Please see `Connection parameters` for further valid
    keyword arguments.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.list_buckets

    name
        Filter buckets with a specific name.

    org
        Override the default organization set in the configuration.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    return [bucket.to_dict() for bucket in _list_buckets(_client, name=name, org=org)]


@_with_client
def update_bucket(name, expire=NOT_SET, description=NOT_SET, org=NOT_SET, **kwargs):
    """
    Create/update a bucket.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.update_bucket mybucket expire=90d

    name
        Name of the bucket to update. Required.

    expire
        Set data expiration time, either as an integer (seconds) or a
        time string like ``6h``. 0 disables expiration. Defaults to ``30d``.

    description
        A description for the bucket.

    org
        Override the default organization set in the configuration.
    """
    if expire == NOT_SET and description == NOT_SET:
        raise SaltInvocationError("Need at least one parameter to update")
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _get_bucket(_client, name=name, org=org)
    if expire != NOT_SET:
        expire = timestring_map(expire)
        existing.retention_rules = [
            influxdb_client.BucketRetentionRules(type="expire", every_seconds=expire)
        ]
    if description != NOT_SET:
        existing.description = description
    return _client.buckets_api().update_bucket(existing).to_dict()


def _list_tasks(_client, name, user, org):
    """
    Helper to list tasks (as objects)
    """
    # 100 is the max value for limit.
    payload = {
        "limit": 100,
    }
    for val, param in ((name, "name"), (user, "user"), (org, "org")):
        if val is not None:
            payload[param] = val

    api = _client.tasks_api()
    tasks = []

    while True:
        new_tasks = api.find_tasks(**payload)
        if not new_tasks:
            break
        tasks.extend(new_tasks)
        if len(new_tasks) < 100:
            break
        payload["after"] = new_tasks[-1].id
    return tasks


@_with_client
def list_tasks(name=None, user=None, org=None, **kwargs):
    """
    List all InfluxDB buckets.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.list_buckets

    name
        Filter tasks with a specific name.

    user
        Filter tasks to a specific user.

    org
        Filter tasks to a specific organization.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    tasks = _list_tasks(_client, name=name, user=user, org=org)
    return [task.to_dict() for task in tasks]


def _fetch_task(_client, name, user=None, org=None):
    """
    Helper to fetch a single task object or None
    """
    res = _list_tasks(_client, name=name, user=user, org=org)
    if len(res) > 1:
        raise CommandExecutionError("Query returned multiple tasks")
    try:
        return res[0]
    except IndexError:
        return None


def _get_task(_client, name, user=None, org=None):
    """
    Helper to get a single task object
    """
    task = _fetch_task(_client, name, user=user, org=org)
    if task is None:
        raise CommandExecutionError(
            f"Could not find task with name {name} in org {org or 'default org'}. User: {user}"
        )
    return task


@_with_client
def create_task(
    name,
    query,
    every=None,
    cron=None,
    offset=None,
    description=None,
    active=True,
    org=None,
    **kwargs,
):
    """
    Create a task.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.write_task mytask

    name
        Name of the task to create. Required.

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
        Whether the task should be created as active. Defaults to true.

    org
        Override the default organization set in the configuration.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _fetch_task(_client, name=name, org=org)
    if existing is not None:
        raise CommandExecutionError(
            f"Task {name} already exists in {org or 'default org'}"
        )
    flux = Task(name=name, query=query, every=every, cron=cron, offset=offset).to_flux()
    status = (
        influxdb_client.TaskStatusType.ACTIVE
        if active
        else influxdb_client.TaskStatusType.INACTIVE
    )
    req = influxdb_client.TaskCreateRequest(
        org=org or _client.org, flux=flux, description=description, status=status
    )

    return _client.tasks_api().create_task(task_create_request=req).to_dict()


@_with_client
def delete_task(name, org=None, **kwargs):
    """
    Delete a task.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.delete_task mytask

    name
        Name of the task to delete.

    org
        Override the default organization set in the configuration.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _get_task(_client, name=name, org=org)
    return _client.tasks_api().delete_task(existing.id) or True


@_with_client
def fetch_task(name, user=None, org=None, **kwargs):
    """
    Returns a task or None.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.fetch_task mytask

    name
        Name of the task to fetch.

    org
        Override the default organization set in the configuration.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    task = _fetch_task(_client, name, user=user, org=org)
    if task is None:
        return task
    return task.to_dict()
    # task_dict = task.to_dict()
    # task_dict.update(Task.from_flux(task_dict["flux"]).to_dict())
    # return task_dict


@_with_client
def update_task(
    name,
    rename=NOT_SET,
    query=NOT_SET,
    every=NOT_SET,
    cron=NOT_SET,
    offset=NOT_SET,
    description=NOT_SET,
    active=NOT_SET,
    org=None,
    **kwargs,
):
    """
    Update a task.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.write_task mytask

    name
        Name of the task to update. Required.

    rename
        New name of the task.

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
        Whether the task should be active.

    org
        Override the default organization set in the configuration.
        Cannot be used to change org on the task.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _get_task(_client, name=name, org=org)
    taskoptshelper = Task.from_flux(existing.flux)
    for attr, var in (
        ("name", rename),
        ("query", query),
        ("every", every),
        ("cron", cron),
        ("offset", offset),
    ):
        # This check should be `is not NOT_SET`, but that requires
        # Salt v3006. The workaround cannot work with `is`
        if var != NOT_SET:
            setattr(taskoptshelper, attr, var)
            if attr != "query":
                setattr(existing, attr, var)
    existing.flux = taskoptshelper.to_flux()
    if description != NOT_SET:
        existing.description = description
    if active is not None:
        existing.status = (
            influxdb_client.TaskStatusType.ACTIVE
            if active
            else influxdb_client.TaskStatusType.INACTIVE
        )

    return _client.tasks_api().update_task(existing).to_dict()


@_with_client
def activate_task(name, org=None, **kwargs):
    """
    Activate a task.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.activate_task mytask

    name
        Name of the task to activate. Required.

    org
        Override the default organization set in the configuration.
        Cannot be used to change org on the task.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _get_task(_client, name=name, org=org)
    if existing.status == influxdb_client.TaskStatusType.ACTIVE:
        raise CommandExecutionError("Task is already active")
    existing.status = influxdb_client.TaskStatusType.ACTIVE
    return _client.tasks_api().update_task(existing).to_dict()


@_with_client
def deactivate_task(name, org=None, **kwargs):
    """
    Deactivate a task.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.deactivate_task mytask

    name
        Name of the task to deactivate. Required.

    org
        Override the default organization set in the configuration.
        Cannot be used to change org on the task.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    existing = _get_task(_client, name=name, org=org)
    if existing.status == influxdb_client.TaskStatusType.INACTIVE:
        raise CommandExecutionError("Task is already inactive")
    existing.status = influxdb_client.TaskStatusType.INACTIVE
    return _client.tasks_api().update_task(existing).to_dict()


# authorizations
# organizations


@_with_client
def query(query, org=None, bind_params=None, columns=None, **kwargs):
    """
    Execute a Flux query.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.query 'from(bucket: example) |> range(start: -10m)'

    query
        Flux query string.

    org
        Override the default organization set in the configuration.

    bind_params
        Mapping of bind parameters to values.

    columns
        Filter required columns.
    """
    try:
        _client = kwargs.pop("_client")
    except KeyError:
        raise SaltException("Did not receive a client. This is a coding bug.")
    res = _client.query_api().query(query, org=org, params=bind_params)
    # TODO This returns raw datetime objects. Convert?
    return res.to_values(columns)


def backup(dest, root_token, influxdb_url=None, influxdb_profile=None):
    """
    Use the ``influx`` CLI to create a backup of the current data.
    This command requires the root token.

    CLI Example:

    .. code-block:: bash

        salt '*' influxdb2.backup /opt/backup/influxdb2 root_token=sdb://sdbvault/salt/roles/influxdb?root_token

    dest
        The backup destination (directory).

    root_token
        The InfluxDB v2 root token.

    influxdb_url
        Override the default URL set in the Salt config.

    influxdb_profile
        Override the default profile in the Salt config.
    """
    if not salt.utils.path.which("influx"):
        raise CommandExecutionError("Missing `influx` CLI command")
    if not dest.endswith("/"):
        dest += "/"
    if not __salt__["file.directory_exists"](dest):
        __salt__["file.makedirs"](dest)
    client_args = _client_args(
        profile=influxdb_profile,
        token=None,
        url=influxdb_url,
        org=None,
        extra=None,
    )
    env = {
        "INFLX_ROOT_TOKEN": __salt__["sdb.get"](root_token),
        "INFLUX_HOST": client_args["url"],
    }
    cmd = shlex.join(["influx", "backup", dest, "-t"]) + ' "$INFLX_ROOT_TOKEN"'
    ret = __salt__["cmd.run_all"](cmd, env=env, python_shell=True)
    if ret["retcode"] > 0:
        raise CommandExecutionError(ret["stderr"])
    return True
