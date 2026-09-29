from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError

# Field types whose values can be captured and rendered safely. One2many,
# binary, properties, json and reference fields are excluded on purpose: they
# are either not persistent values of the record itself, too large, or have
# no reliable business rendering.
TRACKABLE_FIELD_TYPES = (
    'char', 'text', 'html', 'integer', 'float', 'monetary', 'boolean',
    'date', 'datetime', 'selection', 'many2one', 'many2many',
)

# Technical models that must never be tracked: tracking them would either
# recurse into the tracker itself or produce pure technical noise.
EXCLUDED_MODEL_PREFIXES = ('ir.', 'bus.', 'base.', 'business.change.', 'res.config', 'mail.tracking.')


def is_model_trackable(model):
    """ Return whether the given model (recordset) may be tracked at all. """
    return not (
        model._transient
        or model._abstract
        or not model._auto
        or model._name.startswith(EXCLUDED_MODEL_PREFIXES)
    )


class BusinessChangeRule(models.Model):
    _name = 'business.change.rule'
    _description = 'Business Change Tracking Rule'
    _order = 'model_name, id'

    name = fields.Char(compute='_compute_name', store=True, readonly=False, required=True)
    active = fields.Boolean(default=True, help="Only enabled rules generate change history.")
    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, ondelete='cascade',
        domain=[('transient', '=', False), ('abstract', '=', False)])
    model_name = fields.Char(related='model_id.model', store=True, index=True, string='Technical Model')
    field_ids = fields.Many2many(
        'ir.model.fields', 'business_change_rule_field_rel', 'rule_id', 'field_id',
        string='Tracked Fields',
        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', %s)]" % (list(TRACKABLE_FIELD_TYPES),))
    track_create = fields.Boolean('Log Creation', default=True)
    track_unlink = fields.Boolean('Log Deletion', default=True)
    parent_field_id = fields.Many2one(
        'ir.model.fields', string='Show Changes On',
        ondelete='set null',
        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', '=', 'many2one')]",
        help="Optional parent document (e.g. the Order of an order line). Changes of this record "
             "are then also listed in the parent's Change History.")
    action_id = fields.Many2one('ir.actions.server', readonly=True, ondelete='set null', copy=False)
    field_summary = fields.Char('Tracked Fields', compute='_compute_field_summary')
    log_count = fields.Integer(compute='_compute_log_count')

    _model_uniq = models.Constraint('UNIQUE(model_id)', 'Only one tracking rule per model is allowed.')

    @api.depends('model_id')
    def _compute_name(self):
        for rule in self:
            rule.name = rule.model_id.name or rule.name

    @api.depends('field_ids')
    def _compute_field_summary(self):
        # many2many tags on ir.model.fields repeat the model name on every tag
        for rule in self:
            rule.field_summary = ', '.join(sorted(rule.field_ids.mapped('field_description')))

    def _compute_log_count(self):
        groups = self.env['business.change.log']._read_group(
            [('res_model', 'in', self.mapped('model_name'))], ['res_model'], ['__count'])
        counts = {model: count for model, count in groups}
        for rule in self:
            rule.log_count = counts.get(rule.model_name, 0)

    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.field_ids = self.field_ids.filtered(lambda f: f.model_id == self.model_id)
        if self.parent_field_id.model_id != self.model_id:
            self.parent_field_id = False

    @api.constrains('model_id', 'field_ids', 'parent_field_id')
    def _check_configuration(self):
        for rule in self:
            model = self.env.get(rule.model_name)
            if model is None or not is_model_trackable(model):
                raise ValidationError(_("The model “%s” cannot be tracked.", rule.model_id.name))
            for field in rule.field_ids:
                if field.model_id != rule.model_id:
                    raise ValidationError(_("The field “%(field)s” does not belong to the model “%(model)s”.",
                                            field=field.field_description, model=rule.model_id.name))
                orm_field = model._fields.get(field.name)
                if not orm_field or not orm_field.store or field.ttype not in TRACKABLE_FIELD_TYPES:
                    raise ValidationError(_("The field “%s” cannot be tracked: only stored fields of "
                                            "supported types are allowed.", field.field_description))
            if rule.parent_field_id and (rule.parent_field_id.model_id != rule.model_id
                                         or rule.parent_field_id.ttype != 'many2one'):
                raise ValidationError(_("“Show Changes On” must be a many2one field of the tracked model."))

    # ------------------------------------------------------------------
    # CRUD: keep the cached tracking map and the bound action in sync
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') and vals.get('model_id'):
                vals['name'] = self.env['ir.model'].browse(vals['model_id']).name
        rules = super().create(vals_list)
        rules._sync_history_action()
        self.env.registry.clear_cache()
        return rules

    def write(self, vals):
        res = super().write(vals)
        if {'model_id', 'active'} & vals.keys():
            self._sync_history_action()
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        # sudo: the bound server action is technical data owned by the rule
        self.action_id.sudo().unlink()
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _sync_history_action(self):
        """ Bind a "Change History" entry in the Action menu of the tracked model. """
        user_group = self.env.ref('business_change_tracker.group_business_change_user')
        for rule in self:
            vals = {
                'name': _("Change History"),
                'model_id': rule.model_id.id,
                'binding_model_id': rule.model_id.id if rule.active else False,
                'binding_view_types': 'form,list',
                'state': 'code',
                'group_ids': [(6, 0, user_group.ids)],
                # model name is inlined because safe_eval gives no clean access to records._name
                'code': "action = env['business.change.log'].action_open_history(%r, records.ids)" % rule.model_name,
            }
            # sudo: ir.actions.server is only writable by system administrators,
            # tracker managers must still be able to publish the history action
            if rule.action_id:
                rule.action_id.sudo().write(vals)
            else:
                rule.action_id = self.env['ir.actions.server'].sudo().create(vals)

    # ------------------------------------------------------------------
    # Tracking map used by the engine
    # ------------------------------------------------------------------

    @api.model
    @tools.ormcache()
    def _get_tracking_map(self):
        """ Return {model_name: config} for all active rules.

        Cached in the registry and invalidated (for all workers) whenever a rule
        changes, so the ORM hot path costs a single dict lookup. The returned
        structure is shared: callers must not mutate it.
        """
        result = {}
        rules = self.sudo().with_context(active_test=True).search([])
        for rule in rules:
            model = self.env.get(rule.model_name)
            if model is None or not is_model_trackable(model):
                continue
            tracked = {}
            computed = {}
            for field in rule.field_ids:
                orm_field = model._fields.get(field.name)
                if orm_field and orm_field.store and orm_field.type in TRACKABLE_FIELD_TYPES:
                    tracked[field.name] = field.id
                    if orm_field.compute:
                        # e.g. payment terms recomputed when the customer changes:
                        # a silent business change that must appear in the history
                        depends = self.env.registry.field_depends.get(orm_field, ())
                        computed[field.name] = frozenset(path.split('.')[0] for path in depends)
            parent = rule.parent_field_id.name
            if parent and model._fields.get(parent, None) is None:
                parent = False
            result[rule.model_name] = {
                'model_id': rule.model_id.id,
                'fields': tracked,
                'computed': computed,
                'create': rule.track_create,
                'unlink': rule.track_unlink,
                'parent': parent or False,
            }
        return result

    @api.model
    @tools.ormcache()
    def _get_rule_model_names(self):
        """ All models having a rule, including disabled ones (used for log security). """
        rules = self.sudo().with_context(active_test=False).search([])
        return tuple(sorted(set(rules.mapped('model_name'))))

    def action_view_logs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('business_change_tracker.action_business_change_log')
        action['domain'] = [('res_model', '=', self.model_name)]
        return action

    @api.model
    def action_load_presets(self):
        """ Create the suggested (disabled) rules for business apps installed since. """
        from ..hooks import PRESETS  # noqa: PLC0415 - hooks is a leaf module, avoids duplicating the presets
        return self._bct_create_presets(PRESETS)

    @api.model
    def _bct_create_presets(self, presets):
        """ Create disabled rules for the preset models installed in this database;
        return how many were created. """
        created = 0
        IrModel = self.env['ir.model']
        existing = set(self.with_context(active_test=False).search([]).mapped('model_name'))
        for model_name, (fnames, parent) in presets.items():
            if model_name not in self.env or model_name in existing:
                continue
            model = IrModel._get(model_name)
            fields_ = self.env['ir.model.fields'].search([
                ('model_id', '=', model.id), ('name', 'in', fnames),
                ('store', '=', True), ('ttype', 'in', TRACKABLE_FIELD_TYPES)])
            parent_field = parent and self.env['ir.model.fields']._get(model_name, parent)
            self.create({
                'model_id': model.id,
                'active': False,
                'field_ids': [(6, 0, fields_.ids)],
                'parent_field_id': parent_field.id if parent_field else False,
            })
            created += 1
        return created
