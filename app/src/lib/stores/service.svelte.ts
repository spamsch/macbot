import { invoke } from "@tauri-apps/api/core";
import { Command } from "@tauri-apps/plugin-shell";
import { resourceDir, join, dirname } from "@tauri-apps/api/path";

class ServiceStore {
  private _running = $state(false);
  private _sonPath = $state<string | null>(null);

  get running() {
    return this._running;
  }

  async start(verbose = false) {
    if (this._running) return;

    try {
      // Get the path to the bundled sidecar (in Contents/MacOS)
      const resourcePath = await resourceDir();
      const contentsPath = await dirname(resourcePath);
      const sonPath = await join(contentsPath, "MacOS", "son");
      this._sonPath = sonPath;

      // Build the command - don't use --foreground to get rich interactive console
      const args = verbose ? "start --verbose" : "start";

      // AppleScript to open Terminal, resize it, and run the command
      // Show startup message before running the command
      const script = `
        tell application "Terminal"
          set newWindow to do script "clear && echo 'Starting Son of Simon... takes a minute' && \\"${sonPath}\\" ${args}"
          activate
          set bounds of front window to {100, 100, 1100, 700}
        end tell
      `;

      const command = Command.create("exec-sh", [
        "-c",
        `osascript -e '${script.replace(/'/g, "'\"'\"'")}'`,
      ]);

      await command.execute();
      this._running = true;
      await invoke("set_service_running", { running: true });
    } catch (e) {
      console.error("Failed to start:", e);
      throw e;
    }
  }

  async stop() {
    if (!this._running) return;

    try {
      // Kill the son process by name
      const command = Command.create("exec-sh", ["-c", "pkill -f 'son start'"]);
      await command.execute();

      this._running = false;
      await invoke("set_service_running", { running: false });
    } catch (e) {
      console.error("Failed to stop:", e);
      // Even if pkill fails, mark as not running
      this._running = false;
      await invoke("set_service_running", { running: false });
    }
  }

  async showTerminal() {
    try {
      const script = `
        tell application "Terminal"
          activate
        end tell
      `;
      const command = Command.create("exec-sh", [
        "-c",
        `osascript -e '${script.replace(/'/g, "'\"'\"'")}'`,
      ]);
      await command.execute();
    } catch (e) {
      console.error("Failed to show terminal:", e);
    }
  }
}

export const serviceStore = new ServiceStore();
