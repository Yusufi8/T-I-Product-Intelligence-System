from odoo import _, fields, models
from odoo.exceptions import ValidationError


class TiProductMergeWizard(models.TransientModel):
    _name = "ti.product.merge.wizard"
    _description = "PIS Product Merge Wizard"

    source_product_tmpl_id = fields.Many2one("product.template", required=True, string="Duplicate Product")
    target_product_tmpl_id = fields.Many2one("product.template", required=True, string="Master Product")
    reason = fields.Text(required=True)

    def action_merge(self):
        self.ensure_one()
        if self.source_product_tmpl_id == self.target_product_tmpl_id:
            raise ValidationError(_("Source and target products must be different."))
        Alias = self.env["ti.product.alias"]
        if self.source_product_tmpl_id.default_code:
            Alias.create({
                "product_tmpl_id": self.target_product_tmpl_id.id,
                "alias_type": "legacy_ref",
                "name": self.source_product_tmpl_id.default_code,
            })
        for alias in self.source_product_tmpl_id.ti_alias_ids:
            alias.product_tmpl_id = self.target_product_tmpl_id.id
        self.env["ti.product.duplicate.log"].create({
            "product_tmpl_id": self.source_product_tmpl_id.id,
            "duplicate_product_tmpl_id": self.target_product_tmpl_id.id,
            "category_id": self.target_product_tmpl_id.ti_category_id.id,
            "score": 100.0,
            "reason": self.reason,
            "state": "merged",
        })
        self.source_product_tmpl_id.write({
            "active": False,
            "ti_governance_state": "archived",
        })
        return {"type": "ir.actions.act_window_close"}

