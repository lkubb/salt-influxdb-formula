# vim: ft=sls

{%- set tplroot = tpldir.split("/")[0] %}
{%- set sls_config_file = tplroot ~ ".config.file" %}
{%- set sls_cert_managed = tplroot ~ ".cert.managed" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_config_file }}
  - {{ sls_cert_managed }}

InfluxDB is running:
  service.running:
    - name: {{ influxdb.lookup.service.name }}
    - enable: true
    - watch:
      - sls: {{ sls_config_file }}
{%- if influxdb.config.get("tls-key") and influxdb.config.get("tls-cert") %}
      - sls: {{ sls_cert_managed }}
{%- endif %}

{%- if influxdb.manage_firewalld and "firewall-cmd" | which %}

InfluxDB service is known:
  firewalld.service:
    - name: influxdb
    - ports:
      - {{ (influxdb | traverse("config:http-bind-address", ":8086")).split(":") | last }}/tcp
    - require:
      - InfluxDB is running

InfluxDB ports are open:
  firewalld.present:
    - name: public
    - services:
      - influxdb
    - require:
      - InfluxDB service is known
{%- endif %}
