# SPEC — lolq (League auto-pick bot)

LCU-driven champ-select bot: auto-accept queue, auto-ban, pre-pick, pick per assigned role with per-champion layouts (spells+runes), fallback chain. Hosted editor at `/lolq/` plus a loopback desktop connector. Windows installer bundles the picker and dependencies; builds and install/upgrade/uninstall smoke tests run in GitHub Actions.

## §G goal
player queues → bot accepts ready-check → on champ select: reads assigned role → walks role's layout list in order → first ownable/unbanned champion gets picked+locked, spells set, rune page written. Config edits hot-reload (no bot restart). Hosted editor edits layouts/roles/bans/fallback through the connector at loopback port 17653; legacy source editor remains at 5005. Fresh desktop installs start paused.

## §C constraints
- C1 desktop: `desktop.py` + `bridge.py` + `runtime.py`; windowless PyInstaller directory bundle, per-user Inno Setup installer, tray controls and optional sign-in startup. Public `web.js` serves only UI/downloads through the gateway. Existing picker stack: `main.py` (bot, `lcu-driver` aiohttp wrapper) + `server.py` (Flask config editor) + `static/app.js` (vanilla JS, no build) + `start.py` (launcher). Windows target, pyinstaller onefile.
- C2 local macOS League client is available for explicitly scoped tests. Windows install lifecycle is tested in CI; CI has no running League client. Verify evolving LCU shapes against sources: `https://raw.githubusercontent.com/dysolix/hasagi-types/main/swagger.json`, `swagger.dysolix.dev/lcu`, hextechdocs.dev, community bot repos.
- C3 LCU API undocumented, changes without notice. No official error spec — observed shapes only.
- C4 config format: `{bans[], layouts{id:{champion,spells,runes}}, roles{role:[layout_ids]}, fallback{mode,layout_id}}`; `mode` ∈ `random_default` | `fallback_layout` (editor forces a valid `layout_id`, no unselected state) | `dodge`. Old `champions.{role}.order` auto-migrates (`migrate_config`).
- C5 **push to GitHub on task completion** — `origin` = `github.com/imoutonokoibito/lolq.git` master. NOT under clod push ban.

## §I interfaces
- I.lcu WS events: `/lol-matchmaking/v1/ready-check` (accept), `/lol-champ-select/v1/session` (CREATE/UPDATE → ban/prepick/pick state machine).
- I.lcu REST: PATCH `/lol-champ-select/v1/session/actions/{id}` (ban/pick, `completed:true`=lock), PATCH `.../my-selection` (spells), GET/POST/DELETE `/lol-perks/v1/pages` (runes), GET `/lol-perks/v1/recommended-pages`, GET `/lol-champions/v1/owned-champions-minimal` (ownership).
- I.ddragon: versions.json → champion.json (name→id map), runesReforged.json (rune fuzzy match). communitydragon perks.json → stat-shard ids.
- I.editor: loopback :17653 `/api/session`, `/api/status`, GET/POST `/api/config`; Host/Origin checks, custom header, process-local bearer token, bounded validation and atomic writes. No raw LCU routes. Legacy Flask editor remains on :5005.
- I.cfg `config.json` — hot-reloaded every champ-select event.
- I.ci `.github/workflows/build.yml` — Windows installer on push, tested artifact `LoLQ-Windows`; version tags publish EXE + SHA256SUMS. `README.md` describes current install/release contracts.

## §V invariants
- V1 **champ-select `assignedPosition` is LOWERCASE** (`"top"…"utility"`, `""` blind/ARAM). Uppercase exists only in lobby position-*preference* fields (different endpoint). Any role-keyed dict (`role_mapping`, `DEFAULT_SPELLS`) is UPPERCASE-keyed → normalize `.upper()` at capture. Skip = every role silently falls to `'mid'` default (support got Ahri/Veigar). Community proof: sona `normalizePosition`, LeagueAkari lowercase role keys.
- V2 **never trust 2xx on pick PATCH.** LCU accepts unowned-champion PATCH without HTTP error in some client versions. Check BOTH: `champion_id in owned_champion_ids` (fetched on connect, `None`=fetch-failed→skip check, not "owns nothing") AND `resp.status >= 400` → treat as rejected, fall through to next layout.
- V3 **exact normalized match for reverse lookups, never substring.** `"healthscaling".includes("health")` → Defense shard row shows wrong selection on picker reopen. Substring OK only for forward user-input fuzzy match (`find_rune_by_name`), never config-value→UI reverse mapping.
- V4 **config hot-reload every champ-select event** — `load_config()` inside handler, never cached at boot. Editor + bot run concurrently.
- V5 **fallback chain never dead-ends:** layout list exhausted → fallback mode (`fallback_layout` → `random_default`). Random pick excludes banned; retries cap at 5. Sole exception: `dodge` mode — on our live pick turn with every candidate failed, leave champ select (`dodge()`: team-builder `session/quit` → gameflow `session/dodge` → legacy `quitV2` invoke; first 2xx wins; once per session; never in PLANNING).
- V7 **champion endpoints 404 until the client loads champion data** (`RPC_ERROR` "Champion data has not yet been received."). Startup race, not failure → retry with backoff in the background (`load_owned_champion_ids`), retry once more at champ select, log the expected 404 at debug (`quiet_statuses`). Never treat it as "owns nothing".
- V8 **never arm a TPM clear automatically** (`src/`). PPI `Request = 22` clears the TPM at boot: SRK + owner auth gone, TPM-sealed keys (BitLocker, Hello) broken, and the "fix" undoes itself each reboot. Heal in place only (auto-provisioning + `Tpm-Maintenance` + `Initialize-Tpm`); clears opt-in via `tpmfix -AllowClear`, guarded on BitLocker/Hello. Unattended coverage = the `TpmHeal` SYSTEM task (boot + resume + daily), which must actually be registered.
- V6 pick/ban loop guards: banned champion → next layout; unknown name → next layout; `pick_number`/`ban_number` reset after phase so next game starts clean.

## §T tasks
| id | st | task | cites |
|----|----|------|------|
| T1 | x | layouts+roles config format, migration, hot-reload | C4,V4 |
| T2 | x | ownership check + status check on pick/prepick | V2 |
| T3 | x | rune picker shard exact-match reverse lookup | V3 |
| T4 | x | assignedPosition lowercase normalize | V1 |
| T5 | ~ | no runnable check for pick state machine — extract role/pick decision logic to pure function + `test_*.py` when next touched (`tests/test_champion_select.py` covers handler + fallback/dodge) | V1,V2,V5 |
| T6 | x | `dodge` fallback mode; editor "Use layout" always has a layout selected | C4,V5 |
| T7 | x | retry owned-champions through the client's champion-data load; silence lcu-driver's empty-frame logging error | V7 |
| T8 | x | non-destructive TPM heal + registered `TpmHeal` task; no auto-clear | V8 |

## §B bugs
| id | date | cause | fix | cites |
|----|------|-------|-----|------|
| B1 | 2026-08 | rune-picker Defense shard reverse-match used `includes()`; `health` matched before `health scaling` → wrong shard shown on reopen (saved config was correct) | exact normalized-string match in `openRunePicker` | V3 |
| B2 | 2026-08 | pick loop treated any non-exception PATCH as success; never checked status or ownership → unowned champ "Successfully picked", no fallthrough | fetch `owned-champions-minimal` on connect; check ownership + `resp.status>=400` before declaring success | V2 |
| B4 | 2026-10-04 | `tpmfix` armed boot-time TPM clear (PPI op-22) as its fallback; promised `TpmHeal` task was never registered | heal in place, cancel leftover clears, `-AllowClear` opt-in + guarded, register the SYSTEM task | V8 |
| B5 | 2026-10-04 | single owned-champions fetch on connect hit the client's "Champion data has not yet been received" 404 window → ownership unknown all session | background retry with backoff + champ-select retry; expected 404 at debug | V7 |
| B3 | 2026-09-02 | `assigned_position` compared raw lowercase LCU value against UPPERCASE `role_mapping` keys → every lookup missed → `'mid'` default for ALL roles (utility got mid layouts: Ahri→Veigar) | `.upper()` normalize at capture in `champ_select_changed` | V1 |
