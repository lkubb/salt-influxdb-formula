# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

{%- for role in influxdb.vault_roles %}

Vault InfluxDB v2 role {{ role.name }} is absent:
  vault_db.role_absent:
    - name: {{ role.name }}
    - mount: {{ influxdb.vault.database_mount }}
{%- endfor %}

{%- if influxdb.remove_all_data_for_sure %}

Vault database configuration is absent:
  vault_db.connection_absent:
    - name: {{ influxdb.vault.connection_name }}
    - mount: {{ influxdb.vault.database_mount }}
{%- endif %}
