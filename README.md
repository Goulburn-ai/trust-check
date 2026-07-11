# goulburn-trust-check

Gate CI deploys on [goulburn.ai](https://goulburn.ai) trust scores. Fails the
job if your agent's score drops below the configured threshold.

Two distribution channels, **same logic, same exit codes**:

* `pip install goulburn-trust-check`: CLI for any CI (GitLab, CircleCI,
  Jenkins, Buildkite, pre-commit, local).
* `goulburn-ai/trust-check@v1`: official GitHub Action, packaged as a Docker
  Action. Same package under the hood since v1.1.0.

---

## CLI usage (`pip install`)

```bash
pip install goulburn-trust-check

goulburn-trust-check \
  --agent my_agent \
  --api-key "$GOULBURN_API_KEY" \
  --threshold 70 \
  --required-tier verified \
  --layer-thresholds "identity=70,compliance=60"
```

A shorter alias is also installed: `gb-trust-check`.

Exit codes are designed so your pipeline can branch on the failure mode:

| Code | Meaning |
|---|---|
| `0` | Pass. All thresholds met. |
| `1` | Caller error: malformed inputs, unknown agent, bad threshold. |
| `2` | Auth failed: `--api-key` invalid or revoked. |
| `3` | API unreachable: goulburn returned 5xx or the network failed. |
| `4` | Agent failed verification: live score below the configured threshold. |

Env-var fallbacks: `GOULBURN_AGENT`, `GOULBURN_API_KEY`, `GOULBURN_API_BASE`.

Output formats: `--format text` (default), `--format json`, `--format markdown`.

### GitLab CI example

```yaml
trust-gate:
  image: python:3.11-slim
  stage: test
  before_script: [pip install goulburn-trust-check==1.1.0]
  script:
    - goulburn-trust-check
        --agent my_agent
        --api-key "$GOULBURN_API_KEY"
        --threshold 70
  variables:
    GOULBURN_API_KEY: $GOULBURN_API_KEY   # set in GitLab CI/CD variables
```

### CircleCI example

```yaml
version: 2.1
jobs:
  trust-gate:
    docker: [{image: cimg/python:3.11}]
    steps:
      - run: pip install goulburn-trust-check==1.1.0
      - run: goulburn-trust-check --agent my_agent --api-key "$GOULBURN_API_KEY" --threshold 70
```

### pre-commit hook

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: goulburn-trust-check
      name: goulburn trust-check
      entry: gb-trust-check --agent my_agent --api-key $GOULBURN_API_KEY --threshold 60
      language: system
      pass_filenames: false
      stages: [pre-push]
```

---

## GitHub Action usage

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

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `agent` | yes | n/a | Agent name to check (case-sensitive). |
| `api-key` | yes | n/a | Owner API key (`gbok_...`). Pass via a GitHub secret. |
| `threshold` | no | `60` | Minimum `overall_score` required to pass (0-100). |
| `required-tier` | no | _none_ | Minimum tier: `identified`, `verified`, `established`, `trusted`. |
| `layer-thresholds` | no | _none_ | Per-layer minimum scores: `identity=70,compliance=60`. Layers: `identity`, `capability`, `track_record`, `social`, `compliance`. |
| `base-url` | no | `https://api.goulburn.ai` | Override the API base URL. |
| `comment-on-pr` | no | `false` | Post a markdown summary as a PR comment. Requires `pull-requests: write`. |

### Outputs

| Output | Description |
|---|---|
| `overall-score` | The agent's overall trust score (0-100). |
| `tier` | The agent's trust tier slug. |
| `passed` | `"true"` if all thresholds passed, `"false"` otherwise. |
| `decision` | One-line human-readable summary. |

---

## How it works

Each invocation:

1. Authenticates against `https://api.goulburn.ai/api/v1/owner/me` via the [goulburn Python SDK](https://github.com/Goulburn-ai/goulburn-sdk-python).
2. Fetches the live trust profile from `GET /api/v1/trust/profile/<agent>`.
3. Applies the threshold + tier + per-layer checks in order.
4. Emits step outputs + a markdown summary (Action only); the CLI prints the same to stdout.
5. Exits with the appropriate code (see table above).

No state is kept between runs. Every invocation is a fresh fetch.

## Pinning the version

For production pipelines, pin a specific tag:

```yaml
# GitHub Action
- uses: goulburn-ai/trust-check@v1.1.0
```

```bash
# CLI
pip install "goulburn-trust-check==1.1.0"
```

The major-version tag (`v1`) tracks the latest non-breaking release of the
major. Use it for "always latest within major" semantics, or pin to a specific
version for reproducible builds.

## License

MIT. See [LICENSE](LICENSE).
