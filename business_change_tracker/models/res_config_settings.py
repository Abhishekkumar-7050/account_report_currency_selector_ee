from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bct_retention_days = fields.Selection(
        [('30', '30 days'), ('90', '90 days'), ('180', '180 days'), ('365', '365 days'), ('0', 'Forever')],
        string='Keep Change History',
        config_parameter='business_change_tracker.retention_days',
        default='0',
        help="Older change history is deleted by a daily scheduled action. "
             "'Forever' never deletes anything.")

    def action_bct_load_presets(self):
        created = self.env['business.change.rule'].action_load_presets()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if created else 'info',
                'message': self.env._("%s suggested rule(s) created (disabled).", created) if created
                else self.env._("All suggested rules already exist."),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
