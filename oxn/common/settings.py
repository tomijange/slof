"""
Purpose: Defines configuration constants.
Functionality: Contains static settings like storage file names.
Connection: Referenced throughout the application for consistent configuration values.

"""

STORAGE_NAME = "store.h5"
TRIE_NAME = "trie.pickle"
PROMETHEUS_PORT = 9090
"""The port of the HTTP API of every Prometheus oxn reads from"""
JAEGER_PORT = 16686
"""The port of the query service of Jaeger"""
GRAFANA_PORT = 80
"""The port of the Grafana service"""
LOCUST_IMAGE = "locustio/locust:2.37.9"
"""The image of the in-cluster Locust, the version requirements.txt pins for oxn"""
