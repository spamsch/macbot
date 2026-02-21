import { homeDir, join } from "@tauri-apps/api/path";
import { readTextFile, writeTextFile, exists } from "@tauri-apps/plugin-fs";
import { Command } from "@tauri-apps/plugin-shell";

export interface CronJobState {
  next_run_at: string | null;
  last_run_at: string | null;
  last_result: string | null;
  run_count: number;
  error_count: number;
  last_error: string | null;
}

export interface CronSchedule {
  kind: "at" | "every" | "cron";
  at_ms?: number;
  every_ms?: number;
  cron_expr?: string;
  timezone: string;
}

export interface CronPayload {
  kind: string;
  message: string;
}

export interface CronJob {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  schedule: CronSchedule;
  payload: CronPayload;
  state: CronJobState;
  created_at: string;
  updated_at: string;
}

interface CronStorage {
  version: number;
  jobs: CronJob[];
}

class CronStore {
  private _jobs = $state<CronJob[]>([]);
  private _loading = $state(false);
  private _saving = $state(false);
  private _error = $state<string | null>(null);
  private _filePath: string | null = null;

  get jobs() {
    return this._jobs;
  }

  get loading() {
    return this._loading;
  }

  get saving() {
    return this._saving;
  }

  get error() {
    return this._error;
  }

  private async getFilePath(): Promise<string> {
    if (this._filePath) return this._filePath;
    const home = await homeDir();
    this._filePath = await join(home, ".macbot", "cron.json");
    return this._filePath;
  }

  async load() {
    this._loading = true;
    this._error = null;

    try {
      const filePath = await this.getFilePath();

      if (await exists(filePath)) {
        const content = await readTextFile(filePath);
        const parsed: CronStorage = JSON.parse(content);
        this._jobs = parsed.jobs ?? [];
      } else {
        this._jobs = [];
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this._error = `Failed to load scheduled tasks: ${msg}`;
      console.error("Failed to load cron jobs:", e);
      this._jobs = [];
    } finally {
      this._loading = false;
    }
  }

  async toggle(jobId: string) {
    const job = this._jobs.find((j) => j.id === jobId);
    if (!job) return;

    job.enabled = !job.enabled;
    job.updated_at = new Date().toISOString();
    this._jobs = [...this._jobs];
    await this.save();
  }

  async remove(jobId: string) {
    this._jobs = this._jobs.filter((j) => j.id !== jobId);
    await this.save();
  }

  private async save() {
    this._saving = true;
    this._error = null;

    try {
      const filePath = await this.getFilePath();
      const data: CronStorage = { version: 1, jobs: this._jobs };
      await writeTextFile(filePath, JSON.stringify(data, null, 2) + "\n");
      await this.signalReload();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this._error = `Failed to save: ${msg}`;
      console.error("Failed to save cron jobs:", e);
    } finally {
      this._saving = false;
    }
  }

  private async signalReload() {
    // Send SIGHUP to the service to reload cron config
    try {
      const home = await homeDir();
      const pidPath = await join(home, ".macbot", "service.pid");
      if (await exists(pidPath)) {
        const pid = (await readTextFile(pidPath)).trim();
        if (pid) {
          const cmd = Command.create("exec-sh", ["-c", `kill -HUP ${pid}`]);
          await cmd.execute();
        }
      }
    } catch {
      // Best-effort: service may not be running
    }
  }

  scheduleDescription(job: CronJob): string {
    const s = job.schedule;
    if (s.kind === "cron" && s.cron_expr) {
      return s.cron_expr;
    }
    if (s.kind === "every" && s.every_ms) {
      const mins = s.every_ms / 60_000;
      return mins >= 1 ? `every ${mins} min` : `every ${s.every_ms / 1000}s`;
    }
    if (s.kind === "at" && s.at_ms) {
      return `once at ${new Date(s.at_ms).toLocaleString()}`;
    }
    return "unknown";
  }

  formatNextRun(job: CronJob): string {
    if (!job.state.next_run_at) return "—";
    try {
      return new Date(job.state.next_run_at).toLocaleString();
    } catch {
      return job.state.next_run_at;
    }
  }
}

export const cronStore = new CronStore();
