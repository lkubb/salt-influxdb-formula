# vim: ft=sls

{%- set tplroot = tpldir.split("/")[0] %}
{%- set sls_package_install = tplroot ~ ".package.install" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_package_install }}

InfluxDB configuration is managed:
  file.serialize:
    - name: {{ influxdb.lookup.config }}
    - mode: '0644'
    - user: root
    - group: {{ influxdb.lookup.rootgroup }}
    - makedirs: true
    - serializer: {{ influxdb.lookup.config.rsplit(".") | last }}
    - require:
      - sls: {{ sls_package_install }}
    - dataset: {{ influxdb.config | json }}
