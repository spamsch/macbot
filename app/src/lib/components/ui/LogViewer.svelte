<script lang="ts">
  import { ArrowDown, Trash2 } from "lucide-svelte";

  interface LogEntry {
    timestamp: string;
    level: "info" | "warn" | "error" | "success";
    message: string;
  }

  interface Props {
    logs: LogEntry[];
    onclear?: () => void;
  }

  let { logs = [], onclear }: Props = $props();

  let container: HTMLDivElement;
  let autoScroll = $state(true);
  let showScrollButton = $state(false);

  function handleScroll() {
    if (!container) return;
    const isAtBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight <
      50;
    autoScroll = isAtBottom;
    showScrollButton = !isAtBottom && logs.length > 0;
  }

  function scrollToBottom() {
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
      autoScroll = true;
      showScrollButton = false;
    }
  }

  $effect(() => {
    if (autoScroll && container && logs.length > 0) {
      container.scrollTop = container.scrollHeight;
    }
  });

  const levelColors = {
    info: "text-text-muted",
    warn: "text-warning",
    error: "text-error",
    success: "text-success",
  };

  const levelIcons = {
    info: "",
    warn: "",
    error: "",
    success: "",
  };
</script>

<div class="flex flex-col h-full bg-bg rounded-lg border border-border">
  <div
    class="flex items-center justify-between px-4 py-2 border-b border-border"
  >
    <span class="text-sm font-medium text-text">Service Output</span>
    {#if onclear && logs.length > 0}
      <button
        onclick={onclear}
        class="p-1.5 text-text-muted hover:text-text hover:bg-bg-card rounded transition-colors"
        title="Clear logs"
      >
        <Trash2 class="w-4 h-4" />
      </button>
    {/if}
  </div>

  <div
    bind:this={container}
    onscroll={handleScroll}
    class="flex-1 overflow-y-auto font-mono text-sm p-4 space-y-1"
  >
    {#if logs.length === 0}
      <p class="text-text-muted text-center py-8">No logs yet...</p>
    {:else}
      {#each logs as log}
        <div class="flex gap-2 {levelColors[log.level]}">
          <span class="text-text-muted shrink-0">{log.timestamp}</span>
          <span class="break-all">{log.message}</span>
        </div>
      {/each}
    {/if}
  </div>

  {#if showScrollButton}
    <button
      onclick={scrollToBottom}
      class="absolute bottom-16 right-4 p-2 bg-primary text-white rounded-full shadow-lg hover:bg-primary-hover transition-colors"
    >
      <ArrowDown class="w-4 h-4" />
    </button>
  {/if}
</div>
