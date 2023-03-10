# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- set sls_service_running = tplroot ~ ".service.running" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_service_running }}


# This currently only works statically with predefined authorization.
# @TODO: Use bootstrap credentials to create Vault user + authorization with correct perms
Initialize Vault database configuration:
  vault_db.connection_present:
    - name: {{ influxdb.vault.connection_name }}
    - mount: {{ influxdb.vault.database_mount }}
    - rotate: true
    - allowed_roles: {{ influxdb.vault_roles | map(attribute="name") | list | json }}
    # requires custom plugin
    - plugin: influxdb2
    - host: {{ influxdb._host }}
    - port: {{ influxdb._port }}
    - password: {{ influxdb.vault.token or salt["pillar.get"](influxdb.vault.token_pillar, "null") }}
    - organization: {{ influxdb.vault.organization }}
    - tls: {{ "tls-cert" in influxdb.config }}
    - require:
      - sls: {{ sls_service_running }}
      # - Create Vault user in InfluxDB
