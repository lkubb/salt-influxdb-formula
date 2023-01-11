# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ slsdotpath }}.repo

InfluxDB is installed:
  pkg.installed:
    - pkgs:
{%- if influxdb.version %}
      - {{ influxdb.lookup.pkg.name }}: {{ influxdb.version }}
{%- else %}
      - {{ influxdb.lookup.pkg.name }}
{%- endif %}
      - {{ influxdb.lookup.pkg_cli }}

{%- if influxdb.lookup.config.rsplit(".") | last == "toml" %}

Python TOML module is installed for InfluxDB:
  pip.installed:
    - name: toml
{%- endif %}
