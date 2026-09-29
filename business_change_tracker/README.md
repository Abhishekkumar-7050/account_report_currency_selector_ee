# Business Change Tracker (Odoo 19)

> "I see something different in Odoo. What changed, who changed it, when, and what was the previous value?"

Business Change Tracker keeps a **business-readable change history** for the documents you choose — sales orders and their lines, purchase orders, invoices, contacts, transfers or any other model — and answers that question in a few seconds.

```
Change History: S02451
Date              User         Field          Old Value          New Value
29/09/2026 11:42  John Smith   Unit Price     $ 5.00             $ 4.50
29/09/2026 11:35  Sarah Jones  Quantity       1,000.00           800.00
29/09/2026 09:20  John Smith   Delivery Date  10/10/2026 ...     10/20/2026 ...
29/09/2026 09:02  John Smith   Tags           VIP Customer       Added: Key Account
                                                                 Removed: VIP Customer
```

It is **not** a technical audit log. It does not record every write of every model: only the fields an administrator selected, rendered as users see them (names, labels, dates, amounts), never as database IDs.

## 1. Problem solved

Odoo's chatter tracking only covers fields that developers flagged with `tracking=True`, only on models with a chatter (not order lines), mixes changes with messages, and cannot be configured without code. Generic audit-log modules record everything technically. Managers need neither: they need a focused list of *business* changes with before/after values.

## 2. Features

* Tracking rules: choose a model and the fields to track, enable or disable at any time.
* Logs changes (old → new), creations and deletions, with user, date and company.
* Human-readable values: many2one names, selection labels, Yes/No, dates in the user's format, datetimes in the user's timezone, amounts with currency, tags "Added / Removed".
* **Change History** entry in the ⚙ Action menu of every tracked model (form and list).
* Line changes (e.g. order lines) are also listed on their parent document.
* Global **Change Tracker → Change History** with search, filters and grouping by model, record, field, user, operation, company and date.
* "Open Record" navigation; deleted records are clearly shown as "Record no longer exists."
* Security based on the tracked record's own access rights, record rules, companies and field groups.
* Immutable history (no edit, no delete) with an optional retention period.
* Suggested (disabled) rules for Sales, Purchase, Invoicing, Contacts and Inventory.

## 3. Installation

1. Copy `business_change_tracker` into your addons path.
2. Apps → Update Apps List → search "Business Change Tracker" → Install.

Dependencies: `base` only. Sales, Purchase, Accounting and Inventory are supported when installed, but never required.

## 4. Configuration

1. **Change Tracker → Configuration → Tracking Rules.** Suggested rules are created disabled at installation. Use Settings → *Load Suggested Rules* for apps installed later.
2. Open a rule, adjust the **Tracked Fields**, and switch **Enabled** on. The rule has these options:
   * **Log Creation** and **Log Deletion**: record a creation event and a deletion event, in addition to field changes.
   * **Show Changes On**: pick the parent field of a line model (for example `Order Reference` on sales order lines). The line's changes then also appear in the parent's Change History.
3. **Settings → Change Tracker → Retention** sets how long history is kept.

Only one rule per model is allowed. Technical models (`ir.*`, `bus.*`, wizards, abstract models and the tracker itself) cannot be tracked.

## 5. How tracking works

The module extends the ORM `create`, `write` and `unlink` methods of all models through standard inheritance (`_inherit = 'base'`). It does not monkey-patch anything and does not change Odoo source code.

* **Models without a rule:** tracking costs one lookup in an in-memory cache and no SQL.
* **Writes:**
  * The module reads the tracked fields present in the write values (and only those) in one batched fetch before the write, and again after it.
  * A log line is created only when the value really changed. Float fields use the field's own precision.
  * All lines are inserted in a single `create`.
* **Creations:** a "Created" event is logged after the record is created.
* **Deletions:** a "Deleted" event is logged *before* the record is deleted. It keeps the record's display name and parent document.
* **Transactions:** history is written in the same database transaction. If the business operation rolls back, its history rolls back too.
* **Cache:** rules are cached per registry and the cache is cleared for all workers whenever a rule changes. No server restart is needed.

### What is captured

| Source | Captured | Author recorded |
|---|---|---|
| Form / list view edits | ✅ | the user |
| Imports (`load`) | ✅ only rows whose value changed | the importing user |
| Server-side Python / ORM | ✅ | `env.user` |
| `sudo()` | ✅ | the real user (`sudo` keeps the uid) |
| Automated actions (base_automation) | ✅ | the user whose change triggered it |
| Scheduled actions | ✅ | the cron user (usually OdooBot) |
| Batch writes on many records | ✅ each record separately | |
| One2many edits from the parent form | ✅ on the line model if it has a rule | |

### What is NOT captured

* Direct SQL (`cr.execute("UPDATE ...")`), which bypasses the ORM.
* Non-stored computed fields (they are not values of the record). Such fields can't be selected in a rule.
* Stored computed fields recomputed because of a change on *another record*. For example, an order total recomputed after its lines change is not logged on the order; the line change itself is logged.

  Tracked computed fields recomputed because of a change on *the same record* **are** captured. For example, Payment Terms or Pricelist are reset when the customer of an order changes, and that reset appears in the history.
* Binary, one2many, properties, json and reference fields.
* Changes made while modules are being installed or upgraded (the registry is not ready), and code that explicitly passes the `bct_no_track` context key.
* Existing chatter tracking is unaffected and keeps working. Both mechanisms are independent.

## 6. Supported models

These models are pre-configured (disabled) when their apps are installed:

| Model | Suggested fields |
|---|---|
| Sales Order | Customer, Salesperson, Delivery Date, Payment Terms, Pricelist, Status |
| Sales Order Line | Product, Quantity, Unit Price, Discount, Unit (shown on the order) |
| Purchase Order | Vendor, Expected Arrival, Payment Terms, Currency, Status |
| Purchase Order Line | Product, Quantity, Unit Price, Expected Arrival (shown on the order) |
| Journal Entry / Invoice | Partner, Invoice Date, Due Date, Payment Terms, Reference, Status |
| Contact | Name, Email, Phone, Tax ID, Street, City, Country, Tags, Salesperson |
| Transfer | Contact, Scheduled Date, Source Document, Destination Location, Status |

Any other regular (stored) model can be configured the same way, including custom models.

### Tracked field types

| Type | Display |
|---|---|
| Char / Text | text (truncated at 2,000 characters) |
| HTML | converted to plain text (never rendered as HTML) |
| Integer | `1,000 → 800` in the viewer's number format |
| Float | the field's precision |
| Float prices (`Product Price` precision) | with the document currency, e.g. `$ 5.00 → $ 4.50` |
| Monetary | with its currency |
| Boolean | `No → Yes` |
| Date / Datetime | the viewer's date format and timezone |
| Selection | labels (`Quotation → Sales Order`) |
| Many2one | record names at the time of the change |
| Many2many | `Added: …` / `Removed: …` |

## 7. Security

| Group | Rights |
|---|---|
| Change Tracker / User | read the history of the records they can read; navigate to them |
| Change Tracker / Manager | the User rights, plus: manage tracking rules; see history of deleted records |
| Settings (system admin) | retention settings |

* A history line is visible only if the user can read the **source record** with Odoo's own access rights and record rules. For example, a salesperson restricted to "own documents" does not see the history of colleagues' orders. Line history is also visible through a readable parent document. This is enforced on search, grouping and direct reads, all in SQL.
* If a tracked field is restricted by `groups` and the viewer isn't in them, its values are displayed as **Restricted**.
* History of deleted records (whose access can no longer be evaluated) is visible to Managers only.
* **Immutable.** Nobody can create, edit or delete history entries from the UI or RPC, not even administrators. Superuser code that tries to modify an entry gets an error. The only deletion path is the retention job.

## 8. Multi-company

Each entry stores the company of the tracked record (`company_id` when the model has one). A standard record rule restricts entries to the user's allowed companies. Records without a company (for example shared contacts) are visible from every company, just as the records themselves are.

## 9. Retention

Choose 30, 90, 180 or 365 days, or Forever (the default), in Settings. The daily scheduled action "Change Tracker: delete expired change history" works like this:

* It does nothing when retention is Forever.
* It never deletes entries younger than 30 days, even if the setting was tampered with.
* It deletes in batches of 10,000, committing after each batch, and reports its progress to the cron.
* The cleanup itself leaves no entries in the history.

## 10. Performance

* Nothing is tracked by default, and untracked models do no extra work.
* A tracked write costs a constant number of queries, whatever the number of records: 2 batched fetches, 1 batched name lookup per related model, and 1 batched insert. The test suite checks that writing 200 records needs no more queries than writing 10.
* Indexes:
  * `(res_model, res_id, changed_at DESC)` for record history;
  * a partial `(parent_model, parent_res_id)` index for line changes on the parent;
  * `changed_at` for ordering and retention;
  * `user_id` for "who changed it".
  * No other indexes, to keep inserts cheap.
* Measured on the development machine (PostgreSQL 18) with 100,000 history entries:

  | Operation | Time |
  |---|---|
  | Record history page | 10 ms |
  | Global list page + count | 23 ms |
  | Filter by user | 20 ms |
  | Search by field label | 44 ms |

  Run `--test-tags bct_perf` to reproduce.
* Security sub-queries use the tracked models' own record rules. On databases with very complex record rules, the global list costs what reading those models costs.

## 11. Limitations

* See "What is NOT captured" above.
* Many2one/many2many names are **snapshots** in the language of the user who made the change. Dates, numbers and Yes/No are re-rendered in each viewer's language.
* Deleted records keep their name, parent and history, but they **cannot be reconstructed** or restored (there is no rollback in V1).
* Uninstalling the module **deletes all history** (its tables are dropped). Export it first if you need it.
* When two users update the same record concurrently, each entry reflects the values seen by that user's own transaction.
* "Change History" is available from the ⚙ Action menu. No button is injected into business forms, which keeps the module independent of the Sales, Purchase, Inventory and Accounting views.

## 12. Testing

Automated tests (Odoo test framework) cover installation, rules, all field types, create/write/unlink, multi-record writes, imports, automated and scheduled actions, `sudo`, rollback, multi-company, record rules, restricted fields, immutability, retention, navigation, search and performance. The business-model tests run when Sales, Purchase, Accounting and Inventory are installed:

```
odoo -d <db> -u business_change_tracker --test-tags /business_change_tracker --stop-after-init
odoo -d <db> --test-tags bct_perf --stop-after-init        # optional 100k entries benchmark
```

The design rationale is in [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md).

Acceptance testing was done on Odoo 19.0 with Sales, Purchase, Inventory and Invoicing installed:
* 35 end-to-end scenarios through the web client's HTTP API, with 5 users of different rights and 2 companies;
* a real-browser check of every screen (no JavaScript errors);
* Odoo's own Sales and Purchase test suites (441 tests) run with every rule enabled. The only error there also occurs with the rules disabled.

## 13. Roadmap

* V2: **important change rules**, e.g. "price decreased by more than 10 %", "delivery date moved later", "vendor changed after confirmation". The `is_important` flag and the typed raw values are already stored for this.
* Change reasons (optional comment required for selected fields).
* Change alerts (notifications on important changes).
* Optional smart buttons for Sales, Purchase and Inventory through small bridge modules.
* Export of the history of a record to PDF.
