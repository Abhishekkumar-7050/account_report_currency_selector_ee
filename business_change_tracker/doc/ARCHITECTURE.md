# Business Change Tracker — Architecture Decision Record (Phase 1–2)

Status: **Proposed — awaiting approval before implementation**
Target: Odoo 19.0 (Community + Enterprise), module `business_change_tracker`

## 1. Research findings (Odoo 19 source)

| Area | Finding | Consequence |
|---|---|---|
| `BaseModel.write/create/unlink` (`odoo/orm/models.py`) | `create` is `@api.model_create_multi` taking `vals_list`; `write` applies one `vals` to a multi-record set; `unlink` deletes a set. | Must handle batches natively; one old/new snapshot per record. |
| `_register_hook` / `_unregister_hook` | Called after registry build. **Core `base_automation` uses it to `setattr` wrapped `create/write/unlink` onto registry classes** for configured models only. OCA `auditlog` uses the same pattern. | Runtime class patching is the "official" way core does *configurable* interception — but it needs manual unpatching, registry invalidation and has ordering subtleties. |
| `_inherit = 'base'` | Supported mechanism to extend every model (used by `web`, `mail`, `base_import`...). Class disappears cleanly when the module is uninstalled. | A no-monkey-patch alternative for generic interception. |
| `mail.thread` tracking | `_track_prepare` snapshots initial values into `cr.precommit.data`, `_track_finalize` writes `mail.tracking.value` at precommit. Only fields declared `tracking=True`, only on `mail.thread` models; context `mail_notrack` / `tracking_disable` turns it off; stored in chatter messages. | Not configurable per field without code, not on non-mail models (e.g. `sale.order.line`, `purchase.order.line`), can be disabled by any caller's context, mixed with chatter. **Not a suitable foundation**, but we must not interfere with it. |
| Access APIs | `has_access(op)`, `_has_field_access(field, 'read')`, `_search()` returns a `Query` usable as SQL sub-select. | Lets us enforce *source-record* security on logs efficiently in SQL. |
| Cache invalidation | `registry.clear_cache()` + `@tools.ormcache` is signalled across workers. | Rule changes propagate without restarts or registry reload. |

## 2. Options compared

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Model-specific inheritance** (`_inherit='sale.order'` …) | Simple, explicit | Hard dependency on sale/purchase/account/stock; admin can't add models; one override per model | ✗ Not generic |
| **B. Generic `_inherit='base'` override of create/write/unlink** | Pure inheritance (no monkey patch); clean uninstall/upgrade; works for any model incl. custom ones; participates in normal MRO | Runs for every model's write → must short-circuit in O(1) | ✅ **Chosen** |
| **C. Hook into mail tracking** | Reuses chatter UI | Only `tracking=True` fields & mail.thread models; disabled by `mail_notrack`; no line models | ✗ |
| **D. Wrap/depend on OCA auditlog** | Mature | External dependency (App Store unfriendly), technical-audit oriented, patching model | ✗ |
| **E. `_register_hook` class patching (base_automation style)** | Zero overhead on untracked models | Monkey patching; must unpatch; registry invalidation on every rule change (`registry_invalidated`), ordering issues vs other patchers | ✗ Not needed given B's overhead is negligible |
| F. PostgreSQL triggers | Catches raw SQL | No user/label/business rendering, bypasses ORM & security, hard uninstall | ✗ |

### Why B is safe
* **Overhead**: the first line of each override is a lookup in an `ormcache`d `frozenset` of tracked model names → one dict/set lookup for untracked models. No queries.
* **No recursion**: the log model and all `ir.*`/`bus.*`/transient/abstract models are hard-excluded; logs are created with context key `bct_no_track`; the engine never writes to tracked records.
* **Compatibility**: we call `super()` exactly once and never alter `vals`/return values; exceptions from the business write propagate unchanged (we don't catch them).
* **Uninstall**: removing the module removes the class from the MRO; nothing left patched. Log table is dropped (documented — export first).
* **Upgrade**: no stored state in Python classes; rule map rebuilt lazily from DB.

## 3. Tracking engine

```
write(vals):
    rule = tracking_map.get(self._name)          # ormcache, O(1)
    if not rule or guard_active(): return super()
    fnames = rule.fields ∩ vals.keys()           # only written *and* configured fields
    if not fnames: return super()
    old = snapshot(self, fnames)                 # one batched read, stored fields only
    res = super().write(vals)
    new = snapshot(self, fnames)                 # after write (post-compute/inverse)
    diffs = [(rec, f, o, n) for … if o != n]     # same-value write → nothing
    Log.sudo().create(batch of diffs)            # ONE create call per write()
    return res
```
* **create**: after `super()`, one "Created" event per record (if rule.track_create) plus optional initial values of tracked fields (off by default — avoids noise).
* **unlink**: before `super()`, one "Deleted" event per record with `record_name` snapshot. We **do not** claim record reconstruction.
* **Transactions**: logs are inserted in the same cursor → rollback removes them (no precommit/queue/separate cursor). Tested explicitly (savepoint).
* **o2m on parent write** (e.g. order lines edited from SO form): captured on the *line* model when a line rule exists; each line log also stores the parent reference (`parent_model`, `parent_res_id` via rule's configured "parent field", e.g. `order_id`) so the SO's Change History shows line changes too. This is the key business feature.
* **Guards**: skip when `registry.ready` is False (module install/upgrade data loading), context `bct_no_track`, `install_mode`; rule option "Track system/superuser changes" (default on — cron & automations run as real users or `__system__`, we record the acting user; admin can exclude OdooBot).
* **What is NOT captured** (documented): raw SQL writes; non-stored computed fields; stored computed fields recomputed from *another* record (same-record dependencies are captured through `registry.field_depends`); `mail_notrack` has no effect (by design, we are independent).

## 4. Data model

### `business.change.rule` (configuration)
`name, model_id (ir.model, ondelete cascade), model_name (related, stored, indexed), field_ids (m2m ir.model.fields, domain: stored, not binary/one2many), track_create, track_unlink, parent_field_id (optional m2o field for roll-up), active, company_ids (optional scope)`. Constraint: one active rule per model. CRUD → `registry.clear_cache()`.

### `business.change.log` (one row per field change; create/delete = one row with no field)
| Column | Why |
|---|---|
| `res_model` (char, idx), `res_id` (int, idx), composite index `(res_model, res_id, changed_at desc)` | Record-level history is the hot path. Char rather than m2o ir.model so logs survive model uninstall. |
| `model_id` m2o ir.model (ondelete **set null**) | Nice label / grouping; survives deletion. |
| `record_name` char | Snapshot for deleted records — never fabricated later. |
| `parent_model`, `parent_res_id` (idx) | Line changes shown on the order. |
| `field_name` char, `field_id` (ondelete set null), `field_label` char snapshot, `field_type` | Survive field deletion. |
| `operation` selection create/write/unlink (idx) | Filters. |
| `old_value_display`, `new_value_display` Text | Human-readable snapshot at change time (m2o names, selection labels, m2m added/removed). |
| `old_value_raw`, `new_value_raw` Json | Typed values (ids, floats, ISO dates) — for locale-aware re-rendering (dates/tz/number format per viewer) **and V2 business rules** (price −10 %, date moved later). |
| `currency_id` | Monetary rendering. |
| `user_id` (idx), `changed_at` datetime (idx), `company_id` (idx) | Who/when/where. `create_date` not reused so retention/order is explicit. |
| `is_important` bool, `importance_rule_id` (reserved, unused V1) | V2 foundation, no logic now. |

The table is **append-only**.

## 5. Serialization (rendered display strings)
many2one → `display_name` (sudo read of name only); selection → label via `_description_selection(env)`; many2many → "Added: X, Y / Removed: Z"; boolean → Yes/No; integer/float → `formatLang` with field digits; monetary → with record currency symbol; date/datetime → raw ISO stored, formatted **at display time** in viewer lang/tz; char/text → truncated at 1 000 chars; html → converted to plain text (`html2plaintext`) → no XSS, shown in text widget; binary/image → "(file changed)" + size, never content; one2many / non-stored / properties → not selectable in rules (V1).

## 6. Security
* Groups: **Change Tracker User** (read logs), **Change Tracker Manager** (implies User; manages rules/retention). Admin in Manager by default.
* ACL: log = read-only for both groups; create only via engine `sudo()` (justified: users who change a SO must not need write rights on logs). `write`/`unlink` overridden to raise `UserError` — except the retention cron (internal context flag + superuser check).
* Multi-company: standard `ir.rule` `company_id in company_ids or company_id = False`.
* **Source-record security (critical)**: `business.change.log._search` is overridden to AND a domain: for each tracked model the user may read, `res_id in Model._search([])` (SQL sub-select, respects the source model's record rules), deleted-record entries visible only to Managers. Models the user can't read at all are excluded.
* **Field-level**: at display compute, if `not Model._has_field_access(field, 'read')` for the viewer → values shown as "Restricted".

## 7. UI
* **Change History** action on every tracked model: each rule creates/removes an `ir.actions.server` bound to its model (`binding_model_id`), so it shows up in the record's ⚙ Action menu. No view inheritance is needed, so there's no hard dependency on sale/purchase/stock/account, and it works for custom models too.
* Record history: list view (Date, User, Field, Old → New), search filters, grouped by date.
* Menu **Change Tracker → Change History / Configuration → Tracking Rules / Settings**. "Open Record" button; deleted → "Record no longer exists."
* No custom OWL in V1.

## 8. Retention & performance
* Setting `bct.retention_days` (30/90/180/365/Forever, default Forever). Daily cron deletes in 10 000-row batches with `changed_at < now - N days`; never runs when Forever.
* Performance tests: 10k and 100k logs via batched create; verify query count of a tracked write is constant w.r.t. batch size.

## 9. Dependencies decision
`depends: ['base', 'mail']` only (mail for settings/UI conventions). Demo rules for sale/purchase/account/stock created only if those models exist (Python data hook, no hard dependency).

## 10. Risks
| Risk | Mitigation |
|---|---|
| Other modules calling `write` with huge vals on tracked models | Only configured fields snapshotted |
| Records that disappear during write (cascade) | `exists()` before post snapshot |
| Concurrent updates | Each transaction logs its own old/new as seen by its snapshot; documented |
| Uninstall deletes history | Documented; export recommended |
