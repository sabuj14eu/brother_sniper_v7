# config/symbols.json — the symbol registry

One entry per instrument, overlaid onto the hard-coded fallback dicts at boot
(`core/symbol_registry.py` documents the schema). An empty `{}` file means the
bot runs exactly on the hard-coded dicts. Entries with `"enabled": false` are
BENCH-LISTED: their aliases stay unknown, so any signal for them is rejected
upstream as `unsupported` — identical to today.

## Enable ceremony for a new symbol (one symbol at a time — Iron Rule 5)

1. **Broker check** (from any box that can reach the bridge):
   ```bash
   B=http://<bridge-host>:5001
   for s in SOLUSD ADAUSD LINKUSD; do
     echo "== $s"; curl -s "$B/candles?symbol=$s&tf=60&n=2" | head -c 200; echo
   done
   ```
   Rows back = the broker offers it under that name. Errors = check the exact
   instrument name in the MT5 Market Watch and fix the entry's `mt5`/aliases.
2. **Spec verification** — open the MT5 symbol specification window and copy
   the real tickSize, tickValue, volume min/step/max into the entry's `spec`,
   plus sensible `demo_max_lot`. Delete the `SPECS UNVERIFIED` note.
3. **Bridge deploy** (Windows ceremony: backup -> copy -> NSSM restart ->
   verify /health) so the bridge's own SYMBOL_MAP knows the aliases. The
   bridge passes unknown symbols through verbatim, and v7 already sends the
   broker name from the entry's `mt5` key, so this step is belt-and-braces.
4. Flip `"enabled": true`, deploy v7 (backup -> restart sniper-bot -> verify
   `[SYMBOLS] registry applied: ...` in logs/bot.log).
5. **Watch the bench first**: confirm candles flow (`/candles?symbol=...`),
   the platform bias heartbeat picks it up, and decisions appear with the new
   symbol before trusting any trade.

## Rules that do NOT change when adding symbols

- The **crypto slot stays single** — SOL/ADA/LINK/XRP/BTC/ETH all contend for
  one concurrent crypto position. More opportunities, not more exposure;
  widening slots is a human risk decision (Iron Rule 7), never a config edit.
- **Never pool a new symbol's stats with older symbols** — days of history vs
  weeks. n<20 is luck (Iron Rule 5); per-symbol columns stay separate.
- Registry entries set per-symbol *parameters* only. They cannot touch risk
  sizing, gates, thresholds or strategy rules.
