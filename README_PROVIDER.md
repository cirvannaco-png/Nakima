# AI Provider — GitHub Models (default)

Nakima ships with the free **GitHub Models** provider enabled by default, so
you do not need an Anthropic, OpenAI, or DeepSeek account to run it.

## Setup

1. Open <https://github.com/settings/personal-access-tokens/new> and create
   a **fine-grained** personal access token.
2. Under **Account permissions**, grant **Models: Read only**. No repository
   permissions are required for inference (grant those separately if you also
   use the same token for the GitHub App / PR automation).
3. Copy the token into your `.env`:

   ```env
   DEFAULT_AI_PROVIDER=github
   GITHUB_TOKEN=github_pat_...
   GITHUB_MODELS_MODEL=openai/gpt-4o-mini
   ```

4. That's it. `providers.implementations.github_models.GitHubModelsProvider`
   will be selected automatically and calls
   `https://models.github.ai/inference/chat/completions`.

## Switching models

Any model listed at <https://github.com/marketplace/models> works. Common
free-tier options:

| `GITHUB_MODELS_MODEL`             | Notes                                   |
| --------------------------------- | --------------------------------------- |
| `openai/gpt-4o-mini`              | Default — fast, cheap, good at codegen. |
| `openai/gpt-4o`                   | Higher quality, slower.                 |
| `meta/Meta-Llama-3.1-70B-Instruct`| Open-weights alternative.               |
| `mistral-ai/Mistral-Large-2411`   | Long-context reasoning.                 |

## Inside GitHub Actions

You can skip the PAT entirely — the built-in `GITHUB_TOKEN` works if the job
grants `models: read`:

```yaml
permissions:
  contents: read
  models: read
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  DEFAULT_AI_PROVIDER: github
```

## Falling back to Anthropic / OpenAI

The old providers are still supported. Set `DEFAULT_AI_PROVIDER=claude` (or
`openai`) and provide the matching API key. See `core/config.py`.
