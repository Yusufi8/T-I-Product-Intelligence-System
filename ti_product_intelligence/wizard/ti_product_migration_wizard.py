from odoo import _, fields, models


class TiProductMigrationWizard(models.TransientModel):
    _name = "ti.product.migration.wizard"
    _description = "PIS Product Migration and Cleanup Wizard"

    category_id = fields.Many2one("ti.product.category", string="Limit to PIS Category")
    batch_limit = fields.Integer(default=500, required=True)
    preserve_default_code = fields.Boolean(default=True)

    def action_prepare_products(self):
        domain = []
        if self.category_id:
            domain.append(("ti_category_id", "=", self.category_id.id))
        products = self.env["product.template"].search(domain, limit=self.batch_limit)
        for product in products:
            vals = {}
            if self.preserve_default_code and product.default_code and not product.ti_legacy_ref and product.default_code != product.ti_uid:
                vals["ti_legacy_ref"] = product.default_code
            if product.ti_category_id and not product.ti_uid and product.ti_category_id.uid_rule_id:
                spec_values = {line.attribute_id.id: line.display_value for line in product.ti_spec_line_ids}
                vals["ti_uid"] = product.ti_category_id.uid_rule_id.generate_uid(
                    product.ti_category_id,
                    spec_values,
                    product.ti_brand,
                    product.ti_primary_vendor_id.name,
                )
            if vals:
                product.write(vals)
            product._ti_create_legacy_alias()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("PIS Migration"),
                "message": _("%s product(s) prepared.") % len(products),
                "type": "success",
                "sticky": False,
            },
        }

