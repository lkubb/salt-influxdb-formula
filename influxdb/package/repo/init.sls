# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
{%- if influxdb.lookup.pkg_manager in ['apt', 'dnf', 'yum', 'zypper'] %}
  - {{ slsdotpath }}.install
{%- elif salt['state.sls_exists'](slsdotpath ~ '.' ~ influxdb.lookup.pkg_manager) %}
  - {{ slsdotpath }}.{{ influxdb.lookup.pkg_manager }}
{%- else %}
  []
{%- endif %}
