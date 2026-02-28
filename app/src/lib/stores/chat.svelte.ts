import { Command, type Child } from "@tauri-apps/plugin-shell";
import { resourceDir, join, dirname, homeDir } from "@tauri-apps/api/path";
import { readTextFile, writeTextFile, exists, mkdir, readDir, remove } from "@tauri-apps/plugin-fs";

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
  imageUrl?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  cost?: number | null;
  model?: string;
}

export interface AppPermissions {
  Notes: boolean;
  Mail: boolean;
  Calendar: boolean;
  Reminders: boolean;
  Safari: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

interface ConversationFile {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
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
  private _historyDir: string | null = null;
  private _permissions = $state<AppPermissions | null>(null);
  private _checkingPermissions = $state(false);
  private _conversationId = $state<string>(crypto.randomUUID());
  private _conversations = $state<ConversationSummary[]>([]);
  private _conversationTitle = $state<string>("");
  private _isTranscribing = $state(false);
  private _pendingAudioUserMsgId: string | null = null;
  private _sessionCost = $state(0);
  private _sessionTokens = $state(0);
  private _monthlyCost = $state(0);
  private _monthlyTokens = $state(0);
  private _monthlyInteractions = $state(0);

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

  get isTranscribing() {
    return this._isTranscribing;
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

  get conversationId() {
    return this._conversationId;
  }

  get conversations() {
    return this._conversations;
  }

  get conversationTitle() {
    return this._conversationTitle;
  }

  get sessionCost() {
    return this._sessionCost;
  }

  get sessionTokens() {
    return this._sessionTokens;
  }

  get monthlyCost() {
    return this._monthlyCost;
  }

  get monthlyTokens() {
    return this._monthlyTokens;
  }

  get monthlyInteractions() {
    return this._monthlyInteractions;
  }

  private async getHistoryDir(): Promise<string> {
    if (this._historyDir) return this._historyDir;
    const home = await homeDir();
    this._historyDir = await join(home, ".macbot", "chat-history");
    return this._historyDir;
  }

  async saveConversation() {
    if (this._messages.length === 0) return;

    try {
      const dir = await this.getHistoryDir();
      await mkdir(dir, { recursive: true });

      // Auto-generate title from first user message
      if (!this._conversationTitle) {
        const firstUser = this._messages.find((m) => m.role === "user");
        if (firstUser) {
          this._conversationTitle = firstUser.text.slice(0, 50).trim();
          if (firstUser.text.length > 50) this._conversationTitle += "...";
        }
      }

      const now = Date.now();
      const data: ConversationFile = {
        id: this._conversationId,
        title: this._conversationTitle,
        createdAt: this._messages[0]?.timestamp ?? now,
        updatedAt: now,
        messages: this._messages,
      };

      const filePath = await join(dir, `${this._conversationId}.json`);
      await writeTextFile(filePath, JSON.stringify(data));

      // Update summary in conversations list
      const idx = this._conversations.findIndex((c) => c.id === this._conversationId);
      const summary: ConversationSummary = {
        id: data.id,
        title: data.title,
        createdAt: data.createdAt,
        updatedAt: data.updatedAt,
      };
      if (idx !== -1) {
        this._conversations[idx] = summary;
      } else {
        this._conversations = [summary, ...this._conversations];
      }
    } catch (e) {
      console.error("Failed to save conversation:", e);
    }
  }

  async loadConversations() {
    try {
      const dir = await this.getHistoryDir();
      if (!(await exists(dir))) {
        this._conversations = [];
        return;
      }

      const entries = await readDir(dir);
      const summaries: ConversationSummary[] = [];

      for (const entry of entries) {
        if (!entry.name?.endsWith(".json")) continue;
        try {
          const filePath = await join(dir, entry.name);
          const content = await readTextFile(filePath);
          const data = JSON.parse(content) as ConversationFile;
          summaries.push({
            id: data.id,
            title: data.title,
            createdAt: data.createdAt,
            updatedAt: data.updatedAt,
          });
        } catch {
          // Skip malformed files
        }
      }

      summaries.sort((a, b) => b.updatedAt - a.updatedAt);
      this._conversations = summaries;
    } catch (e) {
      console.error("Failed to load conversations:", e);
    }
  }

  async loadConversation(id: string) {
    try {
      const dir = await this.getHistoryDir();
      const filePath = await join(dir, `${id}.json`);
      const content = await readTextFile(filePath);
      const data = JSON.parse(content) as ConversationFile;

      this._conversationId = data.id;
      this._conversationTitle = data.title;
      this._messages = data.messages;
      this._currentAssistantId = null;

      // Recompute session totals from saved message data
      this._sessionCost = 0;
      this._sessionTokens = 0;
      for (const m of data.messages) {
        if (m.totalTokens) this._sessionTokens += m.totalTokens;
        if (typeof m.cost === "number") this._sessionCost += m.cost;
      }
    } catch (e) {
      console.error("Failed to load conversation:", e);
    }
  }

  newConversation() {
    this._messages = [];
    this._conversationId = crypto.randomUUID();
    this._conversationTitle = "";
    this._currentAssistantId = null;
    this._sessionCost = 0;
    this._sessionTokens = 0;
  }

  async deleteConversation(id: string) {
    try {
      const dir = await this.getHistoryDir();
      const filePath = await join(dir, `${id}.json`);
      if (await exists(filePath)) {
        await remove(filePath);
      }
      this._conversations = this._conversations.filter((c) => c.id !== id);

      // If deleting the active conversation, start a new one
      if (this._conversationId === id) {
        this.newConversation();
      }
    } catch (e) {
      console.error("Failed to delete conversation:", e);
    }
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

  async sendAudio(audioBase64: string, format: string = "webm") {
    if (!this._child || this._connectionState !== "connected") {
      return;
    }

    // Add placeholder user message
    this._pendingAudioUserMsgId = crypto.randomUUID();
    this._isTranscribing = true;
    this._messages.push({
      id: this._pendingAudioUserMsgId,
      timestamp: Date.now(),
      role: "user",
      text: "Transcribing audio...",
      status: "streaming",
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

    // Send audio_message JSON-line to stdin
    const payload = JSON.stringify({ type: "audio_message", audio: audioBase64, format }) + "\n";
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
    this.newConversation();
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
          const imageUrl = msg.imageUrl as string | undefined;
          if (direction === "incoming") {
            // Incoming Telegram user message
            this._messages.push({
              id: crypto.randomUUID(),
              timestamp: Date.now(),
              role: "user",
              text,
              status: "complete",
              source: "telegram",
              imageUrl,
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

        case "transcription": {
          // Audio transcription result — update the placeholder user message
          this._isTranscribing = false;
          if (this._pendingAudioUserMsgId) {
            const idx = this._messages.findIndex(
              (m) => m.id === this._pendingAudioUserMsgId
            );
            if (idx !== -1) {
              this._messages[idx] = {
                ...this._messages[idx],
                text: msg.text as string,
                status: "complete",
              };
            }
            this._pendingAudioUserMsgId = null;
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
              const inputTokens = msg.input_tokens as number | undefined;
              const outputTokens = msg.output_tokens as number | undefined;
              const totalTokens = msg.total_tokens as number | undefined;
              const cost = msg.cost as number | null | undefined;
              const model = msg.model as string | undefined;
              this._messages[idx] = {
                ...this._messages[idx],
                status: "complete",
                inputTokens,
                outputTokens,
                totalTokens,
                cost: cost ?? null,
                model,
              };
              if (totalTokens) this._sessionTokens += totalTokens;
              if (typeof cost === "number") this._sessionCost += cost;
            }
            // Update monthly totals from backend
            const monthly = msg.monthly as Record<string, unknown> | undefined;
            if (monthly) {
              const mIn = (monthly.input_tokens as number) ?? 0;
              const mOut = (monthly.output_tokens as number) ?? 0;
              this._monthlyTokens = mIn + mOut;
              this._monthlyCost = (monthly.cost as number) ?? 0;
              this._monthlyInteractions = (monthly.interactions as number) ?? 0;
            }
            this._currentAssistantId = null;
            this.saveConversation();
          }
          break;

        case "error":
          // Clean up pending audio transcription state
          if (this._isTranscribing) {
            this._isTranscribing = false;
            if (this._pendingAudioUserMsgId) {
              const aidx = this._messages.findIndex(
                (m) => m.id === this._pendingAudioUserMsgId
              );
              if (aidx !== -1) {
                this._messages[aidx] = {
                  ...this._messages[aidx],
                  text: "Audio transcription failed",
                  status: "error",
                };
              }
              this._pendingAudioUserMsgId = null;
            }
          }
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
            this.saveConversation();
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
