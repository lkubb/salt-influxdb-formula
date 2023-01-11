# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- set sls_config_clean = tplroot ~ '.config.clean' %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_config_clean }}
  - {{ slsdotpath }}.repo.clean

influxdb-package-clean-pkg-removed:
  pkg.removed:
    - pkgs:
      - {{ influxdb.lookup.pkg.name }}
      - {{ influxdb.lookup.pkg_cli }}
    - require:
      - sls: {{ sls_config_clean }}
