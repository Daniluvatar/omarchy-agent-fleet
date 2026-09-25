# Reference Notes

Phase 1 discovery for Omarchy Agent Fleet, verified 2026-09-25 on the author's
machine (Omarchy `4.0.4-1`, `OMARCHY_PATH=/usr/share/omarchy`).

Each section names the file or command it came from. Nothing here is inferred
from upstream documentation. No credential values appear anywhere in this
repository; stores are described by key name and by presence/absence only.

Structural reference for this plugin:
**`/usr/share/omarchy/shell/plugins/agents/`** (first-party, same product
domain), cross-checked against the third-party
**`~/.config/omarchy/plugins/calmasacow.grok-usage/`** because it is the only
usage-reporting plugin already installed by someone other than Omarchy.

---

## 1. Manifest format

Authoritative source: `/usr/share/omarchy/bin/omarchy-plugin-validate`, which
"mirrors the checks in `shell/services/PluginRegistry.qml`".

| Rule | Enforcement |
|---|---|
| `manifest.json` present and valid JSON | `jq -e .` |
| `schemaVersion` is the JSON **number** `1` | type-aware `==`; `"1"` fails |
| Required fields | `id`, `name`, `version`, `kinds`, `entryPoints` |
| `id` format | `^[A-Za-z0-9][A-Za-z0-9._-]*$`, no `..` |
| `id` namespace | may not start `omarchy.` |
| `kinds` | non-empty array |
| `entryPoints` | object; each value a relative path, no `..`, **file must exist** |
| kind → entry point key | `bar`→`bar`, `bar-widget`→`barWidget`, `menu`→`menu`, `overlay`→`overlay`, `panel`→`panel`, `service`→`service` |
| `barWidget.defaultSection` | when present: `left` \| `center` \| `right` |
| Symlinks | **refused anywhere inside the folder** (`.git` pruned) |

`io.github.daniluvatar.agent-fleet` satisfies the regex and avoids the reserved
namespace. Observed third-party ids follow the same loose convention:
`calmasacow.grok-usage`, `io.github.ramous19.copilot-companion`,
`io.github.selfcrypto.power-saving`, `mohamedmansour.finance`,
`local.omarchy-voice`.

`omarchy plugin validate .` passes on this scaffold.

## 2. Plugin directory structure

| Fact | Value | Evidence |
|---|---|---|
| Third-party plugins live in | `~/.config/omarchy/plugins/<plugin-id>/` | `shell/plugins/README.md`; five plugins observed there |
| First-party plugins live in | `/usr/share/omarchy/shell/plugins/<short-dir>/` | `agents/` observed; registry marks them `__isFirstParty: true` |
| Registry | `/usr/share/omarchy/shell/services/PluginRegistry.qml` | named in the validator comment |
| Directory contents in practice | `manifest.json`, one or more `*.qml`, optional `assets/`, `scripts/`, `README.md`, `LICENSE`, `preview.png` | `agents/`, `calmasacow.grok-usage/` |
| Install method | git checkout into the plugins dir (`omarchy plugin add <git-url>`) | `omarchy-plugin-add` |

The plugin folder is the repository root: `calmasacow.grok-usage` keeps
`manifest.json` at the top of its git repo, so this repo is also flat and can be
cloned straight into the plugins directory.

## 3. Bar-widget entry point

One QML file is the whole widget. From the first-party widget
(`agents/Panel.qml:335-347`) the bar slot is:

```qml
BarIconButton {
  id: button
  anchors.fill: parent
  bar: root.bar
  text: "󱚣"              // static Nerd Font glyph, one for the whole feature
  active: root.alarming   // true only when headline.percent >= 0.9
  onPressed: root.toggle()
}
```

`Panel { moduleName; ipcTarget; manageIpc: false }` is the root, and it owns
both the bar button and the popup. `implicitWidth/Height` come from the button.

**Premise confirmed:** the bar shows one glyph and no number. Percentages,
meters and reset countdowns exist only inside the popup (`LIMITS`, `BALANCE`,
`TOKENS BY DAY`, `TOKENS BY MODEL` sections, `agents/Panel.qml:598-691`). The
only at-a-glance signal is a colour change, silent below 90 % used. Showing
"3 %" and "100 %" in the bar is the gap Agent Fleet fills.

## 4. Panel entry point

There isn't one, and that corrects a playbook assumption: a `bar-widget`
declares a single `entryPoints.barWidget`, and the popup is a child of the same
file. The popup pattern (`agents/Panel.qml:351-386`):

```qml
KeyboardPanel {
  id: panel
  anchorItem: button
  owner: root
  bar: root.bar
  open: root.opened
  focusTarget: keyCatcher
  contentWidth: panel.fittedContentWidth(Style.space(380))
  contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(640))
  // PanelKeyCatcher > Flickable > Column  for scrolling + keyboard nav
}
```

`fittedContentWidth` / `fittedContentHeight` and `Style.space(n)` are how
existing widgets size themselves; hard-coded pixel sizes would fight the theme.

## 5. Command execution pattern

Quickshell's `Process` (import `Quickshell.Io`), driven by a `running`
property, with `StdioCollector` for stderr — from `agents/Main.qml:140-168`:

```qml
Process {
  id: updateProcess
  command: ["omarchy-agent-usage-update", "--limits-only"]
  onExited: ...
  stderr: StdioCollector {
    waitForEnd: true
    onStreamFinished: if (text.trim() !== "") console.warn("agents", text.trim())
  }
}

function runUpdate(kind, agentIds) {
  if (updateProcess.running) { /* collapse queued refreshes */ return }
  updateProcess.command = updateCommand(kind, agentIds)
  updateProcess.running = true
}
```

Two reusable ideas: refresh requests that arrive while a run is in flight are
**collapsed** instead of queued, and the command array is reassigned before
`running` is set. Diagnostics go to the shell console with a module prefix, so
our collector must keep secrets out of stderr as well as stdout.

## 6. Refresh / timer pattern

`agents/Main.qml:118-126` and `:224`:

```qml
property int refreshIntervalSec: Math.max(30, Number(setting("refreshIntervalSec", 900)))
Timer { interval: root.refreshIntervalSec * 1000; repeat: true; triggeredOnStart: true }
```

- Default **900 s**, floor **30 s**, schema clamp `30..3600` step `30`
  (`agents/manifest.json`).
- Opening the popup triggers `refreshLimits()` → `--limits-only`, "because the
  panel wants the numbers that go stale on the wire, not another walk over
  every transcript on disk".
- Settings are read through `setting(key, default)` and declared in
  `manifest.json → barWidget.schema`, which is what renders the settings UI.
  Task 1 declares `refreshIntervalSec` with the same default (900) and a
  coarser 60 s floor.

## 7. Installation / development workflow

```text
omarchy plugin add [git-url] [--enable] [--yes]   # alias: omarchy plugin install
omarchy plugin enable <id> [placement]
omarchy plugin disable <id>
omarchy plugin remove [id] [--yes]
omarchy plugin update [id] [--yes]
omarchy plugin list [--json]
omarchy plugin validate <plugin-folder>
omarchy plugin clone <source-id> [--edit]        # copy a built-in plugin into user config
```

Constraints found:

- `add` takes a **git url only**; there is no install-from-directory. The
  iteration loop is therefore: commit, then clone/copy into
  `~/.config/omarchy/plugins/io.github.daniluvatar.agent-fleet/`, then
  `omarchy plugin enable io.github.daniluvatar.agent-fleet`.
- A symlinked plugin folder is rejected outright, so `ln -s` is not a dev loop.
- Bar placement is data, in `~/.config/omarchy/shell.json` under
  `bar.layout.left/center/right`, as `{ "id": "<plugin-id>", ...settings }`.
  Defaults: `/usr/share/omarchy/config/omarchy/shell.json`. Five third-party
  widgets are already placed in the user's layout, which proves third-party
  entries are first-class. `disabledPlugins: []` is the disable list.
- Task 1/2 therefore change **no** system file and, until you approve enabling
  it, no user config file either.

## 8. Codex data facts (drives Tasks 3-4)

`omarchy-agent-usage-codex --limits-only` works today and is the collector the
playbook prefers to reuse. Measured on this machine: exit `0`, empty stderr,
**1.07 s / 1.27 s**. It does not need the first-party plugin to be installed, so
Agent Fleet depends on the command, not on `omarchy.agents`.

Live shape (trimmed; the command emits more keys, see the record contract
below):

```jsonc
{
  "schemaVersion": 1, "id": "codex", "name": "Codex",
  "ready": true,
  "updatedAt": "2026-09-25T18:05:25.561582+00:00",
  "tierLabel": "plus",
  "usageStatusText": "",
  "authHelpText": "Run `codex login` to authenticate.",
  "limits": [
    { "label": "5h window",      "percent": 0.03, "resetsAt": "2026-09-25T19:26:51+00:00" },
    { "label": "Weekly (7-day)", "percent": 1.0,  "resetsAt": "2026-09-26T18:40:25+00:00" }
  ],
  "hasLocalStats": true, "todayPrompts": 0, "todaySessions": 0,
  "todayTotalTokens": 0, "todayTokensByModel": {}, "recentDays": [],
  "totalPrompts": 0, "totalSessions": 0, "activeDays": 0, "activeDates": [],
  "modelUsage": {}
}
```

Notes that change how the adapter must be written:

1. **`percent` is a fraction of 1** — `0.03` is 3 %, `1.0` is 100 %. Confirmed
   in the collector (`limit_window()` returns `float(used) / 100.0`) and in
   `agents/Panel.qml:44` (`headline.percent >= 0.9`). The playbook's
   `usedPercent` conversion is therefore required, and `1.0` must not be
   treated as "unknown".
2. **`label` is display text, not a stable key.** Observed variants:
   `"5h window"`, `"Weekly (7-day)"`, plus a `"<n>m window"` variant produced by
   the collector. Map to the contract's `session` / `weekly` semantically
   (`/5h/i`, `/week|7/i`) with array order as fallback, exactly as the playbook
   asks.
3. **`resetsAt` is ISO-8601 with offset, or `""`.** Whole seconds from Codex,
   sub-second from others; parse tolerantly.
4. **Empty `limits[]` means unknown, never "no quota".** The reason arrives in
   `usageStatusText` and the remedy in `authHelpText`. This is the graceful
   failure path of Task 4: render those two strings, not an exception.
   Verified locally — the sibling `claude.json` record currently reads
   `ready: false`, `usageStatusText: "Waiting for auth"`,
   `authHelpText: "Run \`claude auth login\` to restore authoritative usage."`,
   `limits: []`, which is a real, live example of the state we must handle.
5. The collector caches local stats under `$XDG_CACHE_HOME/omarchy/agent-usage`
   (source line 341) and reuses a scan up to 900 s old in `--limits-only` mode
   while always re-probing the wire limits. That directory does not exist yet
   here, so the ~1.1 s above is close to a cold number and still inside a
   reasonable bar budget.
6. Codex auth is local and already works: `~/.codex/auth.json` (mode `0600`)
   holds `auth_mode: "chatgpt"` — subscription, not API key — plus `tokens`.
   Agent Fleet never reads this file; it is recorded only to show that no API
   key is involved and that the playbook's "no OpenAI API billing" constraint
   holds for the reuse path.

## 9. Things that change assumptions for Phase 2

Reported, not acted on. All of these are out of Phase 1 scope.

- **`omarchy-agent-usage-update` is the fan-out driver** and writes one record
  per agent to `$XDG_STATE_HOME/omarchy/agents/usage/<agent>.json`. Its
  contract is the union of the keys in §8 plus optional `scope`,
  `hasPromptStats`, `retryAdvised`, and per-limit `kind`/`startsAt`/`title`.
  `agents/README.md` states an agent can be added "without touching this
  plugin: ship a collector that prints the record contract".
- **It only globs `$OMARCHY_PATH/bin/omarchy-agent-usage-*`**, a
  package-owned directory, so a third-party collector cannot join that fan-out.
  `calmasacow.grok-usage` proves the working alternative: ship the collector
  inside the plugin (`scripts/omarchy-agent-usage-grok`), run it as
  `Process { command: ["python3", "-B", …] }` (`Main.qml:126,135`), read the
  directory from `XDG_STATE_HOME` (`Main.qml:16`). Its `grok.json` is live on
  this machine at `tierLabel: "SuperGrok"`.
- **Claude and Fireworks are already first-party collectors**
  (`omarchy-agent-usage-claude`, `-fireworks`), and Claude's covers
  "Anthropic's OAuth usage endpoint (5-hour session + 7-day weekly)". So the
  playbook's later "additional providers" item is partly pre-built, and a
  multi-agent Agent Fleet should read records rather than re-scrape providers.
- **The first-party widget already ships sync** (`syncMode`, `syncDir`,
  `syncFileName`, `syncDeviceId` in its manifest; snapshot merge in
  `calmasacow.grok-usage`) — relevant to the future cross-machine story.
- **`~/.local/bin/opencode` is a mise shim.** First execution installed
  `opencode@1.18.27` (60.5 MB, 26.5 s); warm `opencode auth list` is 0.57 s and
  reports `0 credentials`. Any future provider probe must never be the thing
  that triggers a toolchain install from the bar.

## 10. Reproducing these notes

```bash
omarchy plugin list --json
omarchy plugin --help
find /usr/share/omarchy -path '*agents*' -o -iname '*agent*usage*' 2>/dev/null
ls -l /usr/share/omarchy/bin/omarchy-agent-usage*
sed -n '1,60p;330,400p' /usr/share/omarchy/shell/plugins/agents/Panel.qml
sed -n '110,200p' /usr/share/omarchy/shell/plugins/agents/Main.qml
jq '{id,ready,tierLabel,usageStatusText,limits}' ~/.local/state/omarchy/agents/usage/codex.json
omarchy-agent-usage-codex --limits-only | jq '{tierLabel,limits}'
```
