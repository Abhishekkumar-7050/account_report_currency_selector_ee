
from odoo import models, fields, api, _

class AccountReport(models.Model):
    _inherit = 'account.report'

    def _init_options_custom_currency(self, options, previous_options=None):
        default_currency_id = self.env.company.currency_id.id
        selected_currency_id = (previous_options or {}).get('custom_currency_id') or default_currency_id
        
        options['custom_currency_id'] = int(selected_currency_id)

        currencies = self.env['res.currency'].search([('active', '=', True)], order="name ASC")
        options['available_currencies'] = [
            {'id': c.id, 'name': c.name, 'selected': c.id == options['custom_currency_id']}
            for c in currencies
        ]

    def _init_options_multi_currency(self, options, previous_options=None):
        """
        OVERRIDE: Standard Odoo resets multi_currency to False if companies share the same currency.
        We must force it to True if a custom currency is selected, otherwise symbols won't render.
        """
        super()._init_options_multi_currency(options, previous_options)
        
        custom_currency_id = options.get('custom_currency_id')
        if custom_currency_id and custom_currency_id != self.env.company.currency_id.id:
            options['multi_currency'] = True

    def _build_column_dict(self, col_value, col_data, options=None, currency=False, digits=1, column_expression=None, has_sublines=False, report_line_id=None):
        target_currency_id = (options or {}).get('custom_currency_id')
        company_currency = self.env.company.currency_id

        local_options = options.copy() if options else {}

        if target_currency_id and target_currency_id != company_currency.id:
            local_options['multi_currency'] = True
            
            if col_value is not None and isinstance(col_value, (float, int)):
                target_currency = self.env['res.currency'].browse(target_currency_id)
                from_currency = currency or company_currency

                if from_currency != target_currency:
                    date_to = fields.Date.context_today(self)
                    if options.get('date') and options['date'].get('date_to'):
                        date_to = fields.Date.from_string(options['date']['date_to'])

                    col_value = from_currency._convert(
                        col_value, target_currency, self.env.company, date_to
                    )
                    currency = target_currency


        res = super()._build_column_dict(
            col_value, col_data, local_options, currency, digits, column_expression, has_sublines, report_line_id
        )

        if target_currency_id and target_currency_id != company_currency.id:
            if res.get("figure_type") == "monetary":
                target_currency = self.env['res.currency'].browse(target_currency_id)
                
                if 'format_params' not in res:
                    res['format_params'] = {}

                res["format_params"]["currency_id"] = target_currency.id
                res["currency_symbol"] = target_currency.symbol

        return res

