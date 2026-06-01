/** @odoo-module **/

import { AccountReportController } from "@account_reports/components/account_report/controller";
import { patch } from "@web/core/utils/patch";

patch(AccountReportController.prototype, {
  async load(env) {
    await super.load(env);
    const currencies = await this.orm.searchRead(
      "res.currency",
      [["active", "=", true]],
      ["id", "name"]
    );
    this.data.available_currencies = currencies;
    console.log("Loaded active currencies:", this.data.available_currencies);
  },
});

import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
patch(AccountReportFilters.prototype, {
    /**
     * Handles currency selection
     * @param {Number} currencyId
     */
    async onCustomCurrencySelected(currencyId) {
        const id = parseInt(currencyId);
        await this.controller.updateOption('custom_currency_id', id, true);
        console.log("button clicked");
        this.controller.saveSessionOptions(this.controller.options);
    }
});
