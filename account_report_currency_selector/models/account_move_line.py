# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.tools import SQL


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _compute_sql_consolidation_rate(self, table):
        """ OVERRIDE: when a report currency is forced through the context
        (``custom_currency_id``), convert the consolidated amounts, which are
        expressed in the main company currency, into that currency.
        """
        rate_sql = super()._compute_sql_consolidation_rate(table)
        target_currency_id = self.env.context.get("custom_currency_id")
        company = self.env.company
        if not target_currency_id or target_currency_id == company.currency_id.id:
            return rate_sql

        date_to = fields.Date.to_date(self.env.context.get("date_to")) or fields.Date.context_today(self)
        target_currency = self.env["res.currency"].browse(target_currency_id)
        rates = self.env["res.currency"]._get_rates(company, date_to)
        company_rate = rates.get(company.currency_id.id, (1.0, None))[0] or 1.0
        target_rate = rates.get(target_currency.id, (1.0, None))[0] or 1.0
        return SQL("(%s * %s)", rate_sql, target_rate / company_rate)

    def _compute_sql_consolidation_currency_id(self, table):
        target_currency_id = self.env.context.get("custom_currency_id")
        if target_currency_id:
            return SQL("%s", target_currency_id)
        return super()._compute_sql_consolidation_currency_id(table)
