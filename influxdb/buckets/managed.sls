# vim: ft=sls

{%- set tplroot = tpldir.split('/')[0] %}
{%- set sls_service_running = tplroot ~ ".service.running" %}
{%- from tplroot ~ "/map.jinja" import mapdata as influxdb with context %}

{%- set influxdb_token = salt["vault_db.get_creds"](influxdb.vault.manage_role, mount=influxdb.vault.database_mount)["password"] | d("null") %}
{%- set influxdb_org = influxdb.vault.organization %}

include:
  - {{ sls_service_running }}

{%- for bucket in influxdb.buckets %}

InfluxDB bucket {{ bucket.name | d(bucket) }} is managed:
  influxdb2.bucket_present:
    - name: {{ bucket.name | d(bucket) }}
    - expire: {{ bucket.expire | d(none) | json }}
    - description: {{ bucket.description | d("") | json }}
    - org: {{ bucket.org | d(none) | json }}
    - influxdb_url: {{ influxdb._url }}
    - influxdb_token: {{ influxdb_token }}
    - influxdb_org: {{ influxdb_org }}
    - require:
      - sls: {{ sls_service_running }}
{%- endfor %}

{%- for bucket in influxdb.buckets_absent %}

InfluxDB bucket {{ bucket.name | d(bucket) }} is absent:
  influxdb2.bucket_absent:
    - name: {{ bucket.name | d(bucket) }}
    - org: {{ bucket.org | d(none) | json }}
    - influxdb_url: {{ influxdb._url }}
    - influxdb_token: {{ influxdb_token }}
    - influxdb_org: {{ influxdb_org }}
    - require:
      - sls: {{ sls_service_running }}
{%- endfor %}
