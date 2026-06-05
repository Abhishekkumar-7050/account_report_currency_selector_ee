/** @odoo-module **/

import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
import { patch } from "@web/core/utils/patch";

patch(AccountReportFilters.prototype, {
  async onCustomButtonClick(currencyId) {
    if (currencyId) {
      await this.filterClicked({
        optionKey: "custom_currency_id",
        optionValue: currencyId,
        reload: true,
      });
    }
  },
});
