"""
Export Salt-internal metrics to an InfluxDB v2 server.

:depends: `influxdb-client` Python module

See the ref:`returner module docs <influxdb2-metrics-config>` for
general configuration details.


"""

class InfluxDB2Exporter:
    running = True

    def __init__(self, config, interval=30):
        self.config = config
        self.interval = interval

    def run(self):
        fail_ctr = 0
        while self.running:
            # gather metrics
            # post to influx
            # sleep
