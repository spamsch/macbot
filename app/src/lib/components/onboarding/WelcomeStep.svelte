<script lang="ts">
  import { Button } from "$lib/components/ui";
  import { Sparkles, Terminal, MessageSquare, Calendar } from "lucide-svelte";

  interface Props {
    onNext: () => void;
  }

  let { onNext }: Props = $props();

  const features = [
    {
      icon: Terminal,
      title: "Natural Language Control",
      description: "Tell your Mac what to do in plain English",
    },
    {
      icon: Calendar,
      title: "App Automation",
      description: "Control Mail, Calendar, Reminders, Notes & more",
    },
    {
      icon: MessageSquare,
      title: "Telegram Integration",
      description: "Send commands from anywhere via Telegram",
    },
  ];
</script>

<div class="flex flex-col items-center text-center px-8 py-6">
  <div
    class="w-20 h-20 bg-primary/20 rounded-2xl flex items-center justify-center mb-6"
  >
    <Sparkles class="w-10 h-10 text-primary" />
  </div>

  <h1 class="text-3xl font-bold text-text mb-3">Welcome to Son of Simon</h1>

  <p class="text-text-muted mb-8 max-w-md">
    Your AI-powered macOS automation assistant. Control your Mac with natural
    language commands.
  </p>

  <div class="grid gap-4 mb-8 w-full max-w-md">
    {#each features as feature}
      <div
        class="flex items-start gap-4 p-4 bg-bg-card/50 rounded-lg text-left"
      >
        <div class="p-2 bg-primary/10 rounded-lg shrink-0">
          <feature.icon class="w-5 h-5 text-primary" />
        </div>
        <div>
          <h3 class="font-medium text-text">{feature.title}</h3>
          <p class="text-sm text-text-muted">{feature.description}</p>
        </div>
      </div>
    {/each}
  </div>

  <Button size="lg" onclick={onNext}>Get Started</Button>
</div>
