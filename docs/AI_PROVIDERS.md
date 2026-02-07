# AI Providers and Models

Son of Simon works with multiple AI providers. Pick one during setup or change it later in `~/.macbot/.env`.

| Provider | Models | Key prefix |
|---|---|---|
| **Anthropic** | Claude Sonnet 4.5, Opus 4.6, Haiku 4.5 | `sk-ant-` |
| **OpenAI** | GPT-5.2, GPT-5.2 Pro, GPT-5.1, GPT-5 Mini, o4-mini | `sk-proj-` |
| **OpenRouter** | DeepSeek V3.2, Gemini 2.5 Flash/Pro, GLM 4.7, Llama 4 Maverick, Qwen 3, Grok 4.1 | `sk-or-` |

OpenRouter gives you access to dozens of models with a single API key. Good if you want to experiment.

<p align="center">
  <img src="images/settings.png" alt="Settings" width="500">
</p>

## Configuration

Set your provider and API key in `~/.macbot/.env`:

```bash
MACBOT_LLM_PROVIDER=anthropic      # or openai, or any LiteLLM provider
MACBOT_ANTHROPIC_API_KEY=sk-ant-...
```

You can also configure this through the setup wizard or the dashboard settings page.
