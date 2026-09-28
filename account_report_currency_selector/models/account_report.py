# -*- coding: utf-8 -*-
from odoo import models

from odoo.addons.account_reports.utils.report_data_objects import AccountReportColumnFormatParamsData


class AccountReport(models.Model):
    _inherit = "account.report"

    def _get_custom_currency(self, options):
        """ Return the currency selected in the report options, or an empty
        recordset when the report is displayed in the company currency.
        """
        currency_id = (options or {}).get("custom_currency_id")
        if not currency_id or currency_id == self.env.company.currency_id.id:
            return self.env["res.currency"]
        return self.env["res.currency"].browse(currency_id).exists()

    def _init_options_custom_currency(self, options, previous_options):
        currencies = self.env["res.currency"].search([("active", "=", True)], order="name")
        options["available_currencies"] = [{"id": c.id, "name": c.name} for c in currencies]

        currency_id = (previous_options or {}).get("custom_currency_id")
        if currency_id and int(currency_id) in currencies.ids:
            options["custom_currency_id"] = int(currency_id)
        else:
            options["custom_currency_id"] = self.env.company.currency_id.id
        options["selected_currency_name"] = self.env["res.currency"].browse(options["custom_currency_id"]).name

    def _init_options_multi_currency(self, options, previous_options):
        # Force the currency symbol display when a custom currency is selected.
        super()._init_options_multi_currency(options, previous_options)
        if self._get_custom_currency(previous_options):
            options["multi_currency"] = True

    def _get_options_initializers_forced_sequence_map(self):
        sequence_map = super()._get_options_initializers_forced_sequence_map()
        # Must run before _init_options_multi_currency, which reads its result.
        sequence_map[self._init_options_custom_currency] = sequence_map.get(self._init_options_multi_currency, 1000) - 1
        return sequence_map

    def _get_report_query(self, options, date_scope, domain=None, cta_date_to=None):
        # The context is propagated to account.move.line's consolidation_rate SQL computation.
        report = self.with_context(custom_currency_id=self._get_custom_currency(options).id or False)
        return super(AccountReport, report)._get_report_query(options, date_scope, domain=domain, cta_date_to=cta_date_to)

    def _build_column_data(self, col_value, options_col_desc, options=None, currency=None, digits=1,
                           column_expression=None, has_sublines=False, report_line_id=None):
        target_currency = self._get_custom_currency(options)
        if target_currency and (not currency or currency == self.env.company.currency_id):
            currency = target_currency
        return super()._build_column_data(
            col_value, options_col_desc, options=options, currency=currency, digits=digits,
            column_expression=column_expression, has_sublines=has_sublines, report_line_id=report_line_id,
        )

    def _format_value(self, options, value, figure_type, format_params=None):
        target_currency = self._get_custom_currency(options)
        if target_currency and figure_type == "monetary" and (format_params is None or not format_params.currency_id):
            if format_params is None:
                format_params = AccountReportColumnFormatParamsData()
            format_params.currency_id = target_currency.id
        return super()._format_value(options, value, figure_type, format_params=format_params)

    def get_report_information(self, options):
        info = super().get_report_information(options)
        target_currency = self._get_custom_currency(options)
        if target_currency and info.get("report"):
            info["report"]["company_currency_symbol"] = target_currency.symbol
        return info
