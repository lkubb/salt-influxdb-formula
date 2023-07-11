# vim: ft=sls

{%- set tplroot = tpldir.split("/")[0] %}
{%- set sls_config_file = tplroot ~ ".config.file" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

include:
  - {{ sls_config_file }}

{%- if influxdb.config.get("tls-key") and influxdb.config.get("tls-cert") %}

InfluxDB HTTP certificate private key is managed:
  x509.private_key_managed:
    - name: {{ influxdb.config["tls-key"] }}
    - algo: rsa
    - keysize: 2048
    - new: true
{%-   if salt["file.file_exists"](influxdb.config["tls-key"]) %}
    - prereq:
      - InfluxDB HTTP certificate is managed
{%-   endif %}
    - makedirs: true
    - user: {{ influxdb.lookup.user }}
    - group: {{ influxdb.lookup.group }}
    - require:
      - sls: {{ sls_config_file }}

InfluxDB HTTP certificate is managed:
  x509.certificate_managed:
    - name: {{ influxdb.config["tls-cert"] }}
    - ca_server: {{ influxdb.cert.ca_server or "null" }}
    - signing_policy: {{ influxdb.cert.signing_policy or "null" }}
    - signing_cert: {{ influxdb.cert.signing_cert or "null" }}
    - signing_private_key: {{ influxdb.cert.signing_private_key or
                              (influxdb.config["tls-cert"] if not influxdb.cert.ca_server and not influxdb.cert.signing_cert else "null") }}
    - private_key: {{ influxdb.config["tls-key"] }}
    - authorityKeyIdentifier: keyid:always
    - basicConstraints: critical, CA:false
    - subjectKeyIdentifier: hash
    # required for vault
    - subjectAltName:
      - dns: {{ influxdb.cert.cn or grains.fqdns | first | d(influxdb | traverse("config:instance-id", grains.id)) }}
    - CN: {{ influxdb.cert.cn or grains.fqdns | first | d(influxdb | traverse("config:instance-id", grains.id)) }}
    - mode: '0640'
    - user: {{ influxdb.lookup.user }}
    - group: {{ influxdb.lookup.group }}
    - makedirs: true
    - append_certs: {{ influxdb.cert.intermediate | json }}
    - days_remaining: {{ influxdb.cert.days_remaining }}
    - days_valid: {{ influxdb.cert.days_valid }}
    - require:
      - sls: {{ sls_config_file }}
{%-   if not salt["file.file_exists"](influxdb.config["tls-key"]) %}
      - InfluxDB HTTP certificate private key is managed
{%-   endif %}
{%- endif %}
