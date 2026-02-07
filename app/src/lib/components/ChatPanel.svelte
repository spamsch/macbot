<script lang="ts">
  import { Button } from "$lib/components/ui";
  import { chatStore, type ChatMessage, type ToolCall } from "$lib/stores/chat.svelte";
  import { marked } from "marked";
  import { onMount } from "svelte";

  // Configure marked for inline rendering (no wrapping <p> tags for single lines)
  marked.setOptions({ breaks: true, gfm: true });

  function renderMarkdown(text: string): string {
    return marked.parse(text, { async: false }) as string;
  }
  import {
    Send,
    RotateCcw,
    Trash2,
    Loader2,
    AlertCircle,
    Wifi,
    WifiOff,
    Wrench,
    Check,
    X,
  } from "lucide-svelte";

  interface Props {
    visible: boolean;
    onclose: () => void;
  }

  let { visible, onclose }: Props = $props();

  let inputText = $state("");
  let inputEl: HTMLTextAreaElement | undefined = $state();
  let transcriptEl: HTMLDivElement | undefined = $state();

  // Track previous message count to detect new messages vs streaming updates
  let prevMessageCount = $state(0);

  // Auto-scroll to bottom when new messages arrive
  $effect(() => {
    const count = chatStore.messages.length;
    const lastMsg = chatStore.messages[count - 1];
    // Access text to track streaming updates
    const _ = lastMsg?.text;

    if (transcriptEl) {
      if (count > prevMessageCount) {
        // New message added — always scroll to bottom
        prevMessageCount = count;
        requestAnimationFrame(() => {
          transcriptEl?.scrollTo({ top: transcriptEl.scrollHeight });
        });
      } else {
        // Streaming text update on existing message — only scroll if near bottom
        const { scrollTop, scrollHeight, clientHeight } = transcriptEl;
        const nearBottom = scrollHeight - scrollTop - clientHeight < 100;
        if (nearBottom) {
          requestAnimationFrame(() => {
            transcriptEl?.scrollTo({ top: transcriptEl.scrollHeight });
          });
        }
      }
    }
  });

  // Focus input when panel opens
  $effect(() => {
    if (visible && inputEl) {
      requestAnimationFrame(() => inputEl?.focus());
    }
  });

  async function handleSend() {
    const text = inputText.trim();
    if (!text) return;
    inputText = "";
    await chatStore.send(text);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function statusLabel(state: typeof chatStore.connectionState): string {
    switch (state) {
      case "connected": return "Connected";
      case "connecting": return "Connecting...";
      case "disconnected": return "Disconnected";
      case "error": return "Error";
    }
  }

  function statusColor(state: typeof chatStore.connectionState): string {
    switch (state) {
      case "connected": return "text-success";
      case "connecting": return "text-warning";
      case "disconnected": return "text-text-muted";
      case "error": return "text-error";
    }
  }

  function formatTime(ts: number): string {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
</script>

{#if visible}
  <div class="fixed inset-0 z-50">
    <!-- Backdrop -->
    <button
      type="button"
      class="absolute inset-0 bg-black/50"
      onclick={onclose}
      onkeydown={(e) => e.key === "Escape" && onclose()}
      aria-label="Close chat"
    ></button>

    <!-- Panel -->
    <div
      class="absolute right-0 top-0 bottom-0 w-full bg-bg-card border-l border-border flex flex-col"
    >
      <!-- Header -->
      <div class="flex items-center justify-between p-4 border-b border-border">
        <div class="flex items-center gap-3">
          <h2 class="text-lg font-bold text-text">Chat</h2>
          <div class="flex items-center gap-1.5">
            {#if chatStore.connectionState === "connected"}
              <Wifi class="w-3.5 h-3.5 {statusColor(chatStore.connectionState)}" />
            {:else}
              <WifiOff class="w-3.5 h-3.5 {statusColor(chatStore.connectionState)}" />
            {/if}
            <span class="text-xs {statusColor(chatStore.connectionState)}">
              {statusLabel(chatStore.connectionState)}
            </span>
          </div>
        </div>
        <div class="flex items-center gap-1">
          {#if chatStore.connectionState === "error" || chatStore.connectionState === "disconnected"}
            <button
              type="button"
              class="p-2 hover:bg-bg-input rounded-lg transition-colors text-text-muted hover:text-text"
              onclick={() => chatStore.reconnect()}
              title="Reconnect"
            >
              <RotateCcw class="w-4 h-4" />
            </button>
          {/if}
          {#if chatStore.messages.length > 0}
            <button
              type="button"
              class="p-2 hover:bg-bg-input rounded-lg transition-colors text-text-muted hover:text-text"
              onclick={() => chatStore.clear()}
              title="Clear transcript"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          {/if}
          <button
            type="button"
            class="p-2 hover:bg-bg-input rounded-lg transition-colors text-text-muted hover:text-text"
            onclick={onclose}
          >
            &times;
          </button>
        </div>
      </div>

      <!-- Error Banner -->
      {#if chatStore.error}
        <div class="flex items-center gap-2 px-4 py-2 bg-error/10 border-b border-error/30 text-error text-xs">
          <AlertCircle class="w-3.5 h-3.5 shrink-0" />
          <span class="flex-1">{chatStore.error}</span>
        </div>
      {/if}

      <!-- Transcript -->
      <div class="flex-1 overflow-y-auto p-4 space-y-4" bind:this={transcriptEl}>
        {#if chatStore.messages.length === 0}
          <div class="flex flex-col items-center justify-center h-full text-text-muted text-sm gap-2">
            <p>No messages yet.</p>
            <p class="text-xs">Type a message below to start chatting.</p>
          </div>
        {:else}
          {#each chatStore.messages as msg (msg.id)}
            <div class="flex flex-col gap-1 {msg.role === 'user' ? 'items-end' : 'items-start'}">
              <!-- Telegram badge -->
              {#if msg.source === "telegram"}
                <span class="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-sky-500/10 text-sky-500 border border-sky-500/20">
                  Telegram
                </span>
              {/if}
              <!-- Tool calls (shown above assistant bubble) -->
              {#if msg.toolCalls && msg.toolCalls.length > 0}
                <div class="max-w-[85%] space-y-1">
                  {#each msg.toolCalls as tc}
                    <div class="flex items-center gap-1.5 text-xs text-text-muted">
                      {#if !tc.result}
                        <Loader2 class="w-3 h-3 animate-spin text-primary" />
                      {:else if tc.result.success}
                        <Check class="w-3 h-3 text-success" />
                      {:else}
                        <X class="w-3 h-3 text-error" />
                      {/if}
                      <Wrench class="w-3 h-3" />
                      <span class="font-mono">{tc.name}</span>
                      {#if Object.keys(tc.arguments).length > 0}
                        <span class="text-text-muted/60 truncate max-w-[200px]">
                          ({Object.entries(tc.arguments).map(([k, v]) => `${k}=${v}`).join(", ")})
                        </span>
                      {/if}
                      {#if tc.result && !tc.result.success && tc.result.error}
                        <span class="text-error truncate max-w-[200px]">{tc.result.error}</span>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
              <!-- Message bubble -->
              {#if msg.text || msg.status === "streaming"}
                <div
                  class="max-w-[85%] rounded-xl px-3 py-2 text-sm break-words
                    {msg.role === 'user'
                      ? msg.source === 'telegram'
                        ? 'bg-sky-600 text-white rounded-br-sm whitespace-pre-wrap'
                        : 'bg-primary text-white rounded-br-sm whitespace-pre-wrap'
                      : msg.role === 'system'
                        ? 'bg-bg-input text-text-muted italic border border-border whitespace-pre-wrap'
                        : msg.source === 'telegram'
                          ? 'bg-bg-input text-text rounded-bl-sm border border-sky-500/20 chat-markdown'
                          : 'bg-bg-input text-text rounded-bl-sm chat-markdown'}
                    {msg.status === 'error' ? 'border border-error/30 bg-error/10 text-error' : ''}"
                >
                  {#if msg.role === "assistant" && msg.text}
                    {@html renderMarkdown(msg.text)}
                  {:else}
                    {msg.text || ""}
                  {/if}
                  {#if msg.status === "streaming" && !msg.text}
                    <span class="inline-block w-1.5 h-4 bg-current opacity-60 animate-pulse ml-0.5 align-text-bottom"></span>
                  {/if}
                </div>
              {/if}
              <span class="text-[10px] text-text-muted px-1">{formatTime(msg.timestamp)}</span>
            </div>
          {/each}
        {/if}
      </div>

      <!-- Input -->
      <div class="border-t border-border p-4">
        <div class="flex gap-2">
          <textarea
            class="flex-1 bg-bg-input border border-border rounded-xl px-3 py-2 text-sm text-text resize-none focus:outline-none focus:ring-2 focus:ring-primary/50 min-h-[40px] max-h-[120px]"
            placeholder={chatStore.connectionState === "connected" ? "Type a message..." : "Connecting..."}
            disabled={chatStore.connectionState !== "connected" || chatStore.isStreaming}
            bind:value={inputText}
            bind:this={inputEl}
            onkeydown={handleKeydown}
            rows={1}
          ></textarea>
          <Button
            size="sm"
            onclick={handleSend}
            disabled={chatStore.connectionState !== "connected" || chatStore.isStreaming || !inputText.trim()}
          >
            {#if chatStore.isStreaming}
              <Loader2 class="w-4 h-4 animate-spin" />
            {:else}
              <Send class="w-4 h-4" />
            {/if}
          </Button>
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  :global(.chat-markdown p) {
    margin: 0.25em 0;
  }
  :global(.chat-markdown p:first-child) {
    margin-top: 0;
  }
  :global(.chat-markdown p:last-child) {
    margin-bottom: 0;
  }
  :global(.chat-markdown ul),
  :global(.chat-markdown ol) {
    margin: 0.25em 0;
    padding-left: 1.25em;
  }
  :global(.chat-markdown li) {
    margin: 0.1em 0;
  }
  :global(.chat-markdown code) {
    font-size: 0.85em;
    background: rgba(0, 0, 0, 0.1);
    padding: 0.1em 0.3em;
    border-radius: 0.25em;
  }
  :global(.chat-markdown pre) {
    margin: 0.5em 0;
    padding: 0.5em;
    background: rgba(0, 0, 0, 0.1);
    border-radius: 0.375em;
    overflow-x: auto;
  }
  :global(.chat-markdown pre code) {
    background: none;
    padding: 0;
  }
  :global(.chat-markdown strong) {
    font-weight: 600;
  }
  :global(.chat-markdown h1),
  :global(.chat-markdown h2),
  :global(.chat-markdown h3) {
    font-weight: 600;
    margin: 0.5em 0 0.25em;
  }
  :global(.chat-markdown blockquote) {
    border-left: 2px solid currentColor;
    opacity: 0.7;
    padding-left: 0.5em;
    margin: 0.25em 0;
  }
</style>
