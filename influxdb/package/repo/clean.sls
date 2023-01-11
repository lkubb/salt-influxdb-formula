# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}


{%- if influxdb.lookup.pkg_manager not in ['apt', 'dnf', 'yum', 'zypper'] %}
{%-   if salt['state.sls_exists'](slsdotpath ~ '.' ~ influxdb.lookup.pkg_manager ~ '.clean') %}

include:
  - {{ slsdotpath ~ '.' ~ influxdb.lookup.pkg_manager ~ '.clean' }}
{%-   endif %}

{%- else %}
{%-   for reponame, enabled in influxdb.lookup.enablerepo.items() %}
{%-     if enabled %}

InfluxDB {{ reponame }} repository is absent:
  pkgrepo.absent:
{%-       for conf in ['name', 'ppa', 'ppa_auth', 'keyid', 'keyid_ppa', 'copr'] %}
{%-         if conf in influxdb.lookup.repos[reponame] %}
    - {{ conf }}: {{ influxdb.lookup.repos[reponame][conf] }}
{%-         endif %}
{%-       endfor %}
{%-     endif %}
{%-   endfor %}
{%- endif %}
