# lolq — project rules

> `SPEC.md` is source of truth — cavekit runs implicitly (global hook injects
> scenario→skill routing every turn; §V read on demand). High-risk zones: LCU
> field casing/response handling (`main.py` pick state machine), rune picker
> reverse lookup (`static/app.js`).

**Always `git push` to GitHub on task completion.** Remote: `origin` →
`https://github.com/imoutonokoibito/lolq.git`, branch `master`. This repo is
NOT under the clod GitHub-push ban — that ban is `xXhackerlordXx/clod/` only.

## Stack

- `main.py` — bot, uses `lcu-driver` (aiohttp wrapper around the League
  Client's local LCU API). Runs on Windows, built to exe via
  `.github/workflows/build.yml` (pyinstaller, windows-latest runner).
- `static/app.js` + `server.py` — local web config editor for `config.json`
  (layouts/roles/bans/fallback). Pure vanilla JS, no build step.
- Tests: `python -m unittest discover -s tests -v`; Windows installer lifecycle in CI.
- A local macOS League client is available for scoped tests. CI has no League client.
- Desktop/release architecture and setup are documented in `README.md`; update affected contracts alongside implementation.

## LCU API — undocumented, verify via community sources

Riot does not officially document the LCU API. It can change without notice.
When touching `main.py`'s LCU calls, verify against:
- Swagger dump (most reliable, kept current by community reverse-engineering):
  `https://raw.githubusercontent.com/dysolix/hasagi-types/main/swagger.json`
  (huge file, `python3 -c "import json; ..."` grep it, don't try to read whole)
- `https://swagger.dysolix.dev/lcu/` — browsable version of the same
- `https://hextechdocs.dev/` — LCU getting-started + FAQ
- Community bot scripts on GitHub (search `lcu-driver`, `lcu-api`,
  `LCU-Instalock-Champion`) for real request/response shapes and observed
  error formats, since Riot's LCU has no official error spec.

**Ownership check**: `/lol-champions/v1/owned-champions-minimal` (GET, no
params) returns the logged-in account's owned champions only (list of
`{id, alias, name, active, ownership: {owned, rental, ...}, ...}`). Distinct
from `/lol-champions/v1/inventories/{summonerId}/champions-minimal`, which
returns the FULL roster regardless of ownership. Always check ownership
against the `owned-champions-minimal` set before PATCHing a pick — the LCU
does not reliably reject an unowned-champion pick at the HTTP layer in every
client version, so silently trusting a 2xx response is not safe. Check
`resp.status >= 400` on pick/pre-pick PATCH responses too and treat as a
rejected pick (fall through to the next configured layout), never assume
success from lack-of-exception alone.

**assignedPosition casing**: the champ-select session's
`myTeam[].assignedPosition` is LOWERCASE (`"top"`, `"jungle"`, `"middle"`,
`"bottom"`, `"utility"`; `""` in blind/ARAM). Uppercase position strings only
appear in lobby position-preference fields (different endpoint). Community
confirmation: sona `normalizePosition` lowercases + matches `'middle'`,
`'bottom'`, `'utility'`. Any dict keyed by role in `main.py`
(`role_mapping`, `DEFAULT_SPELLS`) is UPPERCASE-keyed, so `assigned_position`
must be `.upper()`-normalized at capture. Skipping this silently falls back
to mid for every role.

**Dodge** (`fallback.mode == "dodge"`): `main.py` `dodge()` POSTs the LCDS
`quitV2` invoke (`/lol-login/v1/session/invoke`, args as real query params
*and* body `{"data": [...]}` — the no-body form is rejected locally in ~1ms),
then `/lol-lobby-team-builder/champ-select/v1/session/quit`, up to
`DODGE_ROUNDS` times. A 2xx proves nothing: success is confirmed by
`/lol-gameflow/v1/gameflow-phase` leaving `ChampSelect`. Not used:
`/lol-gameflow/v1/session/dodge` is the client's own dodge *notification*
(requires body `{state, dodgeIds, phase}`), not a request to leave. Only fires
on our actual pick turn after every candidate failed, never during PLANNING.

## `src/` — TPM helpers (not part of the bot)

`tpmcheck` (read-only state report), `tpmheal.ps1` (non-destructive heal, used by
the task), `tpmfix` (wrapper; `-AllowClear` is the only destructive path),
`tpmheal-install` (registers the `TpmHeal` SYSTEM task: boot + resume + daily).
Heal runs log to the Application event log, source `TpmHeal`.

**Never arm a TPM clear automatically.** `SetPhysicalPresenceRequest` with
`Request = 22` queues a boot-time TPM clear, which wipes the SRK and owner
auth; anything sealed to the TPM (BitLocker protectors, Windows Hello) breaks.
This machine: Intel PTT 2.0, Win10 19045, Secure Boot DISABLED in BIOS (so
TPM-WMI 1796 at every boot, PCR7 unbound) — Vanguard only gates on TPM 2.0 +
Secure Boot on Windows 11, so TPM readiness was never the VAN blocker here.

## Known-fixed bugs (don't reintroduce)

- **TPM "fix" that undid itself every boot** (`src/tpmfix.ps1`): when the live
  heal did not finish within 48s it armed PPI op-22, a boot-time TPM *clear*.
  Each reboot then wiped the SRK and owner auth and re-provisioned from
  scratch (System log 1793 → 519 `ByPPI` → 1027 → 1025, 2026-09-28 and
  09-29/30), so every run destroyed the state the previous run created. It
  also promised a `TpmHeal` task that was never registered, so nothing healed
  anything unattended. Fixed: heal is non-destructive, clears are opt-in and
  guarded, leftover pending clears get cancelled, and `TpmHeal` actually
  exists as a SYSTEM task on boot/resume/daily.
- **Owned-champions fetch gave up on a startup race** (`main.py` `connect`):
  champion endpoints answer `404 RPC_ERROR "Champion data has not yet been
  received."` until the client's champions plugin finishes loading, and the
  single attempt on connect landed inside that window, so ownership stayed
  unknown for the whole session. Fixed by retrying in a background task with
  backoff (`load_owned_champion_ids`) plus one more attempt at champion
  select; the expected 404 is logged at debug via `quiet_statuses`.
- **Wrong role's layouts picked (support got mid champs)** (`main.py`
  `champ_select_changed`): `assigned_position` was compared raw against
  UPPERCASE `role_mapping` keys, but the LCU sends it lowercase — every
  lookup missed and fell to the `'mid'` default, so a UTILITY player got the
  mid layouts (Ahri → Veigar). Fixed by `.upper()`-normalizing at capture.
  See "assignedPosition casing" above.
- **Rune-picker shard mis-render on reopen** (`static/app.js`
  `openRunePicker`): the Defense stat-shard row has both `health` (5011) and
  `health scaling` (5001). Reverse-matching a stored config value with
  substring/`includes()` matches `health` before `health scaling` reaches
  its turn (`"healthscaling".includes("health")` is true), so opening the
  picker again visually shows the wrong shard selected even though the
  saved config is correct. Fix: exact normalized-string match only, never
  substring, for shard reverse-lookup.
- **False "Successfully picked" for unowned champions** (`main.py`
  `champ_select_changed`): the pick loop treated any non-exception PATCH as
  success and never checked LCU response status or actual champion
  ownership, so an account without a configured champion would pick it,
  "succeed" per the logs, and never fall through to the next layout. Fixed
  by fetching owned-champion IDs on connect and checking both ownership and
  response status before declaring a pick successful.
