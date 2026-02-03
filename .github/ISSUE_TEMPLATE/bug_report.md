---
name: Bug Report
about: Report a bug to help us improve gpt2giga
title: "[BUG] "
labels: bug
assignees: ''
---

## Bug Description

<!-- A clear and concise description of the bug -->

## Environment

### gpt2giga Setup

- **gpt2giga version**: <!-- e.g., 0.5.0 -->
- **Installation method**:
  - [ ] pip (`pip install gpt2giga`)
  - [ ] uv (`uv tool install gpt2giga/ uv add gpt2giga`)
  - [ ] Docker (`docker compose up`)
  - [ ] From source (`pip install git+...`)

- **Python version**: <!-- e.g., 3.10 -->
- **OS**: <!-- e.g., Ubuntu 22.04, macOS 14.0, Windows 11 -->

### GigaChat Configuration

- **GigaChat model**: <!-- e.g., GigaChat, GigaChat-2-Max -->
- **Auth settings**: <!-- e.g., OAuth(scope+creds), Basic(user+password) -->

## How to Reproduce

### Method Used

- [ ] OpenAI Python SDK
- [ ] curl
- [ ] Other: <!-- specify -->

### Request Payload

<!--
Provide the full request you're sending.
Remove any sensitive data (credentials, tokens, etc.)
-->

<details>
<summary>Request</summary>

**For OpenAI SDK:**

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="your-key")

# Your request here
completion = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Your message"}
    ],
    # ... other parameters
)
```

**For curl:**

```bash
curl -X POST http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-key" \
  -d '{
    "model": "gpt-4",
    "messages": [
      {"role": "user", "content": "Your message"}
    ]
  }'
```

</details>

### Steps to Reproduce

1. Start gpt2giga with: `...`
2. Send request: `...`
3. See error

## Expected Behavior

<!-- What you expected to happen -->

## Actual Behavior

<!-- What actually happened -->

## Error Output

<details>
<summary>Error message / Traceback</summary>

```
Paste your error or traceback here
```

</details>

## Logs

<!--
Set GPT2GIGA_LOG_LEVEL=DEBUG and provide relevant logs.
Remove any sensitive information!
-->

<details>
<summary>gpt2giga logs (DEBUG level)</summary>

```
Paste relevant logs here
```

</details>

## Configuration

<!-- Provide your .env file content (remove sensitive values!) -->

<details>
<summary>.env configuration</summary>

```dotenv
GPT2GIGA_HOST=localhost
GPT2GIGA_PORT=8090
GPT2GIGA_LOG_LEVEL=DEBUG
# ... other settings
```

</details>

## Additional Context

<!-- Add any other context about the problem here -->

## Possible Solution

<!-- Optional: If you have any ideas on how to fix this -->
