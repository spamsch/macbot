<script lang="ts">
  import { Button } from "$lib/components/ui";
  import { Terminal, MessageSquare, Calendar, Shield, ArrowRight } from "lucide-svelte";

  interface Props {
    onNext: () => void;
  }

  let { onNext }: Props = $props();

  const features = [
    {
      icon: Calendar,
      title: "Works With Your Apple Apps",
      description: "Uses Mail, Calendar, Reminders, Notes, and Safari directly. Make sure your accounts are set up in macOS System Settings first.",
    },
    {
      icon: Shield,
      title: "Secure by Default",
      description: "No passwords stored, no server running, no OAuth tokens. Your credentials stay in macOS Keychain. Only LLM API calls leave your Mac.",
    },
    {
      icon: MessageSquare,
      title: "Best With Telegram",
      description: "Connect Telegram to control your Mac from your phone — even while away. Leave your Mac running, send voice or text commands from anywhere.",
    },
  ];
</script>

<div class="flex flex-col items-center text-center px-10 py-8">
  <img src="/logo.svg" alt="Son of Simon" class="w-24 h-24 mb-6" />

  <h1 class="text-3xl font-bold text-text mb-3">Welcome to Son of Simon</h1>

  <p class="text-text-muted mb-8 max-w-lg">
    Your personal AI assistant for macOS. Automate Mail, Calendar, and more — securely, with no technical knowledge required.
  </p>

  <div class="grid gap-4 mb-8 w-full max-w-lg text-left">
    {#each features as feature}
      <div
        class="flex items-start gap-4 p-4 bg-bg-card rounded-xl border border-border"
      >
        <div class="p-2 bg-primary/10 rounded-lg shrink-0 mt-0.5">
          <feature.icon class="w-5 h-5 text-primary" />
        </div>
        <div>
          <h3 class="font-semibold text-text mb-1">{feature.title}</h3>
          <p class="text-sm text-text-muted leading-relaxed">{feature.description}</p>
        </div>
      </div>
    {/each}
  </div>

  <div class="space-y-3">
    <Button size="lg" onclick={onNext}>
      Start Setup
      <ArrowRight class="w-5 h-5" />
    </Button>
    <p class="text-xs text-text-muted">
      This will take about 2 minutes to set up
    </p>
  </div>
</div>
