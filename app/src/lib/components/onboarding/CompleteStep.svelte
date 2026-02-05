<script lang="ts">
  import { Button } from "$lib/components/ui";
  import { Check, Rocket } from "lucide-svelte";
  import { onboardingStore } from "$lib/stores/onboarding.svelte";

  interface Props {
    onLaunch: () => void;
  }

  let { onLaunch }: Props = $props();

  let launching = $state(false);

  const summary = $derived([
    {
      label: "AI Provider",
      value:
        onboardingStore.state.data.api_key.provider === "anthropic"
          ? "Anthropic (Claude)"
          : "OpenAI",
      done: onboardingStore.state.data.api_key.configured,
    },
    {
      label: "Telegram",
      value: onboardingStore.state.data.telegram.configured
        ? "Configured"
        : "Skipped",
      done: onboardingStore.state.data.telegram.configured,
    },
  ]);

  async function handleLaunch() {
    launching = true;
    await onboardingStore.complete();
    onLaunch();
  }
</script>

<div class="flex flex-col items-center text-center px-8 py-6">
  <div
    class="w-20 h-20 bg-success/20 rounded-full flex items-center justify-center mb-6 animate-bounce"
  >
    <Check class="w-10 h-10 text-success" />
  </div>

  <h1 class="text-3xl font-bold text-text mb-3">You're All Set!</h1>

  <p class="text-text-muted mb-8 max-w-md">
    Son of Simon is ready to help you automate your Mac. The service will start
    running and you'll see its output in the dashboard.
  </p>

  <!-- Summary -->
  <div class="w-full max-w-sm mb-8">
    <h3 class="text-sm font-medium text-text-muted mb-3 text-left">Summary</h3>
    <div class="space-y-2">
      {#each summary as item}
        <div
          class="flex items-center justify-between p-3 bg-bg-card rounded-lg border border-border"
        >
          <span class="text-sm text-text-muted">{item.label}</span>
          <div class="flex items-center gap-2">
            <span class="text-sm text-text">{item.value}</span>
            {#if item.done}
              <Check class="w-4 h-4 text-success" />
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </div>

  <Button size="lg" onclick={handleLaunch} loading={launching}>
    <Rocket class="w-5 h-5" />
    Launch Dashboard
  </Button>
</div>
