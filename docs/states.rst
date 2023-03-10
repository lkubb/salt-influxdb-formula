Available states
----------------

The following states are found in this formula:

.. contents::
   :local:


``influxdb``
^^^^^^^^^^^^
*Meta-state*.

This installs the influxdb package,
manages the influxdb configuration file
and then starts the associated influxdb service.


``influxdb.package``
^^^^^^^^^^^^^^^^^^^^
Installs the influxdb package only.


``influxdb.package.install``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^



``influxdb.package.repo``
^^^^^^^^^^^^^^^^^^^^^^^^^
This state will install the configured influxdb repository.
This works for apt/dnf/yum/zypper-based distributions only by default.


``influxdb.config``
^^^^^^^^^^^^^^^^^^^
Manages the influxdb service configuration.
Has a dependency on `influxdb.package`_.


``influxdb.service``
^^^^^^^^^^^^^^^^^^^^
Starts the influxdb service and enables it at boot time.
Has a dependency on `influxdb.config`_.


``influxdb.auth``
^^^^^^^^^^^^^^^^^



``influxdb.auth.managed``
^^^^^^^^^^^^^^^^^^^^^^^^^



``influxdb.buckets``
^^^^^^^^^^^^^^^^^^^^



``influxdb.cert``
^^^^^^^^^^^^^^^^^



``influxdb.tasks``
^^^^^^^^^^^^^^^^^^



``influxdb.vault``
^^^^^^^^^^^^^^^^^^



``influxdb.vault.connection``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^



``influxdb.vault.roles``
^^^^^^^^^^^^^^^^^^^^^^^^



``influxdb.clean``
^^^^^^^^^^^^^^^^^^
*Meta-state*.

Undoes everything performed in the ``influxdb`` meta-state
in reverse order, i.e.
stops the service,
removes the configuration file and then
uninstalls the package.


``influxdb.package.clean``
^^^^^^^^^^^^^^^^^^^^^^^^^^
Removes the influxdb package.
Has a depency on `influxdb.config.clean`_.


``influxdb.package.repo.clean``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
This state will remove the configured influxdb repository.
This works for apt/dnf/yum/zypper-based distributions only by default.


``influxdb.config.clean``
^^^^^^^^^^^^^^^^^^^^^^^^^
Removes the configuration of the influxdb service and has a
dependency on `influxdb.service.clean`_.


``influxdb.service.clean``
^^^^^^^^^^^^^^^^^^^^^^^^^^
Stops the influxdb service and disables it at boot time.


``influxdb.buckets.clean``
^^^^^^^^^^^^^^^^^^^^^^^^^^



``influxdb.cert.clean``
^^^^^^^^^^^^^^^^^^^^^^^



``influxdb.tasks.clean``
^^^^^^^^^^^^^^^^^^^^^^^^



``influxdb.vault.clean``
^^^^^^^^^^^^^^^^^^^^^^^^



