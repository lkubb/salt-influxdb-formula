# vim: ft=sls

{%- set tplroot = tpldir.split("/")[0] %}
{%- set sls_vault_connection = tplroot ~ ".vault.connection" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_vault_connection }}

{%-   for role in influxdb.vault_roles %}

Vault InfluxDB v2 role {{ role.name }} is present:
  vault_db.role_present:
    - name: {{ role.name }}
    - mount: {{ influxdb.vault.database_mount }}
    - connection: {{ influxdb.vault.connection_name }}
    - creation_statements:
      - '{{ role.definition | json }}'
    - default_ttl: {{ role.get("default_ttl") or "null" }}
    - max_ttl: {{ role.get("max_ttl") or "null" }}
{%-   endfor %}
