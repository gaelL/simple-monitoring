# Simple monitoring

This Docker compose will deploy a prometheus + grafana + node exporter to collect locally metrics

links:
  * https://www.cloudbees.com/blog/monitoring-your-synchronous-python-web-applications-using-prometheus
  * https://grafana.com/grafana/dashboards/1860-node-exporter-full/


# Run

```
docker-compose up --force-recreate --build
```

Run with smokepyng
```
# Create your own config file from smokepyng/conf.yaml.sample
docker-compose -f docker-compose.yml -f docker-compose.smokepyng.yml up --force-recreate --build
```
Note: Smokepyng is a little python exporter based on https://github.com/shaftmx/smokepyng. It is a troubleshooting framework/script, you can implement whatever you need to track here.
Currently it contains function to track S3 bucket, vault and HTTP request time.

# Config

Env vars:

  * `PROMETHEUS_RETENTION_TIME`: default `90d`
