# openserp

[![PyPI version](https://img.shields.io/pypi/v/openserp.svg)](https://pypi.org/project/openserp/)
[![Python versions](https://img.shields.io/pypi/pyversions/openserp.svg)](https://pypi.org/project/openserp/)
[![License](https://img.shields.io/pypi/l/openserp.svg)](https://github.com/openserpapi/sdk-python/blob/main/LICENSE.md)

```bash
pip install openserp
```

Cloud:

```python
import os
from openserp import OpenSERP

client = OpenSERP(api_key=os.environ["OPENSERP_API_KEY"])
resp = client.search(engine="google", text="openserp")

print(resp.results[0].title, resp.results[0].url)
```

Self-hosted:

```python
from openserp import OpenSERP

client = OpenSERP(base_url="http://localhost:7000")
resp = client.search(engine="bing", text="openserp")

print(resp.results[0].title, resp.results[0].url)
```

Python SDK for the **OpenSERP** multi-engine SERP API - Google, Bing, Yandex, Baidu, DuckDuckGo, and Ecosia results in a single call. Works against the self-hosted [open-source server](https://github.com/karust/openserp) and against [OpenSERP Cloud](https://openserp.org/cloud) with the same code.

Use it for AI grounding, RAG pipelines, LLM tool use, agent tool use, LangChain / LlamaIndex integrations, SEO rank tracking, competitor analysis, and search-powered automations. Open-source alternative to SerpAPI, DataForSEO, ScrapingBee, Bright Data SERP, Oxylabs SERP, and Zenserp.

> Also available for TypeScript / JavaScript: [`@openserp/sdk`](https://www.npmjs.com/package/@openserp/sdk).

> **Alpha - the API may change before `1.0.0`.** Pin a version in production.

## Contents

- [Install](#install)
- [Why OpenSERP](#why-openserp)
- [Quickstart - OSS (self-hosted)](#quickstart---oss-self-hosted)
- [Quickstart - Cloud](#quickstart---cloud)
- [Why two backends?](#why-two-backends)
- [Search](#search)
- [Extract](#extract)
- [Images](#images)
- [Async](#async)
- [Endpoint availability](#endpoint-availability)
- [Telemetry](#telemetry)
- [Error handling](#error-handling)
- [Retry hook](#retry-hook)
- [Use cases](#use-cases)

## Install

```bash
pip install openserp
```

DataFrame export is an optional extra:

```bash
pip install "openserp[pandas]"
```

Requires Python 3.10+.

## Why OpenSERP

| Need | OpenSERP fit |
| --- | --- |
| Local development | Run the OSS server and use the same SDK surface as Cloud. |
| AI grounding | Pull fresh SERP snippets and optional extracted page text for prompts, RAG, or agents. |
| SEO checks | Query Google, Bing, Yandex, Baidu, DuckDuckGo, and Ecosia with typed models. |
| Migration path | Start self-hosted, then switch to Cloud by adding `OPENSERP_API_KEY`. |

Compared with hosted-only SERP APIs, OpenSERP keeps the client contract portable. You can test locally without an API key, then use the hosted API when you want managed infrastructure.

## Quickstart - OSS (self-hosted)

Run the open-source server locally, no API key required:

```bash
docker run -p 7000:7000 karust/openserp serve
```

```python
from openserp import OpenSERP

client = OpenSERP(base_url="http://localhost:7000")

resp = client.search(
    engine="google",
    text="openserp",
    limit=10,
    region="US",
)

print(resp.results[0].title, resp.results[0].url)
```

If you pass no options, the client defaults to `http://localhost:7000`.

## Quickstart - Cloud

Get an API key from the [API keys](https://openserp.org/dashboard/keys) section in the dashboard. When `api_key` is set, the SDK defaults `base_url` to `https://api.openserp.org/v1` and sends `Authorization: Bearer ...` for you.

```python
import os
from openserp import OpenSERP

client = OpenSERP(api_key=os.environ["OPENSERP_API_KEY"])

resp = client.search(engine="google", text="openserp")

print(resp.results[0].title)
print(client.last_response.credits)  # CreditInfo(used=..., remaining=...)
```

If both `base_url` and `api_key` are set, `base_url` wins and the key is still sent. Use this for an authenticated self-hosted deployment. Add `backend="oss"` when you also need OSS-only methods such as `stats()` or `health()`.

## Why two backends?

OpenSERP Cloud uses the same public HTTP contract as the OSS server, with a `/v1/` prefix and bearer auth. The same SDK call works on both; you only change `base_url` / `api_key`. Start with OSS locally, then move to Cloud when you want the hosted API. See [openserp.org/docs/oss-vs-cloud](https://openserp.org/docs/oss-vs-cloud) for the full comparison.

## Search

```python
single = client.search(engine="bing", text="golang", limit=10, region="US")

mega = client.mega_search(
    text="golang",
    engines=["google", "bing", "yandex"],
    mode="balanced",
    limit=20,
)

fast = client.fast_search(text="golang", engines=["google", "bing"])
any_ = client.any_search(text="golang", engines=["google", "yandex"])
```

`mega_search` aggregates multiple engines. `mode` is `"balanced"` (default, merged and deduplicated), `"any"` (first successful engine wins), or `"fast"` (engines reordered by recent health). `fast_search` / `any_search` are sugar for the matching mode.

To enrich top search results with cleaned page content, pass the extraction flags:

```python
grounded = client.search(
    engine="google",
    text="openserp docs",
    extract=3,
    extract_mode="auto",
    min_runes=500,
)

print(grounded.results[0].extracted.content)
```

## Extract

```python
page = client.extract(
    url="https://openserp.org/docs",
    mode="auto",
    clean=True,
)

print(page.markdown)
```

Use `min_runes` to set the auto-mode escalation floor, `clean=False` for whole-page readable extraction, and `use_llms_txt=True` to prefer `/llms-full.txt` or `/llms.txt` for site-root URLs. Non-JSON formats are returned as strings:

```python
markdown = client.extract(url="https://openserp.org", format="markdown")
```

## Images

```python
images = client.image(engine="bing", text="golang logo", limit=20)

mega_images = client.mega_image(text="golang logo", engines=["bing", "google"])
```

## Async

```python
import asyncio, os
from openserp import AsyncOpenSERP


async def main() -> None:
    async with AsyncOpenSERP(api_key=os.environ["OPENSERP_API_KEY"]) as client:
        resp = await client.search(engine="google", text="openserp")
        print(resp.results[0].title)


asyncio.run(main())
```

Run hundreds of queries concurrently with a semaphore:

```python
import asyncio
from openserp import AsyncOpenSERP


async def main() -> None:
    sem = asyncio.Semaphore(20)
    queries = [f"keyword {i}" for i in range(500)]

    async with AsyncOpenSERP() as client:
        async def run(query: str):
            async with sem:
                return await client.search(engine="google", text=query, limit=10)

        responses = await asyncio.gather(*(run(q) for q in queries))
        print(len(responses))


asyncio.run(main())
```

## Endpoint availability

OSS-only operational methods raise `OssOnlyError` when the client is configured for Cloud:

```python
client.parse_google(html="<html>...</html>")
client.stats()
client.health()
```

Cloud-only account methods raise `CloudOnlyError` when the client is configured for OSS:

```python
client.me()
client.pricing()
client.engines_status()
client.engines_capabilities()
```

The backend is inferred from `base_url` and `api_key`. Pass `backend="oss"` or `backend="cloud"` to the constructor to override.

## Telemetry

`client.last_response` is updated after every HTTP response:

```python
client.last_response.credits          # Cloud - CreditInfo(used, remaining)
client.last_response.engine_used      # both - X-Engine-Used
client.last_response.fallback_engine  # OSS only
client.last_response.cache            # OSS only
client.last_response.headers          # raw response headers (lower-cased)
```

Some self-hosted operational headers are not part of the Cloud response contract, so expect those fields to be `None` against `api.openserp.org`. `credits` is Cloud-specific.

## Error handling

```python
from openserp import OpenSERP, RateLimitError, CaptchaError, SERPError

client = OpenSERP(api_key="...")

try:
    client.search(engine="google", text="openserp")
except RateLimitError:
    # slow down or queue the request
    ...
except CaptchaError:
    # inspect the upstream search failure and retry later
    ...
except SERPError as err:
    print(err.status, err.code, err.reason, err.request_id)
```

## Retry hook

The SDK does not apply a retry policy. Provide a hook when you want one:

```python
import os, random, time
from openserp import OpenSERP, SERPError

RETRYABLE = {408, 429, 500, 502, 503}
client: OpenSERP


def should_retry(err: Exception, attempt: int) -> bool:
    if attempt >= 3 or not isinstance(err, SERPError) or err.status not in RETRYABLE:
        return False
    headers = client.last_response.headers if client.last_response else {}
    retry_after = float(headers.get("retry-after", 0) or 0)
    wait = retry_after or min(2 ** attempt * 0.25, 8.0)
    time.sleep(wait + random.random() * 0.25)
    return True


client = OpenSERP(api_key=os.environ["OPENSERP_API_KEY"], retry=should_retry)
client.search(engine="google", text="openserp")
```

## Use cases

- **AI grounding / RAG** - feed top-N results into an LLM prompt (OpenAI, Anthropic, Ollama) for up-to-date answers.
- **LLM tool use** - expose `client.search` as a tool to your agent.
- **SEO monitoring** - daily rank tracking across multiple engines and regions, export to a DataFrame or Sheets.
- **Competitor analysis** - weekly diff of top-10 results for a keyword set.
- **Data pipelines** - stream SERPs to ClickHouse, BigQuery, or a DataFrame for NLP on snippets.

Quick SEO rank report with `pandas`:

```python
import pandas as pd
from openserp import OpenSERP

client = OpenSERP()
keywords = ["openserp", "serp api", "google search api"]
frames = []

for keyword in keywords:
    resp = client.search(engine="google", text=keyword, region="US", limit=10)
    frame = resp.to_pandas()
    frame["keyword"] = keyword
    frames.append(frame)

pd.concat(frames, ignore_index=True).to_csv("rank-report.csv", index=False)
```
