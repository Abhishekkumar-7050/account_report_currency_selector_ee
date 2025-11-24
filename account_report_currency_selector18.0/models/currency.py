# -*- coding: utf-8 -*-
from odoo import models, api, fields, _
from odoo.tools import date_utils, SQL
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta


class ResCurrency(models.Model):
    _inherit = "res.currency"

    @api.model
    def _get_monocurrency_currency_table_sql(
        self, companies, use_cta_rates=False, target_currency=None
    ):
        """
        OVERRIDE:
        Agar target_currency di gayi hai, toh rates uske hisaab se banayein.
        """
        if (
            not target_currency
            or not companies
            or target_currency == companies.currency_id
        ):
            return super()._get_monocurrency_currency_table_sql(
                companies, use_cta_rates=use_cta_rates
            )

        company_currency = companies.currency_id
        date = self._context.get("date_to") or fields.Date.today()
        rate_map = company_currency._get_rates(companies, date)
        rate = rate_map.get(target_currency.id)

        if not rate:
            rate = 1.0 if company_currency == target_currency else 0.0

        rate_values = [
            SQL(
                "(%(company_id)s, CAST(NULL AS VARCHAR), CAST(NULL AS DATE), CAST(NULL AS DATE), %(rate_type)s, %(rate)s)",
                company_id=company.id,
                rate_type=rate_type,
                rate=rate,
            )
            for company in companies
            for rate_type in (
                ("historical", "current", "average") if use_cta_rates else ("current",)
            )
        ]

        if not rate_values:
            return SQL(
                """
                (VALUES (
                    NULL::integer, NULL::varchar, NULL::date, 
                    NULL::date, NULL::varchar, 1::numeric
                ))
                AS account_currency_table(company_id, period_key, date_from, date_next, rate_type, rate)
                WHERE 1=0
            """
            )

        return SQL(
            "(VALUES %s) AS account_currency_table(company_id, period_key, date_from, date_next, rate_type, rate)",
            SQL(",").join(rate_values),
        )

    def _create_currency_table(self, companies, date_periods, use_cta_rates=False):
        """
        OVERRIDE:
        - If custom target currency found in context, use that instead of main company currency.
        - Otherwise run normal Odoo logic.
        """
        forced_currency_id = self.env.context.get("custom_currency_id")
        main_company = self.env.company

        if forced_currency_id:
            currency = self.env["res.currency"].browse(forced_currency_id)
        else:
            currency = main_company.currency_id

        domestic_currency_companies = companies.filtered(
            lambda x: x.currency_id == currency
        )
        other_companies = companies - domestic_currency_companies

        table_builders = []
        if domestic_currency_companies:
            table_builders += [
                self._get_table_builder_domestic_currency(
                    domestic_currency_companies, use_cta_rates
                )
            ]

        last_date_to = None
        for period_key, date_from, date_to in date_periods:
            main_company_unit_factor = self._compute_rate_factor(main_company, date_to)
            if not main_company_unit_factor:
                main_company_unit_factor = main_company.currency_id._get_rates(
                    main_company, date_to
                )[main_company.currency_id.id]

            if use_cta_rates:
                table_builders += [
                    self._get_table_builder_closing(
                        period_key,
                        main_company,
                        other_companies,
                        date_to,
                        main_company_unit_factor,
                    ),
                    self._get_table_builder_historical(
                        main_company,
                        other_companies,
                        date_to,
                        main_company_unit_factor,
                        last_date_to,
                    ),
                    self._get_table_builder_average(
                        period_key,
                        main_company,
                        other_companies,
                        date_from,
                        date_to,
                        main_company_unit_factor,
                    ),
                ]
            else:

                table_builders += [
                    self._get_table_builder_current(
                        period_key,
                        main_company,
                        other_companies,
                        date_to,
                        main_company_unit_factor,
                    )
                ]

            last_date_to = date_to

        self._cr.execute(
            SQL(
                """
            DROP TABLE IF EXISTS account_currency_table;

            CREATE TEMPORARY TABLE account_currency_table
            (company_id, period_key, date_from, date_next, rate_type, rate)
            ON COMMIT DROP
            AS (%(currency_table_build_query)s);

            CREATE INDEX account_currency_table_index
                ON account_currency_table (company_id, rate_type, date_from, date_next);

            ANALYZE account_currency_table;
            """,
                currency_table_build_query=SQL(" UNION ALL ").join(
                    SQL("(%s)", builder) for builder in table_builders
                ),
            )
        )

    def _compute_rate_factor(self, main_company, date_to):
        """
        Returns correct conversion factor (target_rate / company_rate).
        """
        forced_currency_id = self.env.context.get("custom_currency_id")
        if not forced_currency_id:
            return None

        target_currency = self.browse(forced_currency_id)

        company_currency = main_company.currency_id

        company_rate = company_currency._get_rates(main_company, date_to)[
            company_currency.id
        ]
        target_rate = target_currency._get_rates(main_company, date_to)[
            target_currency.id
        ]

        if company_rate == 0:
            company_rate = 1

        factor = target_rate / company_rate
        return factor

    def _get_table_builder_current(
        self,
        period_key,
        main_company,
        other_companies,
        date_to,
        main_company_unit_factor,
    ):
        """Correct 'current' rate builder — works for custom target currency."""
        forced_currency_id = self.env.context.get("custom_currency_id")
        if forced_currency_id:
            target_currency = self.env["res.currency"].browse(forced_currency_id)
        else:
            target_currency = main_company.currency_id

        target_rate = target_currency._get_rates(main_company, date_to)[
            target_currency.id
        ]

        company_rates = []
        for comp in other_companies:
            comp_rate = comp.currency_id._get_rates(comp, date_to)[comp.currency_id.id]
            conversion_rate = target_rate / comp_rate

            company_rates.append(
                SQL(
                    "(%(cid)s, %(period)s, NULL::DATE, NULL::DATE, 'current', %(rate)s)",
                    cid=comp.id,
                    period=period_key,
                    rate=conversion_rate,
                )
            )
        return SQL(
            """
                SELECT * FROM (VALUES
                    %(vals)s
                ) AS t(company_id, period_key, date_from, date_next, rate_type, rate)
                """,
            vals=SQL(",").join(company_rates),
        )

    def _get_table_builder_closing(
        self,
        period_key,
        main_company,
        other_companies,
        date_to,
        main_company_unit_factor,
    ):
        forced_currency_id = self.env.context.get("custom_currency_id")

        if not forced_currency_id:
            return super()._get_table_builder_closing(
                period_key,
                main_company,
                other_companies,
                date_to,
                main_company_unit_factor,
            )

        target_currency = self.env["res.currency"].browse(forced_currency_id)
        target_rate = target_currency._get_rates(main_company, date_to)[
            target_currency.id
        ]

        company_rows = []

        fiscal_year_bounds = self._get_currency_table_fiscal_year_bounds(main_company)

        for comp in other_companies:
            comp_rate = comp.currency_id._get_rates(comp, date_to)[comp.currency_id.id]
            conversion_rate = target_rate / comp_rate

            for fy_from, fy_to in fiscal_year_bounds:
                company_rows.append(
                    SQL(
                        "(%(cid)s, %(pkey)s, %(fy_from)s, %(fy_to)s, 'closing', %(rate)s)",
                        cid=comp.id,
                        pkey=period_key,
                        fy_from=fy_from,
                        fy_to=fy_to,
                        rate=conversion_rate,
                    )
                )

        if not company_rows:
            return SQL("SELECT 1 WHERE false")

        return SQL(
            """
                SELECT *
                FROM (VALUES
                    %(values)s
                ) AS t(company_id, period_key, date_from, date_next, rate_type, rate)
            """,
            values=SQL(", ").join(company_rows),
        )

    def _get_table_builder_historical(
        self,
        main_company,
        other_companies,
        date_to,
        main_company_unit_factor,
        date_exclude,
    ):
        forced_currency_id = self.env.context.get("custom_currency_id")
        if not forced_currency_id:
            return super()._get_table_builder_historical(
                main_company,
                other_companies,
                date_to,
                main_company_unit_factor,
                date_exclude,
            )

        target_currency = self.env["res.currency"].browse(forced_currency_id)

        rows = []

        for comp in other_companies:
            comp_rates = self.env["res.currency.rate"].search(
                [
                    ("currency_id", "=", comp.currency_id.id),
                    ("company_id", "=", main_company.id),
                    ("name", "<=", date_to),
                ],
                order="name DESC",
            )

            for rate in comp_rates:
                tr = target_currency._get_rates(main_company, rate.name)[
                    target_currency.id
                ]
                cr = rate.rate
                conversion_rate = tr / cr

                rows.append(
                    SQL(
                        "(%(cid)s, NULL, %(date_from)s, %(date_next)s, 'historical', %(rate)s)",
                        cid=comp.id,
                        date_from=rate.name,
                        date_next=None,
                        rate=conversion_rate,
                    )
                )

        if not rows:
            return SQL("SELECT 1 WHERE false")

        return SQL(
            """
                SELECT *
                FROM (VALUES
                    %(values)s
                ) AS t(company_id, period_key, date_from, date_next, rate_type, rate)
            """,
            values=SQL(", ").join(rows),
        )

    def _get_table_builder_average(
        self,
        period_key,
        main_company,
        other_companies,
        date_from,
        date_to,
        main_company_unit_factor,
    ):
        forced_currency_id = self.env.context.get("custom_currency_id")

        if not forced_currency_id:
            return super()._get_table_builder_average(
                period_key,
                main_company,
                other_companies,
                date_from,
                date_to,
                main_company_unit_factor,
            )

        target_currency = self.env["res.currency"].browse(forced_currency_id)

        rows = []

        for comp in other_companies:
            comp_rates = self.env["res.currency.rate"].search(
                [
                    ("currency_id", "=", comp.currency_id.id),
                    ("company_id", "=", main_company.id),
                    ("name", ">=", date_from),
                    ("name", "<=", date_to),
                ],
                order="name ASC",
            )

            if not comp_rates:
                continue

            day_segments = []
            total_days = 0

            for i, rate in enumerate(comp_rates):
                next_date = (
                    comp_rates[i + 1].name if i + 1 < len(comp_rates) else date_to
                )

                days = (
                    fields.Date.from_string(next_date)
                    - fields.Date.from_string(rate.name)
                ).days
                total_days += days

                tr = target_currency._get_rates(main_company, rate.name)[
                    target_currency.id
                ]
                cr = rate.rate
                conversion_rate = tr / cr

                day_segments.append(days * conversion_rate)

            average_rate = sum(day_segments) / total_days if total_days else 1

            rows.append(
                SQL(
                    "(%(cid)s, %(period)s, NULL, NULL, 'average', %(rate)s)",
                    cid=comp.id,
                    period=period_key,
                    rate=average_rate,
                )
            )

        if not rows:
            return SQL("SELECT 1 WHERE false")

        return SQL(
            """
                SELECT *
                FROM (VALUES
                    %(values)s
                ) AS t(company_id, period_key, date_from, date_next, rate_type, rate)
            """,
            values=SQL(", ").join(rows),
        )
