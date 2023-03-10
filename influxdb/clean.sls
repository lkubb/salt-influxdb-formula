# vim: ft=sls

{#-
    *Meta-state*.

    Undoes everything performed in the ``influxdb`` meta-state
    in reverse order, i.e.
    stops the service,
    removes the configuration file and then
    uninstalls the package.
#}

include:
  - .tasks.clean
  - .buckets.clean
  - .vault.clean
  - .service.clean
  - .cert.clean
  - .config.clean
  - .package.clean
