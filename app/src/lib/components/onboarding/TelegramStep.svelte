<script lang="ts">
  import { Button, Input } from "$lib/components/ui";
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-shell";
  import { MessageSquare, ExternalLink, Check, AlertCircle } from "lucide-svelte";
  import { onboardingStore } from "$lib/stores/onboarding";

  interface Props {
    onNext: () => void;
    onBack: () => void;
  }

  let { onNext, onBack }: Props = $props();

  let botToken = $state("");
  let chatId = $state("");
  let saving = $state(false);
  let configured = $state(onboardingStore.state.data.telegram.configured);
  let error = $state<string | null>(null);

  const steps = [
    "Open Telegram and search for @BotFather",
    "Send /newbot and follow the prompts to create your bot",
    "Copy the bot token provided by BotFather",
    "Send a message to your new bot, then come back here",
  ];

  async function openTelegram() {
    await open("https://t.me/BotFather");
  }

  async function saveConfig() {
    if (!botToken.trim()) {
      error = "Please enter your bot token";
      return;
    }

    saving = true;
    error = null;

    try {
      // Validate token format
      if (!/^\d+:[A-Za-z0-9_-]+$/.test(botToken)) {
        error = "Invalid bot token format";
        return;
      }

      // Read existing config
      let config = await invoke<string>("read_config");

      // Update or add Telegram settings
      const lines = config.split("\n").filter((line) => {
        const trimmed = line.trim();
        return (
          trimmed &&
          !trimmed.startsWith("TELEGRAM_BOT_TOKEN=") &&
          !trimmed.startsWith("TELEGRAM_CHAT_ID=")
        );
      });

      lines.push(`TELEGRAM_BOT_TOKEN=${botToken}`);
      if (chatId.trim()) {
        lines.push(`TELEGRAM_CHAT_ID=${chatId}`);
      }

      await invoke("write_config", { content: lines.join("\n") + "\n" });

      configured = true;
      await onboardingStore.updateTelegram({
        configured: true,
        skipped: false,
      });
    } catch (e) {
      error = `Failed to save Telegram config: ${e}`;
    } finally {
      saving = false;
    }
  }

  async function skip() {
    await onboardingStore.updateTelegram({
      configured: false,
      skipped: true,
    });
    onNext();
  }

  function handleContinue() {
    onNext();
  }
</script>

<div class="flex flex-col px-8 py-6">
  <div class="flex items-center gap-3 mb-2">
    <div class="p-2 bg-primary/20 rounded-lg">
      <MessageSquare class="w-6 h-6 text-primary" />
    </div>
    <h2 class="text-2xl font-bold text-text">Telegram Integration</h2>
    <span class="text-xs bg-bg-card text-text-muted px-2 py-1 rounded">
      Optional
    </span>
  </div>

  <p class="text-text-muted mb-6">
    Control Son of Simon from anywhere using Telegram. You can skip this and set
    it up later.
  </p>

  <!-- Setup Steps -->
  <div class="mb-6 p-4 bg-bg-card rounded-lg border border-border">
    <h3 class="font-medium text-text mb-3">How to set up:</h3>
    <ol class="space-y-2">
      {#each steps as step, i}
        <li class="flex items-start gap-3 text-sm">
          <span
            class="w-5 h-5 rounded-full bg-bg-input flex items-center justify-center text-xs text-text-muted shrink-0"
          >
            {i + 1}
          </span>
          <span class="text-text-muted">{step}</span>
        </li>
      {/each}
    </ol>

    <Button variant="secondary" size="sm" onclick={openTelegram} class="mt-4">
      Open Telegram
      <ExternalLink class="w-4 h-4" />
    </Button>
  </div>

  {#if !configured}
    <!-- Bot Token Input -->
    <div class="space-y-4 mb-6">
      <Input
        type="password"
        label="Bot Token"
        placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
        bind:value={botToken}
      />

      <Input
        type="text"
        label="Chat ID (optional)"
        placeholder="Your Telegram user ID"
        bind:value={chatId}
      />

      <p class="text-xs text-text-muted">
        The chat ID will be detected automatically when you send your first
        message to the bot.
      </p>
    </div>

    <Button onclick={saveConfig} loading={saving} disabled={saving}>
      Save Telegram Config
    </Button>
  {:else}
    <div
      class="flex items-center gap-2 p-4 bg-success/10 text-success rounded-lg mb-6"
    >
      <Check class="w-5 h-5" />
      <span class="font-medium">Telegram configured!</span>
    </div>
  {/if}

  {#if error}
    <div
      class="flex items-center gap-2 mt-4 p-4 bg-error/10 text-error rounded-lg"
    >
      <AlertCircle class="w-5 h-5 shrink-0" />
      <span class="text-sm">{error}</span>
    </div>
  {/if}

  <!-- Navigation -->
  <div class="flex justify-between mt-6 pt-6 border-t border-border">
    <Button variant="ghost" onclick={onBack}>Back</Button>
    <div class="flex gap-3">
      {#if !configured}
        <Button variant="secondary" onclick={skip}>Skip for Now</Button>
      {/if}
      <Button onclick={handleContinue} disabled={!configured && !botToken}>
        Continue
      </Button>
    </div>
  </div>
</div>
