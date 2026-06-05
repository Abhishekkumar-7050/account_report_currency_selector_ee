# -*- coding: utf-8 -*-
from odoo import models, api, _, fields
from odoo.exceptions import UserError
from odoo.tools import SQL, formatLang


class AccountReport(models.AbstractModel):
    _inherit = "account.report"

    def get_options(self, previous_options=None):
        options = super().get_options(previous_options)

        if previous_options and "custom_currency_id" in previous_options:
            options["custom_currency_id"] = int(previous_options["custom_currency_id"])
        else:
            options["custom_currency_id"] = self.env.company.currency_id.id

        currencies = self.env["res.currency"].search(
            [("active", "=", True)], order="name"
        )
        options["available_currencies"] = [
            {"id": c.id, "name": c.name} for c in currencies
        ]
        selected_currency = self.env["res.currency"].browse(
            options["custom_currency_id"]
        )
        options["selected_currency_name"] = (
            selected_currency.name if selected_currency.exists() else ""
        )
        options["date_to_ctx"] = options.get("date", {}).get("date_to")

        return options

    def _init_currency_table(self, options):
        target_currency_id = options.get("custom_currency_id")
        currency_model = self.env["res.currency"].with_context(
            date_to=options.get("date_to_ctx"), custom_currency_id=target_currency_id
        )

        if (
            not target_currency_id
            or target_currency_id == self.env.company.currency_id.id
        ):
            return super(AccountReport, self)._init_currency_table(options)

        if options["currency_table"]["type"] != "monocurrency":
            companies = self.env["res.company"].browse(
                self.get_report_company_ids(options)
            )
            currency_model._create_currency_table(
                companies,
                [
                    (period_key, period["from"], period["to"])
                    for period_key, period in options["currency_table"][
                        "periods"
                    ].items()
                ],
                use_cta_rates=options["currency_table"]["type"] == "cta",
            )
        else:
            return super(AccountReport, self)._init_currency_table(options)

    @api.model
    def _get_currency_table(self, options) -> SQL:
        target_currency_id = options.get("custom_currency_id")

        currency_model = self.env["res.currency"].with_context(
            date_to=options.get("date_to_ctx"), custom_currency_id=target_currency_id
        )

        if (
            not target_currency_id
            or target_currency_id == self.env.company.currency_id.id
        ):
            return super()._get_currency_table(options)

        companies = self.env["res.company"].browse(self.get_report_company_ids(options))

        return currency_model._get_monocurrency_currency_table_sql(
            companies, use_cta_rates=options["currency_table"]["type"] == "current"
        )

    def _init_options_multi_currency(self, options, previous_options):
        """
        OVERRIDE: Odoo ko force karein 'multi_currency' mode on karne ke liye.
        """
        super()._init_options_multi_currency(options, previous_options)

        target_currency_id = options.get("custom_currency_id")
        if target_currency_id and target_currency_id != self.env.company.currency_id.id:
            options["multi_currency"] = True

    def _build_column_dict(
        self,
        col_value,
        col_data,
        options=None,
        currency=False,
        digits=1,
        column_expression=None,
        has_sublines=False,
        report_line_id=None,
    ):
        """
        OVERRIDE: Har cell ki currency formatting ko force karein.
        """
        res = super()._build_column_dict(
            col_value,
            col_data,
            options,
            currency,
            digits,
            column_expression,
            has_sublines,
            report_line_id,
        )

        target_currency_id = options.get("custom_currency_id")
        if target_currency_id and target_currency_id != self.env.company.currency_id.id:
            if res.get("figure_type") == "monetary":
                target_currency = self.env["res.currency"].browse(target_currency_id)
                res["format_params"]["currency_id"] = target_currency.id
                res["currency_symbol"] = target_currency.symbol

        return res

    def get_report_information(self, options):
        """
        OVERRIDE: Report ke main symbol ko bhi update karein.
        """
        info = super().get_report_information(options)

        target_currency_id = options.get("custom_currency_id")
        if target_currency_id and target_currency_id != self.env.company.currency_id.id:
            target_currency = self.env["res.currency"].browse(target_currency_id)
            info["report"]["company_currency_symbol"] = target_currency.symbol
            info["report"]["company_country_code"] = "IN"

            if (
                "column_headers_render_data" in info
                and "level_colspan" in info["column_headers_render_data"]
            ):
                for header_level in info["column_headers_render_data"]["level_colspan"]:
                    if isinstance(header_level, list):
                        for header_element in header_level:
                            if "name" in header_element:
                                header_element["name"] = (
                                    f"{header_element['name']} ({target_currency.name})"
                                )

        return info

    def _build_column_dict(
        self,
        col_value,
        col_data,
        options=None,
        currency=False,
        digits=1,
        column_expression=None,
        has_sublines=False,
        report_line_id=None,
    ):
        """
        OVERRIDE: Har cell ki currency formatting ko force karein.
        """
        res = super()._build_column_dict(
            col_value,
            col_data,
            options,
            currency,
            digits,
            column_expression,
            has_sublines,
            report_line_id,
        )

        target_currency_id = options.get("custom_currency_id")
        if target_currency_id and target_currency_id != self.env.company.currency_id.id:
            if res.get("figure_type") == "monetary":
                target_currency = self.env["res.currency"].browse(target_currency_id)
                res["format_params"]["currency_id"] = target_currency.id
                res["currency_symbol"] = target_currency.symbol

        return res

    def _format_value(self, options, value, figure_type, format_params=None):
        """
        OVERRIDE: Format ko force karein taaki woh nayi currency use kare.
        """
        target_currency_id = options.get("custom_currency_id")

        if target_currency_id and target_currency_id != self.env.company.currency_id.id:
            if figure_type == "monetary":
                target_currency = self.env["res.currency"].browse(target_currency_id)

                formatLang_params = {
                    "rounding_method": "HALF-UP",
                    "rounding_unit": options.get("rounding_unit"),
                    "currency_obj": target_currency,
                }

                if value is None:
                    return ""

                return formatLang(self.env, value, **formatLang_params)

        return super()._format_value(
            options, value, figure_type, format_params=format_params
        )

    def _init_options_currency_table(self, options, previous_options):
        super()._init_options_currency_table(options, previous_options)
        target_currency_id = previous_options.get(
            "custom_currency_id", self.env.company.currency_id.id
        )
        if target_currency_id and target_currency_id != self.env.company.currency_id.id:
            options["currency_table"]["type"] = "current"

    def _currency_table_apply_rate(self, value: SQL):
        return SQL("((%(value)s) * account_currency_table.rate)", value=value)

    @api.model
    def _currency_table_aml_join(self, options, aml_alias=SQL("account_move_line")):
        """
        Use custom currency table ONLY when custom currency is selected.
        Otherwise fall back to base Odoo join.
        """
        custom_currency_id = options.get("custom_currency_id")

        if (
            not custom_currency_id
            or custom_currency_id == self.env.company.currency_id.id
        ):
            return super()._currency_table_aml_join(options, aml_alias)
        return SQL(
            """
            JOIN account_currency_table
                ON %(aml)s.company_id = account_currency_table.company_id
            """,
            aml=aml_alias,
        )
