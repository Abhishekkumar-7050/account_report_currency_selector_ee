from odoo import api, fields, models
from odoo.tools import float_compare

# Context key set while the tracker writes its own records, and usable by
# callers to deliberately skip tracking (e.g. data migrations).
NO_TRACK = 'bct_no_track'


class Base(models.AbstractModel):
    """ Generic change capture.

    Implemented as a regular ``_inherit = 'base'`` extension instead of patching
    classes at registry setup (as base_automation / auditlog do): the override
    is removed cleanly on uninstall, needs no registry reload when rules change,
    and sits at the bottom of every model's MRO, so it sees the final values
    actually written by business overrides.
    """
    _inherit = 'base'

    def _bct_config(self):
        """ Return the tracking config of this model, or None. Must stay cheap:
        it runs on every create/write/unlink of every model. """
        if self.env.context.get(NO_TRACK):
            return None
        registry = self.env.registry
        # During module loading tables may not exist yet and data files would
        # flood the history with install noise.
        if not registry.ready or 'business.change.rule' not in registry:
            return None
        return self.env['business.change.rule']._get_tracking_map().get(self._name)

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        config = records._bct_config() if records else None
        if config and config['create']:
            records._bct_log_events(config, 'create')
        return records

    def write(self, vals):
        config = self._bct_config() if self else None
        fnames = [
            fname for fname in config['fields']
            if fname in vals or not config['computed'].get(fname, frozenset()).isdisjoint(vals)
        ] if config else None
        if not fnames:
            return super().write(vals)
        records = self.filtered('id')
        before = records._bct_snapshot(fnames)
        res = super().write(vals)
        after = records._bct_snapshot(fnames)
        records._bct_log_changes(config, fnames, before, after)
        return res

    def unlink(self):
        config = self._bct_config() if self else None
        if config and config['unlink']:
            # logged before deletion: afterwards neither the name nor the parent can be read
            self._bct_log_events(config, 'unlink')
        return super().unlink()

    # ------------------------------------------------------------------
    # Capture helpers
    # ------------------------------------------------------------------

    def _bct_snapshot(self, fnames):
        """ Return {record_id: {fname: normalized value}} with a single batched fetch
        of only the tracked fields. sudo: the history must reflect the real value
        even if the writer cannot read every tracked field; visibility is enforced
        when the log is read. """
        records = self.sudo().with_context(active_test=False)
        records.fetch(fnames)
        snapshot = {}
        for record in records:
            values = {}
            for fname in fnames:
                field = self._fields[fname]
                value = record[fname]
                if field.type == 'many2one':
                    value = value.id
                elif field.type == 'many2many':
                    value = tuple(sorted(value.ids))
                values[fname] = value
            snapshot[record.id] = values
        return snapshot

    def _bct_is_equal(self, field, old, new):
        if field.type == 'float':
            digits = field.get_digits(self.env)
            if digits:
                return float_compare(old or 0.0, new or 0.0, precision_digits=digits[1]) == 0
        if field.type == 'monetary':
            # the currency rounding is not known here; ignore float noise only
            return float_compare(old or 0.0, new or 0.0, precision_digits=6) == 0
        if field.type in ('char', 'text', 'html', 'selection', 'many2one', 'date', 'datetime'):
            # an empty string and False/None mean the same thing to a user
            return (old or False) == (new or False)
        return old == new

    def _bct_common_vals(self, config, operation):
        """ Values shared by all log lines of each record, computed in batch. """
        records = self.sudo().with_context(active_test=False)
        parent_fname = config['parent']
        company_field = self._fields.get('company_id')
        has_company = company_field is not None and company_field.type == 'many2one' \
            and company_field.comodel_name == 'res.company'
        user = self.env.user
        now = fields.Datetime.now()
        result = {}
        for record in records:
            vals = {
                'res_model': self._name,
                'res_id': record.id,
                'model_id': config['model_id'],
                'record_name': (record.display_name or '')[:250],
                'operation': operation,
                'user_id': user.id,
                'user_name': user.name,
                'changed_at': now,
                'company_id': record.company_id.id if has_company else False,
            }
            if parent_fname:
                parent = record[parent_fname]
                if parent:
                    vals.update({
                        'parent_model': parent._name,
                        'parent_res_id': parent.id,
                        'parent_name': (parent.display_name or '')[:250],
                    })
            result[record.id] = vals
        return result

    def _bct_log_events(self, config, operation):
        records = self.filtered('id')
        common = records._bct_common_vals(config, operation)
        records.env['business.change.log']._bct_create(list(common.values()))

    def _bct_log_changes(self, config, fnames, before, after):
        Log = self.env['business.change.log']
        changes = []
        for record in self:
            old_values, new_values = before.get(record.id), after.get(record.id)
            if old_values is None or new_values is None:
                continue
            for fname in fnames:
                field = self._fields[fname]
                if not self._bct_is_equal(field, old_values[fname], new_values[fname]):
                    changes.append((record, field, old_values[fname], new_values[fname]))
        if not changes:
            return
        records = self.browse(list(dict.fromkeys(record.id for record, *_dummy in changes)))
        common = records._bct_common_vals(config, 'write')
        vals_list = Log._bct_prepare_field_values(changes, config, common)
        Log._bct_create(vals_list)
