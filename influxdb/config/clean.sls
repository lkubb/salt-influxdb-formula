# vim: ft=sls

{#-
    Removes the configuration of the influxdb service and has a
    dependency on `influxdb.service.clean`_.
#}

{%- set tplroot = tpldir.split("/")[0] %}
{%- set sls_service_clean = tplroot ~ ".service.clean" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_service_clean }}

InfluxDB configuration is absent:
  file.absent:
    - name: {{ influxdb.lookup.config }}
    - require:
      - sls: {{ sls_service_clean }}
