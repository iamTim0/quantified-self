# WHOOP importer

FastAPI health service plus a request-driven NATS consumer for WHOOP cycles,
recovery, sleep and workouts. OAuth tokens are fetched per task from Core and
never configured in this container.

## Updating the generated API client

Save the latest WHOOP schema as `openapi/whoop.json`, then run:

```bash
docker run --rm -v "$PWD:/local" openapitools/openapi-generator-cli generate \
  -i /local/openapi/whoop.json -g python -o /local/generated --additional-properties=packageName=whoop_api
```

Review the generated diff and adapt the stable facade in `client.py`. Only the
OAuth user collection endpoints are used; trusted-partner lab endpoints are not.
