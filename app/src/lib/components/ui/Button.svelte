<script lang="ts">
  import type { Snippet } from "svelte";
  import { Loader2 } from "lucide-svelte";

  interface Props {
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "sm" | "md" | "lg";
    disabled?: boolean;
    loading?: boolean;
    type?: "button" | "submit" | "reset";
    onclick?: (e: MouseEvent) => void;
    children: Snippet;
  }

  let {
    variant = "primary",
    size = "md",
    disabled = false,
    loading = false,
    type = "button",
    onclick,
    children,
  }: Props = $props();

  const baseClasses =
    "inline-flex items-center justify-center font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-bg disabled:opacity-50 disabled:cursor-not-allowed";

  const variantClasses = {
    primary: "bg-primary text-white hover:bg-primary-hover focus:ring-primary",
    secondary:
      "bg-bg-card text-text border border-border hover:bg-bg-input focus:ring-border",
    ghost: "text-text-muted hover:text-text hover:bg-bg-card focus:ring-border",
    danger: "bg-error text-white hover:bg-red-600 focus:ring-error",
  };

  const sizeClasses = {
    sm: "px-3 py-1.5 text-sm gap-1.5",
    md: "px-4 py-2 text-base gap-2",
    lg: "px-6 py-3 text-lg gap-2.5",
  };
</script>

<button
  {type}
  disabled={disabled || loading}
  class="{baseClasses} {variantClasses[variant]} {sizeClasses[size]}"
  onclick={onclick}
>
  {#if loading}
    <Loader2 class="w-4 h-4 animate-spin" />
  {/if}
  {@render children()}
</button>
