<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    padding?: "none" | "sm" | "md" | "lg";
    children: Snippet;
  }

  let { padding = "md", children }: Props = $props();

  const paddingClasses = {
    none: "",
    sm: "p-4",
    md: "p-6",
    lg: "p-8",
  };
</script>

<div
  class="bg-bg-card rounded-xl border border-border shadow-lg {paddingClasses[
    padding
  ]}"
>
  {@render children()}
</div>
