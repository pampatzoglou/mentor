# values.schema.json

Recommended for charts with complex or user-facing values. Catches typos and wrong types at `helm lint` / `helm template` time — before manifests reach the cluster. Not every chart needs one on day one, but add one when values grow beyond a handful of keys or when multiple teams consume the chart:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["image"],
  "properties": {
    "replicaCount": {
      "type": "integer",
      "minimum": 0
    },
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "repository": { "type": "string" },
        "tag":        { "type": "string" },
        "pullPolicy": {
          "type": "string",
          "enum": ["Always", "IfNotPresent", "Never"]
        }
      }
    }
  }
}
```

Cover required keys and any key whose type is easy to get wrong. You don't need to be exhaustive.
