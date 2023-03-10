# vim: ft=sls

{#-
    Stops the influxdb service and disables it at boot time.
#}

{%- set tplroot = tpldir.split("/")[0] %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

InfluxDB is dead:
  service.dead:
    - name: {{ influxdb.lookup.service.name }}
    - enable: false
