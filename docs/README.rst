.. _readme:

InfluxDB Formula
================

|img_sr| |img_pc|

.. |img_sr| image:: https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%9A%80-semantic--release-e10079.svg
   :alt: Semantic Release
   :scale: 100%
   :target: https://github.com/semantic-release/semantic-release
.. |img_pc| image:: https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white
   :alt: pre-commit
   :scale: 100%
   :target: https://github.com/pre-commit/pre-commit

Manage InfluxDB with Salt.

.. contents:: **Table of Contents**
   :depth: 1

General notes
-------------

See the full `SaltStack Formulas installation and usage instructions
<https://docs.saltstack.com/en/latest/topics/development/conventions/formulas.html>`_.

If you are interested in writing or contributing to formulas, please pay attention to the `Writing Formula Section
<https://docs.saltstack.com/en/latest/topics/development/conventions/formulas.html#writing-formulas>`_.

If you want to use this formula, please pay attention to the ``FORMULA`` file and/or ``git tag``,
which contains the currently released version. This formula is versioned according to `Semantic Versioning <http://semver.org/>`_.

See `Formula Versioning Section <https://docs.saltstack.com/en/latest/topics/development/conventions/formulas.html#versioning>`_ for more details.

If you need (non-default) configuration, please refer to:

- `how to configure the formula with map.jinja <map.jinja.rst>`_
- the ``pillar.example`` file
- the `Special notes`_ section

Special notes
-------------
* The Vault integration needs my `custom Vault database plugin <https://github.com/lkubb/vault-plugin-database-influxdb2>`_.
* The Vault integration is setup statically, which means you need to create the required authorization manually and provide it to the formula. A complete bootstrap from scratch would be possible though.

Configuration
-------------
An example pillar is provided, please see `pillar.example`. Note that you do not need to specify everything by pillar. Often, it's much easier and less resource-heavy to use the ``parameters/<grain>/<value>.yaml`` files for non-sensitive settings. The underlying logic is explained in `map.jinja`.


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




Contributing to this repo
-------------------------

Commit messages
^^^^^^^^^^^^^^^

**Commit message formatting is significant!**

Please see `How to contribute <https://github.com/saltstack-formulas/.github/blob/master/CONTRIBUTING.rst>`_ for more details.

pre-commit
^^^^^^^^^^

`pre-commit <https://pre-commit.com/>`_ is configured for this formula, which you may optionally use to ease the steps involved in submitting your changes.
First install  the ``pre-commit`` package manager using the appropriate `method <https://pre-commit.com/#installation>`_, then run ``bin/install-hooks`` and
now ``pre-commit`` will run automatically on each ``git commit``. ::

  $ bin/install-hooks
  pre-commit installed at .git/hooks/pre-commit
  pre-commit installed at .git/hooks/commit-msg

State documentation
~~~~~~~~~~~~~~~~~~~
There is a script that semi-autodocuments available states: ``bin/slsdoc``.

If a ``.sls`` file begins with a Jinja comment, it will dump that into the docs. It can be configured differently depending on the formula. See the script source code for details currently.

This means if you feel a state should be documented, make sure to write a comment explaining it.

Testing
-------

Linux testing is done with ``kitchen-salt``.

Requirements
^^^^^^^^^^^^

* Ruby
* Docker

.. code-block:: bash

   $ gem install bundler
   $ bundle install
   $ bin/kitchen test [platform]

Where ``[platform]`` is the platform name defined in ``kitchen.yml``,
e.g. ``debian-9-2019-2-py3``.

``bin/kitchen converge``
^^^^^^^^^^^^^^^^^^^^^^^^

Creates the docker instance and runs the ``influxdb`` main state, ready for testing.

``bin/kitchen verify``
^^^^^^^^^^^^^^^^^^^^^^

Runs the ``inspec`` tests on the actual instance.

``bin/kitchen destroy``
^^^^^^^^^^^^^^^^^^^^^^^

Removes the docker instance.

``bin/kitchen test``
^^^^^^^^^^^^^^^^^^^^

Runs all of the stages above in one go: i.e. ``destroy`` + ``converge`` + ``verify`` + ``destroy``.

``bin/kitchen login``
^^^^^^^^^^^^^^^^^^^^^

Gives you SSH access to the instance for manual testing.
