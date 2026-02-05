<script lang="ts">
  import { Check } from "lucide-svelte";

  interface Props {
    steps: string[];
    currentStep: number;
  }

  let { steps, currentStep }: Props = $props();
</script>

<div class="flex items-center justify-center gap-2">
  {#each steps as step, i}
    <div class="flex items-center gap-2">
      <div
        class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-all duration-300
               {i < currentStep
          ? 'bg-success text-white'
          : i === currentStep
            ? 'bg-primary text-white ring-4 ring-primary/30'
            : 'bg-bg-input text-text-muted'}"
      >
        {#if i < currentStep}
          <Check class="w-4 h-4" />
        {:else}
          {i + 1}
        {/if}
      </div>

      {#if i < steps.length - 1}
        <div
          class="w-8 h-0.5 transition-colors duration-300
                 {i < currentStep ? 'bg-success' : 'bg-border'}"
        ></div>
      {/if}
    </div>
  {/each}
</div>

<p class="text-center text-sm text-text-muted mt-3">
  {steps[currentStep]}
</p>
