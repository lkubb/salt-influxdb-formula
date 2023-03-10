# vim: ft=sls

{%- set tplroot = tpldir.split("/")[0] %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

# There is no need for python-apt anymore.

{%- for reponame, enabled in influxdb.lookup.enablerepo.items() %}
{%-   if enabled %}

InfluxDB {{ reponame }} repository is available:
  pkgrepo.managed:
{%-     for conf, val in influxdb.lookup.repos[reponame].items() %}
    - {{ conf }}: {{ val }}
{%-     endfor %}
{%-     if influxdb.lookup.pkg_manager in ["dnf", "yum", "zypper"] %}
    - enabled: 1
{%-     endif %}
    - require_in:
      - influxdb-package-install-pkg-installed

{%-   else %}

InfluxDB {{ reponame }} repository is disabled:
  pkgrepo.absent:
{%-     for conf in ["name", "ppa", "ppa_auth", "keyid", "keyid_ppa", "copr"] %}
{%-       if conf in influxdb.lookup.repos[reponame] %}
    - {{ conf }}: {{ influxdb.lookup.repos[reponame][conf] }}
{%-       endif %}
{%-     endfor %}
    - require_in:
      - influxdb-package-install-pkg-installed
{%-   endif %}
{%- endfor %}
