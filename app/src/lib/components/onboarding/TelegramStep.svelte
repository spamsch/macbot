<script lang="ts">
  import { Button, Input } from "$lib/components/ui";
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-shell";
  import { Command } from "@tauri-apps/plugin-shell";
  import { resourceDir, join, dirname } from "@tauri-apps/api/path";
  import { MessageSquare, ExternalLink, Check, AlertCircle, ArrowRight, ArrowLeft, Info, Smartphone, Loader2 } from "lucide-svelte";
  import { onboardingStore } from "$lib/stores/onboarding.svelte";

  interface Props {
    onNext: () => void;
    onBack: () => void;
  }

  let { onNext, onBack }: Props = $props();

  let botToken = $state("");
  let saving = $state(false);
  let configured = $state(onboardingStore.state.data.telegram.configured);
  let chatIdDetected = $state(false);
  let detectingChatId = $state(false);
  let error = $state<string | null>(null);

  async function openTelegram() {
    await open("https://t.me/BotFather");
  }

  async function saveConfig() {
    if (!botToken.trim()) {
      error = "Please paste your bot token in the field above";
      return;
    }

    saving = true;
    error = null;

    try {
      // Validate token format
      if (!/^\d+:[A-Za-z0-9_-]+$/.test(botToken)) {
        error = "This doesn't look like a valid bot token. It should look like: 123456789:ABCdefGHI...";
        return;
      }

      // Read existing config
      let config = await invoke<string>("read_config");

      // Update or add Telegram settings
      const lines = config.split("\n").filter((line) => {
        const trimmed = line.trim();
        return (
          trimmed &&
          !trimmed.startsWith("MACBOT_TELEGRAM_BOT_TOKEN=") &&
          !trimmed.startsWith("MACBOT_TELEGRAM_CHAT_ID=")
        );
      });

      lines.push(`MACBOT_TELEGRAM_BOT_TOKEN=${botToken}`);

      await invoke("write_config", { content: lines.join("\n") + "\n" });

      configured = true;
      await onboardingStore.updateTelegram({
        configured: true,
        skipped: false,
      });
    } catch (e) {
      error = `Something went wrong: ${e}`;
    } finally {
      saving = false;
    }
  }

  async function detectChatId() {
    detectingChatId = true;
    error = null;

    try {
      const resourcePath = await resourceDir();
      const contentsPath = await dirname(resourcePath);
      const sonPath = await join(contentsPath, "MacOS", "son");

      // Run `son telegram detect-chat-id` which polls for a message and returns the chat ID
      const command = Command.create("exec-sh", [
        "-c",
        `"${sonPath}" telegram detect-chat-id 2>&1`,
      ]);
      const result = await command.execute();
      const output = result.stdout.trim();

      // Parse the chat ID from the output (format: "CHAT_ID=12345")
      const match = output.match(/CHAT_ID=(\d+)/);
      if (match) {
        const chatId = match[1];

        // Write chat ID to config
        let config = await invoke<string>("read_config");
        const lines = config.split("\n").filter((line) => {
          return !line.trim().startsWith("MACBOT_TELEGRAM_CHAT_ID=");
        });
        lines.push(`MACBOT_TELEGRAM_CHAT_ID=${chatId}`);
        await invoke("write_config", { content: lines.join("\n") + "\n" });

        chatIdDetected = true;
      } else {
        error = "No message received. You can try again, or skip and set it up later.";
      }
    } catch (e) {
      error = `Detection failed: ${e}`;
    } finally {
      detectingChatId = false;
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

<div class="flex flex-col px-10 py-8">
  <div class="flex items-center gap-3 mb-3">
    <div class="p-2 bg-primary/10 rounded-lg">
      <Smartphone class="w-6 h-6 text-primary" />
    </div>
    <h2 class="text-2xl font-bold text-text">Control From Your Phone</h2>
    <span class="text-xs bg-primary/10 text-primary px-2 py-1 rounded-full font-medium">
      Optional
    </span>
  </div>

  <p class="text-text-muted mb-6">
    Want to send commands to your Mac from anywhere? Connect Telegram and you can text
    Son of Simon from your phone, even when you're not at your computer.
  </p>

  <!-- What is this? -->
  <div class="flex items-start gap-3 p-4 bg-bg-card rounded-xl border border-border mb-6">
    <Info class="w-5 h-5 text-primary shrink-0 mt-0.5" />
    <div>
      <p class="text-sm text-text-muted">
        <strong class="text-text">How does this work?</strong> You'll create a personal Telegram bot
        that only you can use. When you send it a message, Son of Simon will receive it and
        perform the task on your Mac.
      </p>
    </div>
  </div>

  {#if !configured}
    <!-- Setup Steps -->
    <div class="mb-6 p-5 bg-bg-card rounded-xl border border-border">
      <h3 class="font-semibold text-text mb-4">How to set up Telegram:</h3>
      <ol class="text-sm text-text-muted space-y-3 mb-5">
        <li class="flex gap-3">
          <span class="w-6 h-6 rounded-full bg-primary text-white flex items-center justify-center text-xs font-bold shrink-0">1</span>
          <span>Open Telegram on your phone or computer and search for <strong class="text-text">@BotFather</strong></span>
        </li>
        <li class="flex gap-3">
          <span class="w-6 h-6 rounded-full bg-primary text-white flex items-center justify-center text-xs font-bold shrink-0">2</span>
          <span>Send the message <strong class="text-text">/newbot</strong> and follow the instructions to name your bot</span>
        </li>
        <li class="flex gap-3">
          <span class="w-6 h-6 rounded-full bg-primary text-white flex items-center justify-center text-xs font-bold shrink-0">3</span>
          <span>BotFather will give you a token (a long string of numbers and letters) - copy it</span>
        </li>
        <li class="flex gap-3">
          <span class="w-6 h-6 rounded-full bg-primary text-white flex items-center justify-center text-xs font-bold shrink-0">4</span>
          <span>Paste the token below and click "Save"</span>
        </li>
      </ol>
      <Button variant="secondary" onclick={openTelegram}>
        Open Telegram BotFather
        <ExternalLink class="w-4 h-4" />
      </Button>
    </div>

    <!-- Bot Token Input -->
    <div class="mb-6">
      <Input
        type="password"
        label="Paste your bot token here"
        placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz..."
        bind:value={botToken}
        error={error ?? undefined}
      />
    </div>

    <Button onclick={saveConfig} loading={saving} disabled={saving || !botToken.trim()}>
      {saving ? "Saving..." : "Save Bot Token"}
    </Button>
  {:else}
    <!-- Token saved -->
    <div class="flex items-center gap-3 p-5 bg-success/10 rounded-xl border border-success/30 mb-6">
      <div class="w-10 h-10 rounded-full bg-success/20 flex items-center justify-center">
        <Check class="w-6 h-6 text-success" />
      </div>
      <div>
        <p class="font-semibold text-success">Bot token saved!</p>
        <p class="text-sm text-text-muted">
          {#if chatIdDetected}
            Chat ID detected. You're all set!
          {:else}
            One more step — link your Telegram account below.
          {/if}
        </p>
      </div>
    </div>

    <!-- Chat ID Detection -->
    {#if !chatIdDetected}
      <div class="mb-6 p-5 bg-bg-card rounded-xl border border-border">
        <h3 class="font-semibold text-text mb-2">Link your Telegram account</h3>
        <p class="text-sm text-text-muted mb-4">
          Open Telegram and send any message (e.g. "hello") to your new bot,
          then click the button below. This lets Son of Simon send you proactive
          updates like heartbeat results.
        </p>

        <Button
          onclick={detectChatId}
          loading={detectingChatId}
          disabled={detectingChatId}
        >
          {#if detectingChatId}
            <Loader2 class="w-4 h-4 animate-spin" />
            Waiting for your message...
          {:else}
            Detect My Chat ID
          {/if}
        </Button>
      </div>
    {:else}
      <div class="flex items-center gap-3 p-5 bg-success/10 rounded-xl border border-success/30 mb-6">
        <div class="w-10 h-10 rounded-full bg-success/20 flex items-center justify-center">
          <Check class="w-6 h-6 text-success" />
        </div>
        <div>
          <p class="font-semibold text-success">Chat ID linked!</p>
          <p class="text-sm text-text-muted">Son of Simon can now send you proactive messages.</p>
        </div>
      </div>
    {/if}
  {/if}

  {#if error && !configured}
    <div class="flex items-start gap-3 mt-4 p-4 bg-error/10 rounded-xl border border-error/30">
      <AlertCircle class="w-5 h-5 text-error shrink-0 mt-0.5" />
      <div>
        <p class="font-medium text-error">There was a problem</p>
        <p class="text-sm text-text-muted">{error}</p>
      </div>
    </div>
  {/if}

  <!-- Navigation -->
  <div class="flex justify-between mt-6 pt-6 border-t border-border">
    <Button variant="ghost" onclick={onBack}>
      <ArrowLeft class="w-4 h-4" />
      Back
    </Button>
    <div class="flex gap-3">
      {#if !configured}
        <Button variant="secondary" onclick={skip}>
          Skip for Now
        </Button>
      {/if}
      <Button onclick={handleContinue}>
        {configured ? "Continue" : "Continue"}
        <ArrowRight class="w-4 h-4" />
      </Button>
    </div>
  </div>
</div>
