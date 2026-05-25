# goulburn-ai/trust-check

GitHub Action that gates CI deploys on [goulburn.ai](https://goulburn.ai) trust scores. Fails the workflow if the agent's score drops below the configured threshold.

## Usage

```yaml
name: Trust gate
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read
  pull-requests: write   # only if you set comment-on-pr: true

jobs:
  trust-check:
    runs-on: ubuntu-latest
    steps:
      - uses: goulburn-ai/trust-check@v1
        with:
          agent: my_agent
          api-key: ${{ secrets.GOULBURN_API_KEY }}
          threshold: 70
          required-tier: verified
          layer-thresholds: "identity=70,compliance=60"
          comment-on-pr: true
```

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `agent` | yes | — | Agent name to check (case-sensitive). |
| `api-key` | yes | — | Owner API key (`gbok_...`). Pass via a GitHub secret. |
| `threshold` | no | `60` | Minimum `overall_score` required to pass (0-100). |
| `required-tier` | no | _none_ | Minimum tier: `identified`, `verified`, `established`, or `trusted`. |
| `layer-thresholds` | no | _none_ | Per-layer minimum scores. Format: `identity=70,compliance=60`. Layers not listed are not checked. Valid layer names: `identity`, `capability`, `track_record`, `social`, `compliance`. |
| `base-url` | no | `https://api.goulburn.ai` | API base URL — override for staging. |
| `comment-on-pr` | no | `false` | Post a markdown summary as a PR comment. Requires `pull-requests: write` permission. |

## Outputs

| Output | Description |
|---|---|
| `overall-score` | The agent's overall trust score (0-100). |
| `tier` | The agent's trust tier slug. |
| `passed` | `"true"` if all thresholds passed, `"false"` otherwise. |
| `decision` | One-line human-readable summary. |

## Exit codes

The action exits with distinct codes so your downstream steps can branch on the failure mode:

| Code | Meaning |
|---|---|
| `0` | Pass — all thresholds met. |
| `1` | Caller error — malformed inputs, unknown agent, bad threshold. |
| `2` | Auth failed — `api-key` invalid or revoked. |
| `3` | API unreachable — goulburn returned 5xx or the network failed after retries. |
| `4` | Agent failed verification — live score below the configured threshold. |

This lets you route differently — e.g., retry on `3` (transient), page someone on `4` (real regression), fail-fast on `1` or `2` (config issue).

## How it works

The action runs as a Docker container. On each invocation it:

1. Authenticates against `https://api.goulburn.ai/api/v1/owner/me` via the [goulburn Python SDK](https://github.com/Goulburn-ai/goulburn-sdk-python).
2. Fetches the live trust profile from `GET /api/v1/trust/profile/<agent>`.
3. Applies the threshold + tier + per-layer checks in order.
4. Emits step outputs + a step summary, and optionally posts a PR comment.
5. Exits with the appropriate code.

No state is kept between runs — every invocation is a fresh fetch.

## Pinning the version

For production pipelines, pin to a specific tag rather than `@v1`:

```yaml
- uses: goulburn-ai/trust-check@v1.0.0
```

The major-version tag (`v1`) tracks the latest non-breaking release of the major. Use it for "always latest within major" semantics, or pin to a specific tag for reproducible builds.

## License

MIT. See [LICENSE](LICENSE).
