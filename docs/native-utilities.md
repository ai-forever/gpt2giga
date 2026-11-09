# Images and native GigaChat utilities

These operations use the configured GigaChat SDK client and the same gateway
authentication and pass-token identity as other public API routes. Availability
of a native operation still depends on the selected model and upstream account.

## OpenAI image generation

`POST /v2/images/generations` generates one image with the GigaChat v2
`image_generate` tool, downloads its file bytes, and returns OpenAI `b64_json`.
The root route works when `GPT2GIGA_GIGACHAT_API_MODE=v2`; `/v1` explicitly rejects
this operation. Generation is submitted once, without retrying an uncertain
upstream result. A missing image or empty file is an error.

```python
import base64
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090/v2", api_key="0")
result = client.images.generate(
    model="gpt-image-1",
    prompt="A lighthouse on a quiet coast, watercolor",
    n=1,
    response_format="b64_json",
)
image_bytes = base64.b64decode(result.data[0].b64_json)
```

Configure `GIGACHAT_MODEL` to a model with image-tool access. The known client
aliases `gpt-image-1`, `gpt-image-1-mini`, `dall-e-2`, and `dall-e-3` select that
configured model; they do not select an OpenAI backend. Explicit reviewed
GigaChat profile aliases resolve to their configured upstream model. External
provider aliases cannot invoke this native operation.

The subset supports only `n=1`, `response_format=b64_json`, and omitted `size`
or `size=auto`. GigaChat chooses the actual image format and dimensions. Edits,
masks, variations, streaming, multiple candidates, explicit dimensions, quality,
and URL responses are rejected before generation. `user` is accepted without
OpenAI billing semantics. No generated file ID is presented as a public URL.

Runnable example: [generate.py](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/images/generate.py).

## Native utility routes

These routes are GigaChat extensions, not OpenAI, Anthropic, or Gemini endpoints.
They do not call chat generation or perform function execution.

| Route | JSON input | Result and limits |
|---|---|---|
| `POST /bridge/gigachat/tokens/count` | `{"input":["hello"],"model":"GigaChat-3-Ultra"}` | Native text token counts; not the full cost of files, images, or an answer. |
| `POST /bridge/gigachat/functions/validate` | A native function JSON schema | Native validation findings, including findings returned with HTTP 200. JSON input only. |
| `GET /bridge/gigachat/balance` | None | Native account balance; available only for eligible accounts, such as prepaid accounts. |
| `POST /bridge/gigachat/ai/check` | `{"input":"Русский текст","model":"GigaChat-3-Ultra"}` | Likelihood of Russian text being AI-generated. This is not Moderations or a safety classifier. |

The text operations use the existing model resolver; omit `model` to use the
configured default. Safe request headers/options and request-scoped credentials
reach the SDK. SDK response transport headers and credentials are not included
in JSON results. Gateway API-key protection also applies to these `/bridge`
routes. Account restrictions remain upstream errors rather than fabricated data.

Runnable example: [utilities.py](https://github.com/ai-forever/gpt2giga/blob/main/examples/native/utilities.py).

Log probabilities retain the existing accepted/ignored policy. SDK field
availability alone does not prove model/account support, and no verified
logprobs profile is enabled by this expansion. The gateway does not manufacture
probabilities or advertise global logprobs support.
