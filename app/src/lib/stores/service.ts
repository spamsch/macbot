import { invoke } from "@tauri-apps/api/core";
import { Command } from "@tauri-apps/plugin-shell";

export interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error" | "success";
  message: string;
}

function getTimestamp(): string {
  const now = new Date();
  return now.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function parseLogLevel(
  message: string
): "info" | "warn" | "error" | "success" {
  const lower = message.toLowerCase();
  if (lower.includes("error") || lower.includes("failed")) return "error";
  if (lower.includes("warn")) return "warn";
  if (lower.includes("✓") || lower.includes("success") || lower.includes("started"))
    return "success";
  return "info";
}

class ServiceStore {
  private _running = $state(false);
  private _logs = $state<LogEntry[]>([]);
  private _error = $state<string | null>(null);
  private childProcess: Awaited<ReturnType<Command["spawn"]>> | null = null;

  get running() {
    return this._running;
  }

  get logs() {
    return this._logs;
  }

  get error() {
    return this._error;
  }

  addLog(message: string, level?: LogEntry["level"]) {
    this._logs.push({
      timestamp: getTimestamp(),
      level: level ?? parseLogLevel(message),
      message,
    });

    // Keep only last 1000 logs
    if (this._logs.length > 1000) {
      this._logs = this._logs.slice(-1000);
    }
  }

  clearLogs() {
    this._logs = [];
  }

  async start() {
    if (this._running) return;

    this._error = null;
    this.addLog("Starting Son of Simon service...", "info");

    try {
      // Try to use the bundled sidecar first, fall back to system-installed CLI
      let command: Command;
      try {
        // Sidecar binary (bundled with PyInstaller)
        command = Command.sidecar("son", ["start", "--foreground"]);
        this.addLog("Using bundled sidecar", "info");
      } catch {
        // Fallback to system-installed CLI
        command = Command.create("exec-sh", ["-c", "son start --foreground 2>&1"]);
        this.addLog("Using system-installed CLI", "info");
      }

      command.stdout.on("data", (line: string) => {
        if (line.trim()) {
          this.addLog(line.trim());
        }
      });

      command.stderr.on("data", (line: string) => {
        if (line.trim()) {
          this.addLog(line.trim(), "error");
        }
      });

      command.on("close", (data: { code: number }) => {
        this._running = false;
        if (data.code !== 0) {
          this.addLog(`Service exited with code ${data.code}`, "error");
        } else {
          this.addLog("Service stopped", "info");
        }
        this.childProcess = null;
      });

      command.on("error", (error: string) => {
        this._running = false;
        this._error = error;
        this.addLog(`Error: ${error}`, "error");
        this.childProcess = null;
      });

      this.childProcess = await command.spawn();
      this._running = true;
      await invoke("set_service_running", { running: true });
      this.addLog("Service started", "success");
    } catch (e) {
      this._error = String(e);
      this.addLog(`Failed to start service: ${e}`, "error");
    }
  }

  async stop() {
    if (!this._running || !this.childProcess) return;

    this.addLog("Stopping service...", "info");

    try {
      await this.childProcess.kill();
      this._running = false;
      await invoke("set_service_running", { running: false });
      this.childProcess = null;
    } catch (e) {
      this._error = String(e);
      this.addLog(`Failed to stop service: ${e}`, "error");
    }
  }

  async restart() {
    await this.stop();
    // Small delay before restarting
    await new Promise((resolve) => setTimeout(resolve, 500));
    await this.start();
  }
}

export const serviceStore = new ServiceStore();
