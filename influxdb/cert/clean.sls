# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- set sls_service_clean = tplroot ~ '.service.clean' %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_service_clean }}

{%- if influxdb.config.get("tls-key") and influxdb.config.get("tls-cert") %}

InfluxDB key/cert is absent:
  file.absent:
    - names:
      - {{ influxdb.config["tls-cert"] }}
      - {{ influxdb.config["tls-key"] }}
    - require:
      - sls: {{ sls_service_clean }}
{%- endif %}
