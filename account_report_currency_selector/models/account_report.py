
from odoo import models, fields, api, _

class AccountReport(models.Model):
    _inherit = 'account.report'

    def _get_options_initializers_forced_sequence_map(self):
        res = super()._get_options_initializers_forced_sequence_map()
        res[self._init_options_custom_currency] = 1040
        return res

    def _init_options_custom_currency(self, options, previous_options=None):
        default_currency_id = self.env.company.currency_id.id
        selected_currency_id = (previous_options or {}).get('custom_currency_id') or default_currency_id
        
        options['custom_currency_id'] = int(selected_currency_id)

        currencies = self.env['res.currency'].search([('active', '=', True)], order="name ASC")
        options['available_currencies'] = [
            {'id': c.id, 'name': c.name, 'selected': c.id == options['custom_currency_id']}
            for c in currencies
        ]
        
        custom_currency_id = options.get('custom_currency_id')
        if custom_currency_id and custom_currency_id != self.env.company.currency_id.id:
            options['multi_currency'] = True

    def _get_lines(self, options, all_column_groups_expression_totals=None):
        lines = super()._get_lines(options, all_column_groups_expression_totals)

        target_currency_id = options.get('custom_currency_id')
        company_currency = self.env.company.currency_id

        if target_currency_id and target_currency_id != company_currency.id:
            target_currency = self.env['res.currency'].browse(target_currency_id)
            date_to = fields.Date.context_today(self)
            if options.get('date') and options['date'].get('date_to'):
                date_to = fields.Date.from_string(options['date']['date_to'])

            for line in lines:
                for i, col in enumerate(line.get('columns', [])):
                    if 'no_format' in col and isinstance(col['no_format'], (int, float)):
                        col_data = options['columns'][i] if i < len(options.get('columns', [])) else {}
                        
                        is_monetary = False
                        if col_data.get('figure_type') == 'monetary':
                            is_monetary = True
                        elif company_currency.symbol and company_currency.symbol in col.get('name', ''):
                            is_monetary = True
                        elif company_currency.name and company_currency.name in col.get('name', ''):
                            is_monetary = True
                            
                        if is_monetary:
                            original_value = col['no_format']
                            converted = company_currency._convert(
                                original_value, target_currency, self.env.company, date_to
                            )
                            col['no_format'] = converted
                            
                            blank_if_zero = (col.get('name') == '')
                            
                            col['name'] = self.format_value(
                                converted,
                                figure_type='monetary',
                                blank_if_zero=blank_if_zero,
                                currency=target_currency
                            )
                            
                            if hasattr(self, 'is_zero'):
                                col['is_zero'] = self.is_zero(converted, figure_type='monetary', currency=target_currency)
                            else:
                                col['is_zero'] = (converted == 0)

        return lines

