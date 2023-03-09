# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- set sls_service_running = tplroot ~ ".service.running" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

{%- set influxdb_token = "" %}
{%- if influxdb.vault.connection_name in salt["vault_db.list_connections"](influxdb.vault.database_mount) %}
{%-   set influxdb_token = salt["vault_db.get_creds"](influxdb.vault.manage_role, mount=influxdb.vault.database_mount)["password"] | d("null") %}
{%- endif %}
{%- set influxdb_org = influxdb.vault.organization %}

include:
  - {{ sls_service_running }}

{%- if influxdb_token %}
{%-   for task in influxdb.tasks %}

InfluxDB task {{ task.name }} is managed:
  influxdb2.task_present:
    - name: {{ task.name }}
    - query: {{ task.query | json }}
    - every: {{ task.every | d("null") }}
    - cron: {{ task.cron | d("null") }}
    - offset: {{ task.offset | d("null") }}
    - description: {{ task.description | d("null") }}
    - active: {{ task.active | d(true) }}
    - org: {{ task.org | d(none) | json }}
    - influxdb_url: {{ influxdb._url }}
    - influxdb_token: {{ influxdb_token }}
    - influxdb_org: {{ influxdb_org }}
    - require:
      - sls: {{ sls_service_running }}
{%-   endfor %}

{%-   for task in influxdb.tasks_absent %}

InfluxDB task {{ task.name | d(task) }} is absent:
  influxdb2.task_absent:
    - name: {{ task.name | d(task) }}
    - org: {{ task.org | d(none) | json }}
    - influxdb_url: {{ influxdb._url }}
    - influxdb_token: {{ influxdb_token }}
    - influxdb_org: {{ influxdb_org }}
    - require:
      - sls: {{ sls_service_running }}
{%-   endfor %}
{%- endif %}
