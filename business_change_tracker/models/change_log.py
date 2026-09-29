from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.tools import format_amount, format_date, format_datetime, formatLang, html2plaintext

from .base import NO_TRACK

MAX_TEXT_LENGTH = 2000
EMPTY = '—'
RETENTION_PARAM = 'business_change_tracker.retention_days'
# Never purge anything younger than this, whatever the configuration says.
MIN_RETENTION_DAYS = 30
PURGE_BATCH_SIZE = 10000


def _truncate(text):
    text = (text or '').strip()
    if len(text) > MAX_TEXT_LENGTH:
        return text[:MAX_TEXT_LENGTH] + '…'
    return text


class BusinessChangeLog(models.Model):
    _name = 'business.change.log'
    _description = 'Business Change History'
    _order = 'changed_at desc, id desc'
    _rec_name = 'record_name'

    # Record-level history is the hot path (open a document → its history).
    _record_history_idx = models.Index('(res_model, res_id, changed_at DESC)')
    # Line changes listed on their parent document.
    _parent_history_idx = models.Index('(parent_model, parent_res_id) WHERE parent_res_id IS NOT NULL')

    # What / which record. res_model is a char (not only a m2o) so history
    # survives the uninstallation of the tracked model.
    res_model = fields.Char('Technical Model', required=True, readonly=True)
    res_id = fields.Many2oneReference('Record ID', model_field='res_model', readonly=True)
    model_id = fields.Many2one('ir.model', 'Model', ondelete='set null', readonly=True)
    record_name = fields.Char('Record', readonly=True)
    parent_model = fields.Char(readonly=True)
    parent_res_id = fields.Many2oneReference('Parent ID', model_field='parent_model', readonly=True)
    parent_name = fields.Char('Document', readonly=True)
    operation = fields.Selection(
        [('create', 'Created'), ('write', 'Changed'), ('unlink', 'Deleted')],
        required=True, readonly=True)

    # Which field. Labels are snapshots so history stays readable if the field disappears.
    field_id = fields.Many2one('ir.model.fields', 'Field Definition', ondelete='set null', readonly=True)
    field_name = fields.Char('Technical Field', readonly=True)
    field_label = fields.Char('Field', readonly=True)
    field_type = fields.Char(readonly=True)

    # Before / after. *_text: business rendering captured at change time (names,
    # labels); *_raw: typed value, re-rendered in the viewer's language/timezone
    # and kept for future business rules (e.g. "price decreased by more than 10%").
    old_value_text = fields.Text(readonly=True)
    new_value_text = fields.Text(readonly=True)
    old_value_raw = fields.Json(readonly=True)
    new_value_raw = fields.Json(readonly=True)
    currency_id = fields.Many2one('res.currency', ondelete='set null', readonly=True)
    old_value = fields.Text('Old Value', compute='_compute_display_values')
    new_value = fields.Text('New Value', compute='_compute_display_values')
    is_restricted = fields.Boolean(compute='_compute_display_values')

    # Who / when / where.
    user_id = fields.Many2one('res.users', 'Changed By', ondelete='set null', readonly=True, index=True)
    user_name = fields.Char('User Name', readonly=True)
    changed_at = fields.Datetime('Changed On', required=True, readonly=True, index=True)
    company_id = fields.Many2one('res.company', 'Company', ondelete='restrict', readonly=True)

    # Reserved for V2 "important change" rules; not computed in V1.
    is_important = fields.Boolean('Important', readonly=True)

    record_exists = fields.Boolean(compute='_compute_record_exists')

    # ------------------------------------------------------------------
    # Creation (engine only) and serialization
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        self.browse().check_access('create')
        if not self.env.context.get('bct_engine'):
            raise UserError(_("Change history entries are generated automatically and cannot be created manually."))
        return super().create(vals_list)

    @api.model
    def _bct_create(self, vals_list):
        if vals_list:
            # sudo: the author of a business change never has (nor needs) write
            # access to the history; entries are created on their behalf.
            self.sudo().with_context(bct_engine=True, **{NO_TRACK: True}).create(vals_list)

    @api.model
    def _bct_prepare_field_values(self, changes, config, common):
        """ Turn (record, field, old, new) tuples into log values, resolving all
        relational names with one query per comodel. """
        names = self._bct_resolve_names(changes)
        vals_list = []
        for record, field, old, new in changes:
            vals = dict(common[record.id])
            vals.update({
                'field_id': config['fields'].get(field.name),
                'field_name': field.name,
                'field_label': field._description_string(self.env),
                'field_type': field.type,
            })
            vals.update(self._bct_serialize(record, field, old, new, names))
            vals_list.append(vals)
        return vals_list

    @api.model
    def _bct_resolve_names(self, changes):
        ids_by_model = {}
        for _record, field, old, new in changes:
            if field.type == 'many2one':
                ids_by_model.setdefault(field.comodel_name, set()).update(v for v in (old, new) if v)
            elif field.type == 'many2many':
                ids_by_model.setdefault(field.comodel_name, set()).update(old + new)
        names = {}
        for model_name, ids in ids_by_model.items():
            # sudo: the display name is part of the captured evidence; reading
            # it is guarded later by the log's own access rules
            targets = self.env[model_name].sudo().with_context(active_test=False).browse(ids).exists()
            names[model_name] = {target.id: target.display_name for target in targets}
        return names

    @api.model
    def _bct_serialize(self, record, field, old, new, names):
        ftype = field.type
        vals = {'old_value_raw': None, 'new_value_raw': None, 'old_value_text': False, 'new_value_text': False}
        if ftype == 'many2one':
            comodel_names = names.get(field.comodel_name, {})
            vals.update({
                'old_value_raw': old or None,
                'new_value_raw': new or None,
                'old_value_text': comodel_names.get(old, f"#{old}") if old else False,
                'new_value_text': comodel_names.get(new, f"#{new}") if new else False,
            })
        elif ftype == 'many2many':
            comodel_names = names.get(field.comodel_name, {})
            label = lambda ids: ', '.join(comodel_names.get(i, f"#{i}") for i in ids)  # noqa: E731
            added = [i for i in new if i not in old]
            removed = [i for i in old if i not in new]
            summary = []
            if added:
                summary.append(_("Added: %s", label(added)))
            if removed:
                summary.append(_("Removed: %s", label(removed)))
            vals.update({
                'old_value_raw': list(old),
                'new_value_raw': list(new),
                'old_value_text': label(old) or False,
                'new_value_text': '\n'.join(summary),
            })
        elif ftype == 'selection':
            labels = dict(field._description_selection(self.env))
            vals.update({
                'old_value_raw': old or None,
                'new_value_raw': new or None,
                'old_value_text': labels.get(old, old) if old else False,
                'new_value_text': labels.get(new, new) if new else False,
            })
        elif ftype in ('char', 'text'):
            vals.update({'old_value_text': _truncate(old) or False, 'new_value_text': _truncate(new) or False})
        elif ftype == 'html':
            # stored as plain text: history is never rendered as HTML (no XSS surface)
            vals.update({
                'old_value_text': _truncate(html2plaintext(old)) if old else False,
                'new_value_text': _truncate(html2plaintext(new)) if new else False,
            })
        elif ftype in ('date', 'datetime'):
            vals.update({
                'old_value_raw': fields.Datetime.to_string(old) if ftype == 'datetime' else fields.Date.to_string(old),
                'new_value_raw': fields.Datetime.to_string(new) if ftype == 'datetime' else fields.Date.to_string(new),
            })
        elif ftype == 'boolean':
            vals.update({'old_value_raw': bool(old), 'new_value_raw': bool(new)})
        else:  # integer, float, monetary
            vals.update({'old_value_raw': old, 'new_value_raw': new})
            currency = self._bct_get_currency(record, field)
            if currency:
                vals['currency_id'] = currency.id
        return vals

    @api.model
    def _bct_get_currency(self, record, field):
        """ Currency used to display an amount. Monetary fields declare it; plain
        float prices (e.g. order line "Unit Price", digits 'Product Price') are
        displayed with the document currency because that is how users read them. """
        if field.type == 'monetary':
            currency_field = field.currency_field
            return record.sudo()[currency_field] if currency_field in record._fields else None
        if field.type == 'float' and isinstance(field._digits, str) and 'price' in field._digits.lower():
            currency_field = record._fields.get('currency_id')
            if currency_field is not None and currency_field.comodel_name == 'res.currency':
                return record.sudo().currency_id
        return None

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    @api.depends('old_value_raw', 'new_value_raw', 'old_value_text', 'new_value_text', 'field_type')
    @api.depends_context('lang', 'tz', 'uid')
    def _compute_display_values(self):
        tz = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        for log in self:
            if log.operation != 'write':
                log.old_value = log.new_value = False
                log.is_restricted = False
                continue
            model = self.env.get(log.res_model)
            field = model._fields.get(log.field_name) if model is not None else None
            if field is not None and not model._has_field_access(field, 'read'):
                log.old_value = log.new_value = _("Restricted")
                log.is_restricted = True
                continue
            log.is_restricted = False
            log.old_value = log._bct_format(log.old_value_raw, log.old_value_text, field, tz)
            log.new_value = log._bct_format(log.new_value_raw, log.new_value_text, field, tz)

    def _bct_format(self, raw, text, field, tz):
        ftype = self.field_type
        if ftype == 'boolean':
            return _("Yes") if raw else _("No")
        if ftype in ('many2one', 'many2many', 'selection', 'char', 'text', 'html'):
            return text or EMPTY
        if ftype in ('integer', 'float', 'monetary'):
            # a Json column stores 0 as NULL, and numeric fields have no "empty" value
            raw = raw or 0
        elif raw is None or raw is False:
            return EMPTY
        if ftype == 'date':
            return format_date(self.env, raw)
        if ftype == 'datetime':
            return format_datetime(self.env, raw, tz=tz)
        if ftype == 'integer':
            return formatLang(self.env, raw, digits=0)
        if self.currency_id:
            return format_amount(self.env, raw, self.currency_id)
        digits = field.get_digits(self.env) if field is not None and ftype == 'float' else None
        if digits:
            precision = digits[1]
        else:
            # no declared precision: keep the meaningful decimals of the value
            precision = len(f'{float(raw):.6f}'.rstrip('0').split('.')[1])
        return formatLang(self.env, raw, digits=precision)

    def _compute_record_exists(self):
        existing = {}
        for model_name in set(self.mapped('res_model')):
            model = self.env.get(model_name)
            ids = self.filtered(lambda log: log.res_model == model_name).mapped('res_id')
            if model is None:
                existing[model_name] = set()
            else:
                existing[model_name] = set(model.sudo().with_context(active_test=False).browse(ids).exists().ids)
        for log in self:
            log.record_exists = log.res_id in existing[log.res_model]

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @api.model
    def action_open_history(self, model_name, record_ids):
        """ Change History of given records, including changes of their lines. """
        action = self.env['ir.actions.act_window']._for_xml_id('business_change_tracker.action_business_change_log_record')
        action['domain'] = [
            '|',
            '&', ('res_model', '=', model_name), ('res_id', 'in', record_ids),
            '&', ('parent_model', '=', model_name), ('parent_res_id', 'in', record_ids),
        ]
        if len(record_ids) == 1:
            record = self.env[model_name].browse(record_ids)
            action['name'] = _("Change History: %s", record.display_name)
        return action

    def action_open_record(self):
        self.ensure_one()
        if not self.record_exists:
            raise UserError(_("Record no longer exists."))
        record = self.env[self.res_model].browse(self.res_id)
        # raises the standard AccessError when the user may not open it
        record.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'views': [(False, 'form')],
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Security: a log is visible only if its source record is
    # ------------------------------------------------------------------

    @api.model
    def _bct_access_domain(self):
        """ Domain restricting logs to records the current user can read in their
        own model (ACL + record rules), evaluated in SQL through sub-queries.

        Line logs are also visible through a readable parent document. Logs of
        deleted records (and of models without rule / uninstalled) are only
        visible to tracker managers, since the source security can no longer be
        evaluated.
        """
        is_manager = self.env.user.has_group('business_change_tracker.group_business_change_manager')
        rule_models = [name for name in self.env['business.change.rule']._get_rule_model_names() if name in self.env]
        clauses = []
        for model_name in rule_models:
            model = self.env[model_name].with_context(active_test=False)
            if not model.has_access('read'):
                continue
            readable = model._search([])
            visible = Domain('res_id', 'in', readable)
            if is_manager:
                visible |= Domain('res_id', 'not in', model.sudo()._search([]))
            clauses.append(Domain('res_model', '=', model_name) & visible)
            clauses.append(Domain('parent_model', '=', model_name) & Domain('parent_res_id', 'in', readable))
        if is_manager:
            clauses.append(Domain('res_model', 'not in', rule_models))
        return Domain.OR(clauses)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        if not self.env.su and not bypass_access:
            domain = Domain(domain) & self._bct_access_domain()
        return super()._search(domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)

    def _check_access(self, operation):
        result = super()._check_access(operation)
        if result or operation != 'read' or self.env.su or not any(self._ids):
            return result
        forbidden = self - self.search([('id', 'in', self.ids)])
        if forbidden:
            return forbidden, lambda: AccessError(_("You are not allowed to see the change history of this record."))
        return None

    # ------------------------------------------------------------------
    # Immutability and retention
    # ------------------------------------------------------------------

    def write(self, vals):
        # standard AccessError first for regular users, then refuse even superuser code
        self.check_access('write')
        raise UserError(_("Change history is audit evidence and cannot be modified."))

    def unlink(self):
        self.check_access('unlink')
        if not (self.env.su and self.env.context.get('bct_retention_cleanup')):
            raise UserError(_("Change history cannot be deleted. Configure a retention period instead."))
        return super().unlink()

    @api.model
    def _bct_get_retention_cutoff(self):
        days = int(self.env['ir.config_parameter'].sudo().get_param(RETENTION_PARAM) or 0)
        if days <= 0:
            return None  # keep forever
        return fields.Datetime.now() - timedelta(days=max(days, MIN_RETENTION_DAYS))

    @api.model
    def _bct_purge_batch(self, cutoff, batch_size=PURGE_BATCH_SIZE):
        """ Delete one batch of logs older than ``cutoff``; return how many were deleted. """
        logs = self.sudo().search([('changed_at', '<', cutoff)], limit=batch_size, order='id')
        count = len(logs)
        logs.with_context(bct_retention_cleanup=True).unlink()
        return count

    @api.model
    def _cron_retention_cleanup(self):
        cutoff = self._bct_get_retention_cutoff()
        if cutoff is None:
            return
        while True:
            count = self._bct_purge_batch(cutoff)
            if not count:
                break
            remaining = self.sudo().search_count([('changed_at', '<', cutoff)])
            if not self.env['ir.cron']._commit_progress(count, remaining=remaining) or not remaining:
                break
