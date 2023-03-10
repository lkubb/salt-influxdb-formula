# vim: ft=sls

{#-
    *Meta-state*.

    This installs the influxdb package,
    manages the influxdb configuration file
    and then starts the associated influxdb service.
#}

include:
  - .package
  - .config
  - .cert
  - .service
  - .auth
  - .vault
  - .buckets
  - .tasks
