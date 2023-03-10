# vim: ft=sls

{#-
    Starts the influxdb service and enables it at boot time.
    Has a dependency on `influxdb.config`_.
#}

include:
  - .running
