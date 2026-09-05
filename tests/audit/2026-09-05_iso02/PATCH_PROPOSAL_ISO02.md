# ISO-02 — fabricated balance. PROPOSED PATCH, not applied. P0.

Record: `brother-developer/brother_developer/memory/bugs/BUG-2026-09-04-ISO02-fabricated-balance.json`.
Fixtures: this directory (`pytest tests/audit/2026-09-05_iso02 -q` from the repo root; no dependencies).

**BEFORE.** `core/ic_markets.py:62` returns `float(r.json().get("balance", 1000.0))` whatever the
status code; `:63-66` returns `ACCOUNT_BALANCE` (6000.0 on the box, §6) on any exception and calls
it "conservative". `bot.py:839-840` and `:594-595, :1277-1278, :1308-1309, :1384-1385` add
`except Exception: bal=1000.0`; `:1318-1319` uses 0.

**WHY WRONG.** A bridge that answers 503 "mt5 disconnected" has said UNKNOWN; the bot turns that
into 1000.0, which passes the fail-closed margin gate (`bot.py:832-836`, floor 500.0), feeds the
EquityGuard (`risk/equity_guard.py:38-43` moves `peak_balance`), and sizes the lot
(`bot.py:997 calc_lot(...balance...)`). After ISO-01 the v7 bridge answers 503 more often, so the
heartbeat and Telegram lie more often. Freshness Law: missing ≠ default. ADR-005 spirit: a number
the broker did not say is not money.

**AFTER.** `get_balance()` returns `None` unless `status_code == 200` and `balance` is present
(`proposed_get_balance.py`). Callers treat `None` as UNKNOWN: the margin gate already refuses
(`:833-836`); `:839-840` reuses `_bal_gate` instead of re-fetching; every `except Exception:
bal=1000.0` becomes `bal = xtb.get_balance()` followed by `if bal is None: <log UNKNOWN; skip the
guard update / return degraded>`; `EquityGuard.check(None, …)` returns blocked with
`block_reason="balance UNKNOWN"` (fail closed). `ACCOUNT_BALANCE` becomes dead config, documented
as such in `.env`.

**WHY CORRECT.** The only path to an order requires a measured balance; every other path refuses
and says why. No threshold moves: the floor, the guard tiers and `calc_lot` are untouched.

**WHAT COULD BREAK.** (1) The bot stops trading whenever the bridge is down — that is the
intended fail-closed. (2) `equity_guard.update_balance` must never receive `None`; the callers
above guard it, and a test should pin `check(None)`. (3) Telegram "ONLINE" message at `:1384-1390`
prints the balance; it must print UNKNOWN, not 0.

**HOW TESTED.** Contract fixtures in this directory (4 tests) must pass against the real
`ICMarketsClient` once applied (point `prop.requests` at `core.ic_markets.requests`); the evidence
fixtures stay green forever against the pre-patch copy; the source pin fails on the patch commit
and is deleted there; a new `tests/test_equity_guard_unknown.py` pins `check(None)` blocked.
Replay: same signals through old/new must show `BEHAVIOR CHANGED` only when the bridge was down.

```diff
--- a/core/ic_markets.py
+++ b/core/ic_markets.py
@@ def get_balance(self):
-            r = requests.get(url, timeout=5)
-            return float(r.json().get("balance", 1000.0))
-        except Exception as e:
-            fb = float(os.getenv("ACCOUNT_BALANCE","6000.0"))
-            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) - using conservative fallback {fb}")
-            return fb
+            r = requests.get(url, timeout=5)
+            if r.status_code != 200:
+                log.warning(f"[CT] get_balance: bridge answered {r.status_code} — balance UNKNOWN")
+                return None
+            bal = r.json().get("balance")
+            return float(bal) if bal is not None else None
+        except Exception as e:
+            log.warning(f"[CT] get_balance FAILED ({type(e).__name__}) — balance UNKNOWN, no fallback")
+            return None
--- a/bot.py
+++ b/bot.py
@@ -839,2 +839,1 @@
-    try: balance=xtb.get_balance()
-    except Exception: balance=1000.0
+    balance=_bal_gate            # measured, non-None: the gate above already refused otherwise
@@ -594,2 +594,3 @@
-            bal=xtb.get_balance()
-        except Exception: bal=1000.0
+            bal=xtb.get_balance()
+        except Exception: bal=None
+        if bal is None: log.warning("[MONITOR] balance UNKNOWN — guard not updated"); time.sleep(60); continue
(same shape at :563, :1277-1278, :1308-1309, :1318-1319, :1384-1385; /health returns "balance": null and status "degraded")
--- a/risk/equity_guard.py
+++ b/risk/equity_guard.py
@@ def check(self,bal,consecutive_losses,max_losses=3):
+        if bal is None:
+            return GuardResult(allowed=False, block_reason="balance UNKNOWN — bridge unreadable", tier_hit="UNKNOWN")
```
