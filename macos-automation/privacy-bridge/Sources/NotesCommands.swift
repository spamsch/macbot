// ==============================================================================
// NotesCommands.swift - Notes.app content operations, owned by the bridge.
// ==============================================================================
// These commands send Apple Events from this process (NSAppleScript), so the
// Automation grant they need is the one recorded against this app's bundle ID.
// Nothing here shells out to `osascript`, which would be a separate TCC caller.
//
// Safety properties held on purpose:
//   * create / move / delete are separate explicit subcommands. No read command
//     ever mutates Notes.
//   * `delete` and `folder-delete` require --confirmed.
//   * `folder-delete` refuses a folder that still contains notes.
//   * `export` refuses to overwrite an existing file unless --force.
//   * Note bodies appear only in `read`, `export`, and `search --preview`,
//     which exist to return them. Errors never echo note content.
// ==============================================================================

import Foundation

enum NotesCommands {
    /// Subcommands routed here. Anything else under `notes` (status, request,
    /// probe) stays with AutomationCommands.
    static let subcommands: Set<String> = [
        "folders", "list", "search", "read", "create", "move", "delete",
        "folder-create", "folder-rename", "folder-delete", "export", "help",
    ]

    static let app = "notes"

    static func run(_ args: Args) -> Never {
        let sub = args.positional(1) ?? "help"
        switch sub {
        case "folders": folders(args)
        case "list": list(args)
        case "search": search(args)
        case "read": read(args)
        case "create": create(args)
        case "move": move(args)
        case "delete": deleteNote(args)
        case "folder-create": folderCreate(args)
        case "folder-rename": folderRename(args)
        case "folder-delete": folderDelete(args)
        case "export": export(args)
        case "help": help()
        default:
            Out.failure("notes", BridgeError(
                code: "unknown_subcommand",
                message: "Unknown notes subcommand \"\(sub)\"",
                hint: "Available: " + subcommands.sorted().joined(separator: ", ") +
                      ", status, request, probe"
            ))
        }
    }

    private static func help() -> Never {
        Out.success("notes help", [
            "usage": "letta-privacy-bridge notes <subcommand> [options]",
            "subcommands": [
                ["name": "folders", "summary": "List folders with note counts and smart-folder flags."],
                ["name": "list", "summary": "List note metadata (no bodies).",
                 "options": ["--folder <name>", "--recent <days>", "--limit <n>"]],
                ["name": "search", "summary": "Search titles, and bodies unless --title-only.",
                 "options": ["--query <text>", "--folder <name>", "--title-only",
                             "--preview", "--limit <n>"]],
                ["name": "read", "summary": "Read one note.",
                 "options": ["--title <text>", "--folder <name>", "--format text|html"]],
                ["name": "create", "summary": "Create a note.",
                 "options": ["--title <text>", "--body <text>", "--body-file <path>",
                             "--folder <name>", "--html"]],
                ["name": "move", "summary": "Move a note to another folder.",
                 "options": ["--title <text>", "--from <name>", "--to <name>"]],
                ["name": "delete", "summary": "Delete a note. Requires --confirmed.",
                 "options": ["--title <text>", "--folder <name>", "--confirmed"]],
                ["name": "folder-create", "summary": "Create a folder.",
                 "options": ["--name <text>", "--parent <name>"]],
                ["name": "folder-rename", "summary": "Rename a folder.",
                 "options": ["--name <text>", "--new-name <text>"]],
                ["name": "folder-delete", "summary": "Delete an empty folder. Requires --confirmed.",
                 "options": ["--name <text>", "--confirmed"]],
                ["name": "export", "summary": "Write a note or a whole folder to disk.",
                 "options": ["--title <text> --output <path>",
                             "--folder <name> --output-dir <dir>",
                             "--format text|html", "--force"]],
            ],
            "notes": [
                "Titles match exactly first (case-insensitive); otherwise the first " +
                "substring match wins.",
                "Timestamps are local time, formatted YYYY-MM-DDTHH:MM:SS.",
                "Attachments are not exposed. Smart folders are reported but cannot receive notes.",
                "Every subcommand accepts --dry-run: it prints the AppleScript that would " +
                "be sent and touches neither Notes nor the disk.",
            ],
        ])
    }

    // MARK: - permission gate

    /// Refuses early when Apple Events are denied or never asked, so a command
    /// never fails halfway with a cryptic -1743.
    private static func requireAutomation(_ args: Args, _ command: String) {
        guard !args.bool("dry-run") else { return }
        guard let target = AutomationTarget.named(app) else { return }
        let permission = AutomationPermissions.check(target, askUser: false)
        switch permission.status {
        case "denied":
            Out.failure(command, BridgeError(
                code: "automation_denied",
                message: "Apple Events to Notes are denied for Letta Privacy Bridge",
                hint: permission.detail,
                recovery: [
                    "letta-privacy-bridge automation request --app notes",
                    "letta-privacy-bridge open-settings automation",
                ]
            ))
        case "not_determined":
            Out.failure(command, BridgeError(
                code: "automation_not_determined",
                message: "macOS has not been asked yet whether this app may automate Notes",
                hint: "Run `notes request` first; it shows a dialog attributed to the bridge.",
                recovery: ["letta-privacy-bridge notes request"]
            ))
        default:
            // "authorized", or -600 (Notes closed) — the Apple Event launches it.
            break
        }
    }

    // MARK: - shared AppleScript prelude

    /// Handlers every script may call. They encode the two hard-won Notes.app
    /// rules: bulk-fetch a single property per folder (`repeat with n in notes
    /// of f` raises -1728 on iCloud folders), then re-resolve each note globally
    /// with `note id X`.
    private static let prelude = """
    on pad2(n)
        set s to ((n as integer) as text)
        if (count of s) < 2 then set s to "0" & s
        return s
    end pad2

    on isoDate(d)
        if d is missing value then return ""
        return ((year of d) as integer as text) & "-" & my pad2((month of d) as integer) ¬
            & "-" & my pad2(day of d) & "T" & my pad2(hours of d) & ":" ¬
            & my pad2(minutes of d) & ":" & my pad2(seconds of d)
    end isoDate

    on folderRef(fname)
        tell application "Notes"
            repeat with f in folders
                considering case
                    if name of f is fname then return contents of f
                end considering
            end repeat
            repeat with f in folders
                if name of f is fname then return contents of f
            end repeat
        end tell
        return missing value
    end folderRef

    on isSmartFolder(f)
        tell application "Notes"
            if (count of notes of f) is 0 then return false
            try
                set fid to id of f
                set gn to note id (id of (first note of f))
                if (id of (container of gn)) is not fid then return true
            end try
        end tell
        return false
    end isSmartFolder

    on findNote(t, fname)
        tell application "Notes"
            set folderList to {}
            if fname is "" then
                set folderList to folders
            else
                set fr to my folderRef(fname)
                if fr is missing value then return {"nofolder"}
                set folderList to {fr}
            end if
            set fallback to {}
            repeat with f in folderList
                if name of f is not "Recently Deleted" then
                    set fn to name of f
                    set nCount to count of notes of f
                    if nCount > 0 then
                        try
                            set nIds to id of notes of f
                            set nNames to name of notes of f
                            repeat with i from 1 to nCount
                                set nm to item i of nNames
                                if nm is t then return {"ok", item i of nIds, nm, fn}
                                if (fallback is {}) and (nm contains t) then
                                    set fallback to {"ok", item i of nIds, nm, fn}
                                end if
                            end repeat
                        end try
                    end if
                end if
            end repeat
            if fallback is not {} then return fallback
        end tell
        return {"nonote"}
    end findNote
    """

    private static func script(_ body: String) -> String {
        prelude + "\n\n" + body
    }

    /// Sends the event, or — with `--dry-run` — prints the exact AppleScript that
    /// would have been sent and stops. Dry runs touch neither Notes nor the disk,
    /// which makes the generated source checkable (`osacompile`) without reading
    /// a single note.
    private static func execute(_ source: String, _ args: Args, command: String) -> NSAppleEventDescriptor {
        if args.bool("dry-run") {
            Out.success(command, [
                "dry_run": true,
                "app": app,
                "script": source,
                "note": "Nothing was sent to Notes and nothing was written.",
            ])
        }
        return AppleScriptRunner.runOrFail(source, command: command, app: app)
    }

    /// Emits the AppleScript expression that selects which folders to walk.
    private static func folderSelection(_ folder: String?) -> String {
        guard let folder else {
            return "set folderList to folders"
        }
        return """
        set fr to my folderRef(\(AS.literal(folder)))
        if fr is missing value then return {"nofolder"}
        set folderList to {fr}
        """
    }

    private static func failNoFolder(_ command: String, _ name: String) -> Never {
        Out.failure(command, BridgeError(
            code: "folder_not_found",
            message: "No Notes folder named \"\(name)\"",
            hint: "Run `letta-privacy-bridge notes folders` for the exact names."
        ))
    }

    private static func failNoNote(_ command: String, title: String, folder: String?) -> Never {
        Out.failure(command, BridgeError(
            code: "note_not_found",
            message: "No note matching \"\(title)\"" + (folder.map { " in folder \"\($0)\"" } ?? ""),
            hint: "Run `letta-privacy-bridge notes list` or `notes search --title-only` first."
        ))
    }

    // MARK: - folders

    private static func folders(_ args: Args) -> Never {
        let command = "notes folders"
        requireAutomation(args, command)

        let source = script("""
        tell application "Notes"
            set out to {}
            repeat with f in folders
                set fid to id of f
                set fname to name of f
                set nCount to count of notes of f
                set smart to "false"
                if my isSmartFolder(f) then set smart to "true"
                set end of out to {fid, fname, (nCount as text), smart}
            end repeat
            return out
        end tell
        """)

        let result = execute(source, args, command: command)
        let payload = result.items.map { entry -> [String: Any] in
            [
                "id": entry.text(1),
                "name": entry.text(2),
                "note_count": entry.int(3),
                "smart_folder": entry.text(4) == "true",
            ]
        }
        Out.success(command, ["count": payload.count, "folders": payload])
    }

    // MARK: - list

    private static func list(_ args: Args) -> Never {
        let command = "notes list"
        requireAutomation(args, command)

        let folder = args.string("folder")
        let limit = max(1, args.int("limit") ?? 50)
        let recent = args.int("recent")

        let cutoff = recent.map {
            "set cutoff to (current date) - (\(max(0, $0)) * 86400)"
        } ?? "set cutoff to missing value"

        let source = script("""
        tell application "Notes"
            \(cutoff)
            set out to {}
            set total to 0
            \(folderSelection(folder))
            repeat with f in folderList
                if name of f is not "Recently Deleted" then
                    set fname to name of f
                    set nCount to count of notes of f
                    if nCount > 0 then
                        try
                            set nIds to id of notes of f
                            set nNames to name of notes of f
                            set nMods to modification date of notes of f
                            repeat with i from 1 to nCount
                                set md to item i of nMods
                                set keep to true
                                if cutoff is not missing value then
                                    if md < cutoff then set keep to false
                                end if
                                if keep then
                                    set total to total + 1
                                    if total <= \(limit) then
                                        set end of out to {item i of nIds, item i of nNames, ¬
                                            fname, my isoDate(md)}
                                    end if
                                end if
                            end repeat
                        end try
                    end if
                end if
            end repeat
            return {(total as text), out}
        end tell
        """)

        let result = execute(source, args, command: command)
        if result.text(1) == "nofolder", let folder { failNoFolder(command, folder) }

        let total = result.int(1)
        let notes = (result.atIndex(2)?.items ?? []).map { entry -> [String: Any] in
            [
                "id": entry.text(1),
                "title": entry.text(2),
                "folder": entry.text(3),
                "modified": entry.text(4),
            ]
        }
        Out.success(command, [
            "count": notes.count,
            "total_matched": total,
            "limit": limit,
            "truncated": total > notes.count,
            "notes": notes,
        ])
    }

    // MARK: - search

    private static func search(_ args: Args) -> Never {
        let command = "notes search"
        requireAutomation(args, command)

        let query = args.require("query", command: command)
        let folder = args.string("folder")
        let limit = max(1, args.int("limit") ?? 20)
        let titleOnly = args.bool("title-only")
        let preview = args.bool("preview")

        // Content matching costs one Apple Event per note, so --title-only is the
        // cheap path and stays a deliberate choice by the caller.
        let contentMatch = titleOnly ? "" : """
                                    if not matched then
                                        try
                                            if plaintext of (note id (item i of nIds)) contains q then
                                                set matched to true
                                            end if
                                        end try
                                    end if
        """
        let previewBlock = preview ? """
                                            try
                                                set t to plaintext of (note id (item i of nIds))
                                                if (count of t) > 200 then
                                                    set pv to (text 1 thru 200 of t) & "..."
                                                else
                                                    set pv to t
                                                end if
                                            end try
        """ : ""

        let source = script("""
        tell application "Notes"
            set q to \(AS.literal(query))
            set out to {}
            set total to 0
            \(folderSelection(folder))
            repeat with f in folderList
                if name of f is not "Recently Deleted" then
                    set fname to name of f
                    set nCount to count of notes of f
                    if nCount > 0 then
                        try
                            set nIds to id of notes of f
                            set nNames to name of notes of f
                            set nMods to modification date of notes of f
                            repeat with i from 1 to nCount
                                set nm to item i of nNames
                                set matched to (nm contains q)
        \(contentMatch)
                                if matched then
                                    set total to total + 1
                                    if total <= \(limit) then
                                        set pv to ""
        \(previewBlock)
                                        set end of out to {item i of nIds, nm, fname, ¬
                                            my isoDate(item i of nMods), pv}
                                    end if
                                end if
                            end repeat
                        end try
                    end if
                end if
            end repeat
            return {(total as text), out}
        end tell
        """)

        let result = execute(source, args, command: command)
        if result.text(1) == "nofolder", let folder { failNoFolder(command, folder) }

        let total = result.int(1)
        let matches = (result.atIndex(2)?.items ?? []).map { entry -> [String: Any] in
            var item: [String: Any] = [
                "id": entry.text(1),
                "title": entry.text(2),
                "folder": entry.text(3),
                "modified": entry.text(4),
            ]
            if preview { item["preview"] = entry.text(5) }
            return item
        }
        Out.success(command, [
            "query": query,
            "scope": titleOnly ? "titles" : "titles_and_bodies",
            "count": matches.count,
            "total_matched": total,
            "limit": limit,
            "truncated": total > matches.count,
            "matches": matches,
        ])
    }

    // MARK: - read

    private static func read(_ args: Args) -> Never {
        let command = "notes read"
        requireAutomation(args, command)

        let title = args.require("title", command: command)
        let folder = args.string("folder")
        let html = format(args, command: command) == "html"

        let source = script("""
        set found to my findNote(\(AS.literal(title)), \(AS.literal(folder ?? "")))
        if item 1 of found is not "ok" then return found
        tell application "Notes"
            set n to note id (item 2 of found)
            set c to \(html ? "body of n" : "plaintext of n")
            return {"ok", item 2 of found, item 3 of found, item 4 of found, ¬
                my isoDate(modification date of n), my isoDate(creation date of n), c}
        end tell
        """)

        let result = execute(source, args, command: command)
        switch result.text(1) {
        case "nofolder": failNoFolder(command, folder ?? "")
        case "nonote": failNoNote(command, title: title, folder: folder)
        default: break
        }

        Out.success(command, ["note": [
            "id": result.text(2),
            "title": result.text(3),
            "folder": result.text(4),
            "modified": result.text(5),
            "created": result.text(6),
            "format": html ? "html" : "text",
            "content": result.text(7),
        ]])
    }

    // MARK: - create

    private static func create(_ args: Args) -> Never {
        let command = "notes create"
        requireAutomation(args, command)

        let title = args.require("title", command: command)
        var body = args.string("body")
        if let path = args.string("body-file") {
            guard let contents = try? String(contentsOfFile: path, encoding: .utf8) else {
                Out.failure(command, BridgeError(
                    code: "body_file_unreadable",
                    message: "Could not read --body-file at \(path)",
                    hint: "Pass a readable UTF-8 text file, or use --body."
                ))
            }
            body = contents
        }
        let html = args.bool("html")
        // Notes stores rich text as HTML. Plain input is wrapped so newlines survive.
        let markup = html ? (body ?? title) : "<div>" + escapeHTML(body ?? title)
            .replacingOccurrences(of: "\n", with: "<br>") + "</div>"

        let folder = args.string("folder")
        let placement = folder.map {
            """
            set fr to my folderRef(\(AS.literal($0)))
            if fr is missing value then return {"nofolder"}
            set n to make new note at fr with properties {name:t, body:b}
            """
        } ?? "set n to make new note with properties {name:t, body:b}"

        let source = script("""
        tell application "Notes"
            set t to \(AS.literal(title))
            set b to \(AS.literal(markup))
            \(placement)
            set gn to note id (id of n)
            return {"ok", id of gn, name of gn, name of (container of gn)}
        end tell
        """)

        let result = execute(source, args, command: command)
        if result.text(1) == "nofolder" { failNoFolder(command, folder ?? "") }

        Out.success(command, ["note": [
            "id": result.text(2),
            "title": result.text(3),
            "folder": result.text(4),
            "format": html ? "html" : "text",
        ]])
    }

    // MARK: - move

    private static func move(_ args: Args) -> Never {
        let command = "notes move"
        requireAutomation(args, command)

        let title = args.require("title", command: command)
        let destination = args.require("to", command: command)
        let from = args.string("from")

        let source = script("""
        set dest to my folderRef(\(AS.literal(destination)))
        if dest is missing value then return {"nodest"}
        if my isSmartFolder(dest) then return {"smart"}
        set found to my findNote(\(AS.literal(title)), \(AS.literal(from ?? "")))
        if item 1 of found is not "ok" then return found
        tell application "Notes"
            set n to note id (item 2 of found)
            move n to dest
            set gn to note id (item 2 of found)
            return {"ok", item 2 of found, item 3 of found, item 4 of found, name of (container of gn)}
        end tell
        """)

        let result = execute(source, args, command: command)
        switch result.text(1) {
        case "nodest": failNoFolder(command, destination)
        case "nofolder": failNoFolder(command, from ?? "")
        case "nonote": failNoNote(command, title: title, folder: from)
        case "smart":
            Out.failure(command, BridgeError(
                code: "smart_folder_destination",
                message: "\"\(destination)\" is a Smart Folder",
                hint: "Notes cannot assign notes to Smart Folders. Move to a regular folder, " +
                      "or adjust the Smart Folder's query instead."
            ))
        default: break
        }

        Out.success(command, ["note": [
            "id": result.text(2),
            "title": result.text(3),
            "from_folder": result.text(4),
            "folder": result.text(5),
        ]])
    }

    // MARK: - delete

    private static func deleteNote(_ args: Args) -> Never {
        let command = "notes delete"
        requireAutomation(args, command)
        let title = args.require("title", command: command)
        let folder = args.string("folder")
        requireConfirmation(args, command: command, subject: "note \"\(title)\"")

        let source = script("""
        set found to my findNote(\(AS.literal(title)), \(AS.literal(folder ?? "")))
        if item 1 of found is not "ok" then return found
        tell application "Notes"
            delete (note id (item 2 of found))
        end tell
        return found
        """)

        let result = execute(source, args, command: command)
        switch result.text(1) {
        case "nofolder": failNoFolder(command, folder ?? "")
        case "nonote": failNoNote(command, title: title, folder: folder)
        default: break
        }

        Out.success(command, [
            "deleted": true,
            "note": [
                "id": result.text(2),
                "title": result.text(3),
                "folder": result.text(4),
            ],
            "recovery": "Notes moves deletions to \"Recently Deleted\" for 30 days.",
        ])
    }

    // MARK: - folders: create / rename / delete

    private static func folderCreate(_ args: Args) -> Never {
        let command = "notes folder-create"
        requireAutomation(args, command)
        let name = args.require("name", command: command)
        let parent = args.string("parent")

        let placement = parent.map {
            """
            set pf to my folderRef(\(AS.literal($0)))
            if pf is missing value then return {"noparent"}
            set nf to make new folder at pf with properties {name:fn}
            """
        } ?? "set nf to make new folder with properties {name:fn}"

        let source = script("""
        tell application "Notes"
            set fn to \(AS.literal(name))
            \(placement)
            return {"ok", id of nf, name of nf}
        end tell
        """)

        let result = execute(source, args, command: command)
        if result.text(1) == "noparent" { failNoFolder(command, parent ?? "") }

        Out.success(command, ["folder": [
            "id": result.text(2),
            "name": result.text(3),
            "parent": parent ?? "",
        ]])
    }

    private static func folderRename(_ args: Args) -> Never {
        let command = "notes folder-rename"
        requireAutomation(args, command)
        let name = args.require("name", command: command)
        let newName = args.require("new-name", command: command)

        let source = script("""
        set f to my folderRef(\(AS.literal(name)))
        if f is missing value then return {"nofolder"}
        tell application "Notes"
            set name of f to \(AS.literal(newName))
            return {"ok", id of f, name of f}
        end tell
        """)

        let result = execute(source, args, command: command)
        if result.text(1) == "nofolder" { failNoFolder(command, name) }

        Out.success(command, ["folder": [
            "id": result.text(2),
            "name": result.text(3),
            "previous_name": name,
        ]])
    }

    private static func folderDelete(_ args: Args) -> Never {
        let command = "notes folder-delete"
        requireAutomation(args, command)
        let name = args.require("name", command: command)
        requireConfirmation(args, command: command, subject: "folder \"\(name)\"")

        let source = script("""
        set f to my folderRef(\(AS.literal(name)))
        if f is missing value then return {"nofolder"}
        tell application "Notes"
            set nCount to count of notes of f
            if nCount > 0 then return {"notempty", (nCount as text)}
            set fid to id of f
            delete f
            return {"ok", fid}
        end tell
        """)

        let result = execute(source, args, command: command)
        switch result.text(1) {
        case "nofolder": failNoFolder(command, name)
        case "notempty":
            Out.failure(command, BridgeError(
                code: "folder_not_empty",
                message: "Folder \"\(name)\" still holds \(result.int(2)) note(s)",
                hint: "Move or delete the notes first; the bridge will not delete a folder " +
                      "with contents.",
                recovery: ["letta-privacy-bridge notes list --folder \(name)"]
            ))
        default: break
        }

        Out.success(command, [
            "deleted": true,
            "folder": ["id": result.text(2), "name": name],
        ])
    }

    // MARK: - export

    private static func export(_ args: Args) -> Never {
        let command = "notes export"
        requireAutomation(args, command)
        let format = format(args, command: command)
        let html = format == "html"
        let force = args.bool("force")

        if let folder = args.string("folder") {
            guard let directory = args.string("output-dir") else {
                Out.failure(command, BridgeError(
                    code: "missing_argument",
                    message: "--output-dir is required when exporting a folder",
                    hint: "Example: notes export --folder Work --output-dir /tmp/work-notes"
                ))
            }
            exportFolder(folder, to: directory, html: html, force: force, args: args, command: command)
        }

        guard let title = args.string("title") else {
            Out.failure(command, BridgeError(
                code: "missing_argument",
                message: "Pass either --title with --output, or --folder with --output-dir",
                hint: "Run `letta-privacy-bridge notes help` for the option list."
            ))
        }
        guard let output = args.string("output") else {
            Out.failure(command, BridgeError(
                code: "missing_argument",
                message: "--output is required when exporting a single note",
                hint: "Example: notes export --title \"Meeting\" --output /tmp/meeting.txt"
            ))
        }
        exportNote(title, folder: args.string("folder"), to: output,
                   html: html, force: force, args: args, command: command)
    }

    private static func exportNote(
        _ title: String, folder: String?, to path: String,
        html: Bool, force: Bool, args: Args, command: String
    ) -> Never {
        let target = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
        guard force || !FileManager.default.fileExists(atPath: target.path) else {
            Out.failure(command, BridgeError(
                code: "output_exists",
                message: "\(target.path) already exists",
                hint: "Pass --force to overwrite, or choose another path."
            ))
        }

        let source = script("""
        set found to my findNote(\(AS.literal(title)), \(AS.literal(folder ?? "")))
        if item 1 of found is not "ok" then return found
        tell application "Notes"
            set n to note id (item 2 of found)
            return {"ok", item 3 of found, item 4 of found, \(html ? "body of n" : "plaintext of n")}
        end tell
        """)

        let result = execute(source, args, command: command)
        switch result.text(1) {
        case "nofolder": failNoFolder(command, folder ?? "")
        case "nonote": failNoNote(command, title: title, folder: folder)
        default: break
        }

        let bytes = write(result.text(4), to: target, command: command)
        Out.success(command, [
            "exported": 1,
            "format": html ? "html" : "text",
            "files": [["title": result.text(2), "folder": result.text(3),
                       "path": target.path, "bytes": bytes]],
        ])
    }

    private static func exportFolder(
        _ folder: String, to directory: String,
        html: Bool, force: Bool, args: Args, command: String
    ) -> Never {
        let root = URL(fileURLWithPath: (directory as NSString).expandingTildeInPath)
        let source = script("""
        set f to my folderRef(\(AS.literal(folder)))
        if f is missing value then return {"nofolder", {}}
        tell application "Notes"
            set out to {}
            set nCount to count of notes of f
            if nCount > 0 then
                set nIds to id of notes of f
                set nNames to name of notes of f
                repeat with i from 1 to nCount
                    set n to note id (item i of nIds)
                    set end of out to {item i of nNames, \(html ? "body of n" : "plaintext of n")}
                end repeat
            end if
            return {"ok", out}
        end tell
        """)

        let result = execute(source, args, command: command)
        if result.text(1) == "nofolder" { failNoFolder(command, folder) }

        // Created only once Notes has answered, so a dry run or a bad folder name
        // never leaves an empty directory behind.
        do {
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        } catch {
            Out.failure(command, BridgeError(
                code: "output_dir_unwritable",
                message: "Could not create \(root.path): \(error.localizedDescription)"
            ))
        }

        let ext = html ? "html" : "txt"
        var used: Set<String> = []
        var files: [[String: Any]] = []
        for (index, entry) in (result.atIndex(2)?.items ?? []).enumerated() {
            let title = entry.text(1)
            var stem = safeFilename(title, fallback: "note-\(index + 1)")
            var suffix = 2
            while used.contains(stem.lowercased()) {
                stem = safeFilename(title, fallback: "note-\(index + 1)") + "-\(suffix)"
                suffix += 1
            }
            used.insert(stem.lowercased())

            let target = root.appendingPathComponent(stem).appendingPathExtension(ext)
            guard force || !FileManager.default.fileExists(atPath: target.path) else {
                Out.failure(command, BridgeError(
                    code: "output_exists",
                    message: "\(target.path) already exists",
                    hint: "Pass --force to overwrite, or export into an empty directory.",
                    recovery: ["Partial export: \(files.count) file(s) already written to \(root.path)"]
                ))
            }
            let bytes = write(entry.text(2), to: target, command: command)
            files.append(["title": title, "path": target.path, "bytes": bytes])
        }

        Out.success(command, [
            "exported": files.count,
            "folder": folder,
            "format": html ? "html" : "text",
            "output_dir": root.path,
            "files": files,
        ])
    }

    @discardableResult
    private static func write(_ contents: String, to url: URL, command: String) -> Int {
        let data = Data(contents.utf8)
        do {
            try data.write(to: url)
        } catch {
            Out.failure(command, BridgeError(
                code: "write_failed",
                message: "Could not write \(url.path): \(error.localizedDescription)"
            ))
        }
        return data.count
    }

    // MARK: - small helpers

    private static func format(_ args: Args, command: String) -> String {
        let value = (args.string("format") ?? "text").lowercased()
        guard ["text", "html"].contains(value) else {
            Out.failure(command, BridgeError(
                code: "invalid_format",
                message: "Unsupported --format \"\(value)\"",
                hint: "Use text or html."
            ))
        }
        return value
    }

    private static func requireConfirmation(_ args: Args, command: String, subject: String) {
        guard !args.bool("confirmed") else { return }
        Out.failure(command, BridgeError(
            code: "confirmation_required",
            message: "Deleting the \(subject) needs explicit confirmation",
            hint: "Re-run with --confirmed once the user has agreed to the deletion."
        ))
    }

    private static func safeFilename(_ raw: String, fallback: String) -> String {
        let cleaned = raw
            .components(separatedBy: CharacterSet(charactersIn: "/\\:\n\r\t"))
            .joined(separator: "-")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmed = String(cleaned.prefix(120))
        return trimmed.isEmpty || trimmed.hasPrefix(".") ? fallback : trimmed
    }

    private static func escapeHTML(_ raw: String) -> String {
        raw.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
}
