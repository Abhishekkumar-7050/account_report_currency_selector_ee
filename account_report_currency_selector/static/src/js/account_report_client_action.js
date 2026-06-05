/** @odoo-module **/

import { AccountReportController } from "@account_reports/components/account_report/controller";
import { patch } from "@web/core/utils/patch";

console.log("AccountReportController (base class) currency patch loaded!");

patch(AccountReportController.prototype, {
  async load(env) {
    console.log("Patched AccountReportController.load() starting...");
    await super.load(env);
    console.log("Original load() finished. Now loading currencies.");

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
  async onCustomButtonClick(currencyId) {
    if (currencyId) {
      console.log("A currency was selected:", currencyId);
      const currency = this.controller.options.available_currencies.find(
        (c) => c.id === currencyId
      );
      console.log("Selected currency object:", currency);
      await this.filterClicked({
        optionKey: "custom_currency_id",
        optionValue: currencyId,
        reload: true,
      });
    } else {
      console.log("The main 'My Button' was clicked.");
    }
  },
});
