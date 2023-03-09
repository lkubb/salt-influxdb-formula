# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

{%- set influxdb_token = "" %}
{%- if influxdb.vault.connection_name in salt["vault_db.list_connections"](influxdb.vault.database_mount) %}
{%-   set influxdb_token = salt["vault_db.get_creds"](influxdb.vault.manage_role, mount=influxdb.vault.database_mount)["password"] | d("null") %}
{%- endif %}
{%- set influxdb_org = influxdb.vault.organization %}

{%- if influxdb_token %}
{%-   for task in influxdb.tasks %}

InfluxDB task {{ task.name }} is absent:
  influxdb2.task_absent:
    - name: {{ task.name }}
    - org: {{ task.org | d(none) | json }}
    - influxdb_url: {{ influxdb._url }}
    - influxdb_token: {{ influxdb_token }}
    - influxdb_org: {{ influxdb_org }}
{%-   endfor %}
{%- endif %}
