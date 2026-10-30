"""Library of mocks used by the tests"""

experiment_spec_mock = """
    experiment:
      version: 0.0.1
      orchestrator: docker-compose
      responses:
        - my_metric_response_no_params:
            metric_name: prometheus_metric
            type: metric
            target: sue
            step: 5
            left_window: 2m
            right_window: 0m
        - otelcol_spans:
            metric_name: otelcol_exporter_sent_spans
            type: metric
            target: sue
            labels: {exporter: logging}
            step: 1
            left_window: 2m
            right_window: 2m
        - my_trace_response:
            type: trace
            service_name: adservice
            left_window: 5m
            right_window: 2m
      treatments:
         - pause_treatment:
            action: pause
            params:
                duration: 30s
                service_name: frontend
      sue:
        compose: /Users/witch/opentelemetry-demo/docker-compose.yml
        exclude: [loadgenerator]
        include: [otelcol]
      loadgen:
        run_time: 20s
    """
metric_rvar_description_mock = {
    "some_prometheus_metric": {
        "type": "metric",
        "metric_name": "otelcol_exporter_sent_spans",
        "step": "1",
        "labels": {
            "exporter": "logging",
        },
        "left_window": "2m",
        "right_window": "0m",
    }
}
screening_experiment_mock = """
experiment:
  responses:
    - recommendation_service_traces:
        type: trace
        service_name: recommendationservice
        left_window: 30s
        right_window: 30s
        limit: 1000
  sue:
    compose: /Users/witch/opentelemetry-demo/docker-compose.yml
    exclude: [loadgenerator]
  loadgen:
    run_time: 30s
    tasks:
    - { endpoint: /, verb: get, weight: 1, params: { } }
    - { endpoint: /api/products/0PUK6V6EV0, verb: get, weight: 1, params: { } }
    - { endpoint: /api/recommendations, verb: get, weight: 1, params: {"productIds": ["1YMWWN1N4O"]}}
    - { endpoint: /api/cart, verb: get, weight: 1, params: {}}
    - { endpoint: /api/data, verb: get, weight: 1, params: {"contextKeys": ["telescopes"]}}
"""

kubernetes_experiment = """
# inject a packet delay of 0-90ms while increasing the otel metric inverval to 1s
experiment:
  version: 0.0.1
  orchestrator: kubernetes
  services:
    jaeger: {name: jaeger, namespace: system-under-evaluation}
    prometheus: [
      {name: prometheus, namespace: system-under-evaluation, target: sue},
      {name: kube-prometheus-kube-prome-prometheus, namespace: oxn-external-monitoring, target: oxn},
    ]
  responses:
    - recommendations_total:
        type: metric
        target: sue
        metric_name: increase(app_recommendations_counter_total[90s])
        left_window: 240s
        right_window: 240s
        step: 1
  treatments:
    - empty_treatment:
        action: empty
        params: {duration: 1m}
  sue:
    compose: opentelemetry-demo/docker-compose.yml
    exclude: [loadgenerator]
    required: [{namespace: monitoring, name: grafana}, {namespace: monitoring, name: node-exporter}]
  loadgen:
    run_time: 10m
    locust_files: [{path: locust/locust_basic_interaction.py}]
    target: {name: frontend-proxy, namespace: system-under-evaluation, port: 8080}
"""