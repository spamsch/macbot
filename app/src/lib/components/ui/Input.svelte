<script lang="ts">
  import { Eye, EyeOff } from "lucide-svelte";

  interface Props {
    type?: "text" | "password" | "email" | "url";
    placeholder?: string;
    value?: string;
    label?: string;
    error?: string;
    disabled?: boolean;
    id?: string;
  }

  let {
    type = "text",
    placeholder = "",
    value = $bindable(""),
    label,
    error,
    disabled = false,
    id,
  }: Props = $props();

  let showPassword = $state(false);
  let inputType = $derived(
    type === "password" ? (showPassword ? "text" : "password") : type
  );

  function togglePassword() {
    showPassword = !showPassword;
  }
</script>

<div class="flex flex-col gap-1.5">
  {#if label}
    <label for={id} class="text-sm font-medium text-text-muted">
      {label}
    </label>
  {/if}

  <div class="relative">
    <input
      {id}
      type={inputType}
      {placeholder}
      {disabled}
      bind:value
      class="w-full px-4 py-2.5 bg-bg-input text-text placeholder-text-muted rounded-lg border transition-colors
             {error
        ? 'border-error focus:border-error focus:ring-error'
        : 'border-border focus:border-primary focus:ring-primary'}
             focus:outline-none focus:ring-2 focus:ring-opacity-50
             disabled:opacity-50 disabled:cursor-not-allowed"
    />

    {#if type === "password"}
      <button
        type="button"
        onclick={togglePassword}
        class="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text transition-colors"
        tabindex={-1}
      >
        {#if showPassword}
          <EyeOff class="w-5 h-5" />
        {:else}
          <Eye class="w-5 h-5" />
        {/if}
      </button>
    {/if}
  </div>

  {#if error}
    <p class="text-sm text-error">{error}</p>
  {/if}
</div>
