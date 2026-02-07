import { Command, type Child } from "@tauri-apps/plugin-shell";
import { resourceDir, join, dirname } from "@tauri-apps/api/path";

export interface ToolCall {
  name: string;
  arguments: Record<string, string>;
  result?: { success: boolean; error?: string | null };
}

export interface ChatMessage {
  id: string;
  timestamp: number;
  role: "user" | "assistant" | "system";
  text: string;
  status: "streaming" | "complete" | "error";
  toolCalls?: ToolCall[];
  source?: "chat" | "telegram";
}

export interface AppPermissions {
  Notes: boolean;
  Mail: boolean;
  Calendar: boolean;
  Reminders: boolean;
  Safari: boolean;
}

type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

class ChatStore {
  private _messages = $state<ChatMessage[]>([]);
  private _connectionState = $state<ConnectionState>("disconnected");
  private _error = $state<string | null>(null);
  private _child: Child | null = null;
  private _currentAssistantId: string | null = null;
  private _telegramAssistantId: string | null = null;
  private _buffer = "";
  private _sonPath: string | null = null;
  private _permissions = $state<AppPermissions | null>(null);
  private _checkingPermissions = $state(false);

  get messages() {
    return this._messages;
  }

  get connectionState() {
    return this._connectionState;
  }

  get error() {
    return this._error;
  }

  get isStreaming() {
    return this._currentAssistantId !== null;
  }

  get serviceRunning() {
    return this._child !== null && this._connectionState === "connected";
  }

  get permissions() {
    return this._permissions;
  }

  get checkingPermissions() {
    return this._checkingPermissions;
  }

  private async getSonPath(): Promise<string> {
    if (this._sonPath) return this._sonPath;
    const resourcePath = await resourceDir();
    const contentsPath = await dirname(resourcePath);
    this._sonPath = await join(contentsPath, "MacOS", "son");
    return this._sonPath;
  }

  async checkPermissions(): Promise<AppPermissions> {
    this._checkingPermissions = true;
    try {
      const sonPath = await this.getSonPath();
      const command = Command.create("exec-sh", [
        "-c",
        `"${sonPath}" doctor --json`,
      ]);
      const output = await command.execute();
      const result = JSON.parse(output.stdout);
      const automation = result.permissions?.automation ?? {};
      this._permissions = {
        Notes: automation.Notes ?? false,
        Mail: automation.Mail ?? false,
        Calendar: automation.Calendar ?? false,
        Reminders: automation.Reminders ?? false,
        Safari: automation.Safari ?? false,
      };
      return this._permissions;
    } catch (e) {
      console.error("Failed to check permissions:", e);
      throw e;
    } finally {
      this._checkingPermissions = false;
    }
  }

  async connect() {
    if (this._connectionState === "connected" || this._connectionState === "connecting") {
      return;
    }

    this._connectionState = "connecting";
    this._error = null;

    try {
      const sonPath = await this.getSonPath();

      const command = Command.create("exec-sh", [
        "-c",
        `"${sonPath}" start --foreground`,
      ]);

      command.stdout.on("data", (line: string) => {
        this._handleStdout(line);
      });

      command.stderr.on("data", (line: string) => {
        console.error("[son service stderr]", line);
      });

      command.on("close", (data) => {
        this._child = null;
        this._currentAssistantId = null;
        if (this._connectionState !== "disconnected") {
          // Unexpected exit
          this._connectionState = "error";
          this._error = `Service process exited (code ${data.code})`;
          this._addSystemMessage("Service process exited unexpectedly.");
        }
      });

      command.on("error", (error) => {
        console.error("[son service error]", error);
        this._connectionState = "error";
        this._error = String(error);
      });

      this._child = await command.spawn();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this._connectionState = "error";
      this._error = `Failed to start service: ${msg}`;
      console.error("Failed to start service:", e);
    }
  }

  async send(text: string) {
    if (!this._child || this._connectionState !== "connected") {
      return;
    }

    // Add user message to transcript
    this._messages.push({
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      role: "user",
      text,
      status: "complete",
    });

    // Create placeholder for assistant response
    this._currentAssistantId = crypto.randomUUID();
    this._messages.push({
      id: this._currentAssistantId,
      timestamp: Date.now(),
      role: "assistant",
      text: "",
      status: "streaming",
    });

    // Send JSON-line to stdin
    const payload = JSON.stringify({ type: "message", text }) + "\n";
    await this._child.write(payload);
  }

  async disconnect() {
    this._connectionState = "disconnected";
    if (this._child) {
      await this._child.kill();
      this._child = null;
    }
    this._currentAssistantId = null;
  }

  async reconnect() {
    await this.disconnect();
    await this.connect();
  }

  clear() {
    this._messages = [];
    this._currentAssistantId = null;
  }

  private _handleStdout(raw: string) {
    // stdout may deliver partial lines; buffer and split on newlines
    this._buffer += raw;
    const lines = this._buffer.split("\n");
    // Keep the last (possibly incomplete) segment in the buffer
    this._buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(trimmed);
      } catch {
        console.warn("[son service] non-JSON stdout:", trimmed);
        continue;
      }

      switch (msg.type) {
        case "ready":
          this._connectionState = "connected";
          break;

        case "telegram_message": {
          const direction = msg.direction as string;
          const text = msg.text as string;
          if (direction === "incoming") {
            // Incoming Telegram user message
            this._messages.push({
              id: crypto.randomUUID(),
              timestamp: Date.now(),
              role: "user",
              text,
              status: "complete",
              source: "telegram",
            });
            // Create placeholder for the assistant response (tool calls will attach here)
            this._telegramAssistantId = crypto.randomUUID();
            this._messages.push({
              id: this._telegramAssistantId,
              timestamp: Date.now(),
              role: "assistant",
              text: "",
              status: "streaming",
              source: "telegram",
            });
          } else if (direction === "outgoing") {
            // Outgoing Telegram assistant response
            if (this._telegramAssistantId) {
              const idx = this._messages.findIndex(
                (m) => m.id === this._telegramAssistantId
              );
              if (idx !== -1) {
                this._messages[idx] = {
                  ...this._messages[idx],
                  text,
                  status: "complete",
                };
              }
              this._telegramAssistantId = null;
            } else {
              // No placeholder — create a standalone outgoing message
              this._messages.push({
                id: crypto.randomUUID(),
                timestamp: Date.now(),
                role: "assistant",
                text,
                status: "complete",
                source: "telegram",
              });
            }
          }
          break;
        }

        case "tool_call": {
          const targetId = this._currentAssistantId ?? this._telegramAssistantId;
          if (targetId) {
            const idx = this._messages.findIndex(
              (m) => m.id === targetId
            );
            if (idx !== -1) {
              const existing = this._messages[idx];
              const toolCalls = [...(existing.toolCalls ?? [])];
              toolCalls.push({
                name: msg.name as string,
                arguments: (msg.arguments ?? {}) as Record<string, string>,
              });
              this._messages[idx] = { ...existing, toolCalls };
            }
          }
          break;
        }

        case "tool_result": {
          const targetId = this._currentAssistantId ?? this._telegramAssistantId;
          if (targetId) {
            const idx = this._messages.findIndex(
              (m) => m.id === targetId
            );
            if (idx !== -1) {
              const existing = this._messages[idx];
              const toolCalls = [...(existing.toolCalls ?? [])];
              // Update the last tool call with its result
              const last = toolCalls.length - 1;
              if (last >= 0) {
                toolCalls[last] = {
                  ...toolCalls[last],
                  result: {
                    success: msg.success as boolean,
                    error: msg.error as string | undefined,
                  },
                };
              }
              this._messages[idx] = { ...existing, toolCalls };
            }
          }
          break;
        }

        case "chunk":
          if (this._currentAssistantId && msg.text) {
            const idx = this._messages.findIndex(
              (m) => m.id === this._currentAssistantId
            );
            if (idx !== -1) {
              this._messages[idx] = {
                ...this._messages[idx],
                text: this._messages[idx].text + (msg.text as string),
              };
            }
          }
          break;

        case "done":
          if (this._currentAssistantId) {
            const idx = this._messages.findIndex(
              (m) => m.id === this._currentAssistantId
            );
            if (idx !== -1) {
              this._messages[idx] = {
                ...this._messages[idx],
                status: "complete",
              };
            }
            this._currentAssistantId = null;
          }
          break;

        case "error":
          if (this._currentAssistantId) {
            const idx = this._messages.findIndex(
              (m) => m.id === this._currentAssistantId
            );
            if (idx !== -1) {
              this._messages[idx] = {
                ...this._messages[idx],
                text: (msg.text as string) ?? "Unknown error",
                status: "error",
              };
            }
            this._currentAssistantId = null;
          } else {
            this._addSystemMessage(`Error: ${msg.text as string}`);
          }
          break;
      }
    }
  }

  private _addSystemMessage(text: string) {
    this._messages.push({
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      role: "system",
      text,
      status: "complete",
    });
  }
}

export const chatStore = new ChatStore();
