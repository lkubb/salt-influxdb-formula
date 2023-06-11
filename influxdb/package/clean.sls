# vim: ft=sls

{#-
    Removes the influxdb package.
    Has a dependency on `influxdb.config.clean`_.
#}

{%- set tplroot = tpldir.split("/")[0] %}
{%- set sls_config_clean = tplroot ~ ".config.clean" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_config_clean }}
  - {{ slsdotpath }}.repo.clean

InfluxDB is removed:
  pkg.removed:
    - pkgs:
      - {{ influxdb.lookup.pkg.name }}
      - {{ influxdb.lookup.pkg_cli }}
    - require:
      - sls: {{ sls_config_clean }}
