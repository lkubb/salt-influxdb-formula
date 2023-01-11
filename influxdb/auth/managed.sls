# -*- coding: utf-8 -*-
# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- set sls_service_running = tplroot ~ '.service.running' %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_service_running }}

{%- if influxdb.init.user_password or (influxdb.init.user_password_pillar and influxdb.init.user_password_pillar in pillar) %}

InfluxDB initial user account is set up:
  cmd.run:
    - name: >
        influx setup -f
        --username "$SETUP_USER"
        --password "$SETUP_PW"
        --org "$SETUP_ORG"
        --bucket "$SETUP_BUCKET"
    - env:
      - INFLUX_HOST: http{{ "s" if influxdb.config.get("tls-cert") }}://{{ influxdb.init.host or influxdb.config.http-bind-address }}
      - SETUP_USER: {{ influxdb.init.user_name }}
      - SETUP_PW: {{ influxdb.init.user_password or pillar[influxdb.init.user_password_pillar] }}
      - SETUP_ORG: {{ influxdb.init.org }}
      - SETUP_BUCKET: {{ influxdb.init.bucket }}
  - unless:
    - influx setup 2>&1 >/dev/null | grep "already been set up"
  - require:
    - sls: {{ sls_service_running }}
{%- endif %}
