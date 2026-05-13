from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.ti_product_intelligence.models.product_governance import normalize_text, odoo_product_type_from_pis


class TiProductCreationWizard(models.TransientModel):
    _name = "ti.product.creation.wizard"
    _description = "Controlled PIS Product Creation Wizard"

    name = fields.Char(string="Standardized Product Name", required=True)
    category_id = fields.Many2one("ti.product.category", required=True)
    product_type = fields.Selection(related="category_id.product_type", readonly=True)
    brand = fields.Char(string="Brand/Make")
    vendor_id = fields.Many2one("res.partner", string="Primary Vendor")
    proposed_uid = fields.Char(readonly=True)
    description = fields.Text(readonly=True)
    override_duplicate = fields.Boolean(string="Override Duplicate")
    override_reason = fields.Text(string="Override Reason")
    duplicate_threshold = fields.Float(default=85.0)
    review_threshold = fields.Float(default=60.0)
    attachment_ids = fields.Many2many("ir.attachment", string="Drawings / Samples")
    spec_line_ids = fields.One2many("ti.product.creation.spec.wizard", "wizard_id", string="Technical Specifications")
    duplicate_line_ids = fields.One2many("ti.product.creation.duplicate.wizard", "wizard_id", string="Possible Duplicates")
    duplicate_blocked = fields.Boolean(compute="_compute_duplicate_blocked")
    include_bom = fields.Boolean(string="Create BOM")
    bom_line_ids = fields.One2many("ti.product.bom.wizard.line", "creation_wizard_id", string="BOM Components")

    @api.model
    def action_open_from_context(self, source_model=None):
        return {
            "type": "ir.actions.act_window",
            "name": _("Create Governed Product"),
            "res_model": self._name,
            "view_mode": "form",
            "target": "new",
            "context": {"default_source_model": source_model} if source_model else {},
        }

    @api.depends("duplicate_line_ids.score", "category_id.duplicate_threshold")
    def _compute_duplicate_blocked(self):
        for wizard in self:
            threshold = wizard.category_id.duplicate_threshold or 85.0
            wizard.duplicate_blocked = any(line.score >= threshold for line in wizard.duplicate_line_ids)

    @api.onchange("category_id")
    def _onchange_category_id(self):
        self.spec_line_ids = [(5, 0, 0)]
        if self.category_id:
            self.spec_line_ids = [(0, 0, {"attribute_id": attribute.id}) for attribute in self.category_id.attribute_ids.sorted("sequence")]
        self._recompute_preview()

    @api.onchange("name", "brand", "vendor_id", "spec_line_ids", "spec_line_ids.value_char", "spec_line_ids.value_float", "spec_line_ids.value_id")
    def _onchange_preview(self):
        self._recompute_preview()

    def _recompute_preview(self):
        for wizard in self:
            spec_values = wizard._spec_value_map()
            parts = [wizard.category_id.name or "", wizard.name or ""]
            for line in wizard.spec_line_ids:
                if line.display_value:
                    parts.append("%s %s" % (line.attribute_id.name, line.display_value))
            if wizard.brand:
                parts.append(wizard.brand)
            wizard.description = " | ".join([part for part in parts if part])
            rule = wizard.category_id.uid_rule_id
            wizard.proposed_uid = rule.generate_uid(wizard.category_id, spec_values, wizard.brand, wizard.vendor_id.name) if rule else False

    def _spec_value_map(self):
        self.ensure_one()
        values = {}
        for line in self.spec_line_ids:
            token_value = line.value_id.code or line.display_value if line.data_type == "selection" else line.display_value
            values[line.attribute_id.id] = token_value
            values[line.attribute_id.code] = token_value
        return values

    def _validate_wizard(self):
        self.ensure_one()
        missing = [line.attribute_id.name for line in self.spec_line_ids if line.attribute_id.mandatory and not line.display_value]
        if missing:
            raise ValidationError(_("Missing mandatory technical specifications: %s") % ", ".join(missing))
        if self.category_id.requires_attachment and not self.attachment_ids:
            raise ValidationError(_("This category requires drawing/sample attachments before product creation."))
        if self.duplicate_blocked and not self.override_duplicate:
            raise ValidationError(_("A high-confidence duplicate exists. Product creation is blocked."))
        warning_scores = self.duplicate_line_ids.filtered(lambda line: 60 <= line.score < (self.category_id.duplicate_threshold or self.duplicate_threshold))
        if warning_scores and self.override_duplicate and not self.override_reason:
            raise ValidationError(_("Type a reason before overriding duplicate warnings."))
        if self.override_duplicate and not (
            self.env.user.has_group("ti_product_intelligence.group_ti_product_steward")
            or self.env.user.has_group("ti_product_intelligence.group_ti_product_manager")
        ):
            raise AccessError(_("Only Product Stewards or PIS Managers can override duplicates."))

    def action_check_duplicates(self):
        self.ensure_one()
        self._recompute_preview()
        self.duplicate_line_ids = [(5, 0, 0)]
        temp_product = self.env["product.template"].new({
            "name": self.name,
            "ti_category_id": self.category_id.id,
            "ti_brand": self.brand,
        })
        normalized_name = normalize_text(" ".join([self.name or "", self.brand or ""]))
        spec_text = normalize_text(" ".join(self.spec_line_ids.mapped("display_value")))
        candidates = self.env["product.template"].search([("ti_category_id", "=", self.category_id.id)], limit=200)
        scored = temp_product._ti_score_duplicates(candidates, normalized_name, spec_text)
        threshold = self.category_id.review_threshold or self.review_threshold
        self.duplicate_line_ids = [
            (0, 0, {
                "product_tmpl_id": item["product"].id,
                "score": item["score"],
                "reason": item["reason"],
            })
            for item in scored
            if item["score"] >= threshold
        ]
        return {
            "type": "ir.actions.act_window",
            "name": _("Create Governed Product"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_create_product(self):
        self.ensure_one()
        self.action_check_duplicates()
        self._validate_wizard()
        if not self.proposed_uid:
            raise ValidationError(_("Configure a UID rule before creating products in this category."))
        vals = {
            "name": self.name,
            "ti_category_id": self.category_id.id,
            "categ_id": self.category_id.categ_id.id,
            "ti_brand": self.brand,
            "ti_primary_vendor_id": self.vendor_id.id,
            "type": odoo_product_type_from_pis(self.category_id.product_type),
            "ti_uid": self.proposed_uid,
            "default_code": self.proposed_uid,
            "description_purchase": self.description,
            "description_sale": self.description,
            "ti_governance_state": "approved" if not self.duplicate_blocked else "pending_review",
            "ti_spec_line_ids": [
                (0, 0, {
                    "attribute_id": line.attribute_id.id,
                    "value_char": line.value_char,
                    "value_float": line.value_float,
                    "value_id": line.value_id.id,
                })
                for line in self.spec_line_ids
            ],
        }
        product = self.env["product.template"].with_context(ti_allow_product_create=True).create(vals)
        if self.vendor_id:
            self.env["ti.product.alias"].create({
                "product_tmpl_id": product.id,
                "alias_type": "vendor_code",
                "name": self.vendor_id.ref or self.vendor_id.name,
                "partner_id": self.vendor_id.id,
            })
        for duplicate in self.duplicate_line_ids:
            state = "approved" if self.override_duplicate else ("blocked" if duplicate.score >= (self.category_id.duplicate_threshold or self.duplicate_threshold) else "review")
            log = self.env["ti.product.duplicate.log"].create({
                "product_tmpl_id": product.id,
                "duplicate_product_tmpl_id": duplicate.product_tmpl_id.id,
                "category_id": self.category_id.id,
                "score": duplicate.score,
                "reason": "%s\n%s" % (duplicate.reason or "", self.override_reason or ""),
                "state": state,
                "override_user_id": self.env.user.id if self.override_duplicate else False,
                "override_date": fields.Datetime.now() if self.override_duplicate else False,
            })
            if duplicate.score >= 60:
                log._notify_stewards()
        if self.include_bom and self.bom_line_ids:
            bom = self.env["mrp.bom"].create({
                "product_tmpl_id": product.id,
                "type": "normal",
            })
            for line in self.bom_line_ids:
                self.env["mrp.bom.line"].create({
                    "bom_id": bom.id,
                    "product_id": line.product_id.id,
                    "product_qty": line.quantity,
                    "product_uom_id": line.uom_id.id,
                    "operation_id": line.operation_id.id,
                })
        if self.attachment_ids:
            self.attachment_ids.write({"res_model": "product.template", "res_id": product.id})
        return {
            "type": "ir.actions.act_window",
            "name": _("Product"),
            "res_model": "product.template",
            "res_id": product.id,
            "view_mode": "form",
        }


class TiProductCreationSpecWizard(models.TransientModel):
    _name = "ti.product.creation.spec.wizard"
    _description = "PIS Product Creation Specification"
    _order = "sequence, attribute_id"

    wizard_id = fields.Many2one("ti.product.creation.wizard", required=True, ondelete="cascade")
    attribute_id = fields.Many2one("ti.product.attribute", required=True)
    sequence = fields.Integer(related="attribute_id.sequence")
    mandatory = fields.Boolean(related="attribute_id.mandatory")
    data_type = fields.Selection(related="attribute_id.data_type")
    value_char = fields.Char()
    value_float = fields.Float()
    value_id = fields.Many2one("ti.product.attribute.value")
    display_value = fields.Char(compute="_compute_display_value")

    @api.depends("value_char", "value_float", "value_id", "data_type")
    def _compute_display_value(self):
        for line in self:
            if line.data_type == "float":
                line.display_value = ("%s" % line.value_float).rstrip("0").rstrip(".")
            elif line.data_type == "selection":
                line.display_value = line.value_id.name or ""
            else:
                line.display_value = line.value_char or ""


class TiProductCreationDuplicateWizard(models.TransientModel):
    _name = "ti.product.creation.duplicate.wizard"
    _description = "PIS Product Creation Duplicate Candidate"
    _order = "score desc"

    wizard_id = fields.Many2one("ti.product.creation.wizard", required=True, ondelete="cascade")
    product_tmpl_id = fields.Many2one("product.template", readonly=True)
    ti_uid = fields.Char(related="product_tmpl_id.ti_uid")
    score = fields.Float(readonly=True)
    reason = fields.Char(readonly=True)
