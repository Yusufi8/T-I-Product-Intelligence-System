from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TiProductBomWizard(models.TransientModel):
    _name = "ti.product.bom.wizard"
    _description = "PIS BOM Creation Wizard"

    product_tmpl_id = fields.Many2one("product.template", required=True, domain="[('ti_category_id', '!=', False)]")
    bom_type = fields.Selection(
        [("normal", "Manufacture this product"), ("phantom", "Kit"), ("subcontract", "Subcontracting")],
        default="normal",
        required=True,
    )
    component_line_ids = fields.One2many("ti.product.bom.wizard.line", "wizard_id", string="Components")

    def action_create_bom(self):
        self.ensure_one()
        if not self.component_line_ids:
            raise ValidationError(_("Add at least one BOM component."))
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": self.product_tmpl_id.id,
            "type": self.bom_type,
        })
        for line in self.component_line_ids:
            if not line.product_id.product_tmpl_id.ti_category_id:
                raise ValidationError(_("Component %s is not a PIS governed product.") % line.product_id.display_name)
            self.env["mrp.bom.line"].create({
                "bom_id": bom.id,
                "product_id": line.product_id.id,
                "product_qty": line.quantity,
                "product_uom_id": line.uom_id.id,
                "operation_id": line.operation_id.id,
            })
        return {
            "type": "ir.actions.act_window",
            "name": _("Bill of Materials"),
            "res_model": "mrp.bom",
            "res_id": bom.id,
            "view_mode": "form",
        }


class TiProductBomWizardLine(models.TransientModel):
    _name = "ti.product.bom.wizard.line"
    _description = "PIS BOM Creation Wizard Line"

    wizard_id = fields.Many2one("ti.product.bom.wizard", ondelete="cascade")
    creation_wizard_id = fields.Many2one("ti.product.creation.wizard", ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, domain="[('product_tmpl_id.ti_category_id', '!=', False)]")
    quantity = fields.Float(default=1.0, required=True)
    uom_id = fields.Many2one("uom.uom", required=True)
    operation_id = fields.Many2one("mrp.routing.workcenter", string="Operation")

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for line in self:
            if line.product_id and not line.uom_id:
                line.uom_id = line.product_id.uom_id
