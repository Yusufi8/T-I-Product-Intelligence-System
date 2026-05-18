from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression

from odoo.addons.ti_product_intelligence.models.product_governance import (
    build_standard_product_name,
    normalize_text,
    odoo_product_type_from_pis,
)


class TiProductCreationWizard(models.TransientModel):
    _name = "ti.product.creation.wizard"
    _description = "Controlled PIS Product Creation Wizard"

    source_model = fields.Char(readonly=True)
    source_res_id = fields.Integer(readonly=True)
    is_sale_source = fields.Boolean(compute="_compute_source_flags")
    is_purchase_source = fields.Boolean(compute="_compute_source_flags")

    search_query = fields.Char(string="Search Product")
    selected_product_tmpl_id = fields.Many2one("product.template", string="Selected Product", readonly=True)
    selected_product_id = fields.Many2one("product.product", related="selected_product_tmpl_id.product_variant_id", string="Selected Variant")
    search_result_ids = fields.One2many("ti.product.search.result.wizard", "wizard_id", string="Search Results")

    name = fields.Char(string="Standardized Product Name", readonly=True)
    category_id = fields.Many2one("ti.product.category", string="Product Category")
    subcategory_id = fields.Many2one("ti.product.category", string="Subcategory")
    product_type = fields.Selection(related="category_id.product_type", readonly=True)
    product_classification = fields.Char(compute="_compute_product_classification")
    brand = fields.Char(string="Brand/Make")
    vendor_id = fields.Many2one("res.partner", string="Primary Vendor")
    vendor_code = fields.Char(string="Vendor Code")
    material_details = fields.Text(string="Material Details")
    keyword_text = fields.Char(string="Keywords")
    revision = fields.Char(default="Rev.A")
    line_uom_id = fields.Many2one("uom.uom", string="UOM")
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

    line_quantity = fields.Float(string="Quantity", default=1.0)
    sale_price_unit = fields.Float(string="Unit Price")
    sale_discount = fields.Float(string="Discount")
    sale_tax_ids = fields.Many2many("account.tax", "ti_pis_wizard_sale_tax_rel", "wizard_id", "tax_id", string="Taxes")
    sale_customer_lead = fields.Float(string="Delivery Lead Time")
    purchase_price_unit = fields.Float(string="Cost")
    purchase_vendor_id = fields.Many2one("res.partner", string="Vendor")
    purchase_planned_date = fields.Datetime(string="Planned Date", default=fields.Datetime.now)
    purchase_tax_ids = fields.Many2many("account.tax", "ti_pis_wizard_purchase_tax_rel", "wizard_id", "tax_id", string="Taxes")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        source_model = values.get("source_model") or self.env.context.get("default_source_model") or self.env.context.get("source_model") or self.env.context.get("active_model")
        source_res_id = values.get("source_res_id") or self.env.context.get("default_source_res_id") or self.env.context.get("active_id")
        if source_model:
            values["source_model"] = source_model
        if source_res_id:
            values["source_res_id"] = source_res_id
        order = self._get_order_from_values(source_model, source_res_id)
        if order:
            if source_model == "sale.order":
                values.setdefault("sale_discount", 0.0)
                values.setdefault("sale_customer_lead", 0.0)
            elif source_model == "purchase.order":
                values.setdefault("vendor_id", order.partner_id.id)
                values.setdefault("purchase_vendor_id", order.partner_id.id)
                values.setdefault("purchase_planned_date", fields.Datetime.now())
            values.setdefault("line_quantity", 1.0)
        return values

    @api.model
    def action_open_from_context(self, source_model=None, source_res_id=None):
        context = dict(self.env.context)
        if source_model:
            context["default_source_model"] = source_model
        if source_res_id:
            context["default_source_res_id"] = source_res_id
        return {
            "type": "ir.actions.act_window",
            "name": _("Add Governed Product"),
            "res_model": self._name,
            "view_mode": "form",
            "target": "new",
            "context": context,
        }

    @api.model
    def _get_order_from_values(self, source_model, source_res_id):
        if source_model in ("sale.order", "purchase.order") and source_res_id:
            return self.env[source_model].browse(source_res_id).exists()
        return self.env["sale.order"].browse()

    def _get_source_order(self):
        self.ensure_one()
        return self._get_order_from_values(self.source_model, self.source_res_id)

    @api.depends("source_model")
    def _compute_source_flags(self):
        for wizard in self:
            wizard.is_sale_source = wizard.source_model == "sale.order"
            wizard.is_purchase_source = wizard.source_model == "purchase.order"

    @api.depends("category_id", "subcategory_id", "product_type")
    def _compute_product_classification(self):
        labels = dict(self.env["ti.product.category"]._fields["product_type"].selection)
        for wizard in self:
            parts = []
            if wizard.product_type:
                parts.append(labels.get(wizard.product_type, wizard.product_type))
            if wizard.category_id:
                parts.append(wizard.category_id.name)
            if wizard.subcategory_id:
                parts.append(wizard.subcategory_id.name)
            wizard.product_classification = " / ".join(parts)

    @api.depends("duplicate_line_ids.score", "category_id.duplicate_threshold")
    def _compute_duplicate_blocked(self):
        for wizard in self:
            threshold = wizard.category_id.duplicate_threshold or wizard.duplicate_threshold
            wizard.duplicate_blocked = any(line.score >= threshold for line in wizard.duplicate_line_ids)

    @api.onchange("category_id")
    def _onchange_category_id(self):
        self.selected_product_tmpl_id = False
        self.subcategory_id = False
        self.spec_line_ids = [(5, 0, 0)]
        if self.category_id:
            self.spec_line_ids = [(0, 0, {"attribute_id": attribute.id}) for attribute in self.category_id.attribute_ids.sorted("sequence")]
        self._recompute_preview()

    @api.onchange("selected_product_tmpl_id")
    def _onchange_selected_product_tmpl_id(self):
        if self.selected_product_tmpl_id:
            self._fill_from_product(self.selected_product_tmpl_id)

    @api.onchange(
        "brand",
        "vendor_id",
        "vendor_code",
        "material_details",
        "keyword_text",
        "spec_line_ids",
        "spec_line_ids.value_char",
        "spec_line_ids.value_float",
        "spec_line_ids.value_id",
    )
    def _onchange_preview(self):
        self._recompute_preview()

    def _spec_value_map(self):
        self.ensure_one()
        values = {}
        for line in self.spec_line_ids:
            if not line.attribute_id:
                continue
            token_value = ((line.value_id.code or line.display_value) if line.data_type == "selection" else line.display_value)
            values[line.attribute_id.id] = token_value
            values[line.attribute_id.code] = token_value
        return values

    def _standard_name(self):
        self.ensure_one()
        return build_standard_product_name(self.category_id, self.spec_line_ids.sorted("sequence"), self.brand)

    def _recompute_preview(self):
        for wizard in self:
            wizard.name = wizard._standard_name()
            spec_values = wizard._spec_value_map()
            parts = [wizard.category_id.name or ""]
            for line in wizard.spec_line_ids:
                if line.display_value:
                    parts.append("%s %s" % (line.attribute_id.name, line.display_value))
            if wizard.brand:
                parts.append(wizard.brand)
            if wizard.material_details:
                parts.append(wizard.material_details)
            wizard.description = " | ".join([part for part in parts if part])
            rule = wizard.category_id.uid_rule_id
            wizard.proposed_uid = rule.generate_uid(
                wizard.category_id,
                spec_values,
                wizard.brand,
                wizard.vendor_id.name,
                consume_sequence=False,
            ) if rule else False

    def _reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Add Governed Product"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _category_domain(self):
        self.ensure_one()
        domain = [("ti_category_id", "!=", False)]
        if self.category_id:
            domain.append(("ti_category_id", "=", self.category_id.id))
        if self.subcategory_id:
            domain.append(("ti_subcategory_id", "=", self.subcategory_id.id))
        return domain

    def action_search_products(self):
        self.ensure_one()
        Product = self.env["product.template"]
        domain = self._category_domain()
        query = (self.search_query or "").strip()
        exact_products = Product.browse()
        if query:
            normalized = normalize_text(query)
            exact_domain = expression.OR([
                [("ti_uid", "=", query)],
                [("default_code", "=", query)],
                [("ti_legacy_ref", "=", query)],
                [("ti_vendor_code", "=", query)],
            ])
            exact_products = Product.search(expression.AND([domain, exact_domain]), limit=20)
            alias_products = self.env["ti.product.alias"].search([
                "|",
                ("name", "=", query),
                ("normalized_name", "=", normalized),
            ], limit=50).mapped("product_tmpl_id")
            if self.category_id:
                alias_products = alias_products.filtered(lambda product: product.ti_category_id == self.category_id)
            exact_products |= alias_products
            fuzzy_domain = expression.OR([
                [("ti_uid", "ilike", query)],
                [("default_code", "ilike", query)],
                [("ti_legacy_ref", "ilike", query)],
                [("ti_vendor_code", "ilike", query)],
                [("ti_brand", "ilike", query)],
                [("name", "ilike", query)],
                [("ti_spec_search_text", "ilike", normalized)],
                [("ti_keyword_search_text", "ilike", normalized)],
                [("ti_alias_ids.normalized_name", "ilike", normalized)],
            ])
            fuzzy_products = Product.search(expression.AND([domain, [("id", "not in", exact_products.ids)], fuzzy_domain]), limit=80)
        else:
            fuzzy_products = Product.search(domain, limit=80)

        products = (exact_products | fuzzy_products)[:80]
        commands = [(5, 0, 0)]
        for product in products:
            score = 100.0 if product in exact_products else 0.0
            reason = _("exact match") if product in exact_products else _("search match")
            commands.append((0, 0, {
                "product_tmpl_id": product.id,
                "score": score,
                "match_reason": reason,
            }))
        self.search_result_ids = commands
        if len(products) == 1 and products == exact_products:
            self.selected_product_tmpl_id = products
            self._fill_from_product(products)
        return self._reopen()

    def _fill_from_product(self, product_tmpl):
        self.ensure_one()
        product = product_tmpl.product_variant_id
        self.selected_product_tmpl_id = product_tmpl
        self.category_id = product_tmpl.ti_category_id
        self.subcategory_id = product_tmpl.ti_subcategory_id
        self.brand = product_tmpl.ti_brand
        self.vendor_id = product_tmpl.ti_primary_vendor_id
        self.vendor_code = product_tmpl.ti_vendor_code
        self.material_details = product_tmpl.ti_material_details
        self.keyword_text = ", ".join(product_tmpl.ti_keyword_ids.mapped("name"))
        self.revision = product_tmpl.ti_revision
        self.name = product_tmpl.name
        self.proposed_uid = product_tmpl.ti_uid
        self.description = product_tmpl.description_sale or product_tmpl.description_purchase
        self.line_uom_id = product.uom_id
        self.spec_line_ids = [(5, 0, 0)] + [
            (0, 0, {
                "attribute_id": line.attribute_id.id,
                "value_char": line.value_char,
                "value_float": line.value_float,
                "value_id": line.value_id.id,
            })
            for line in product_tmpl.ti_spec_line_ids.sorted("sequence")
        ]
        self._set_order_line_defaults(product_tmpl)

    def _set_order_line_defaults(self, product_tmpl):
        self.ensure_one()
        product = product_tmpl.product_variant_id
        order = self._get_source_order()
        company = order.company_id if order else self.env.company
        quantity = self.line_quantity or 1.0
        if self.is_sale_source:
            taxes = product_tmpl.taxes_id.filtered(lambda tax: not tax.company_id or tax.company_id == company)
            if order and order.fiscal_position_id:
                taxes = order.fiscal_position_id.map_tax(taxes)
            self.sale_tax_ids = [(6, 0, taxes.ids)]
            self.sale_price_unit = self._get_sale_price(product, order, quantity)
            self.sale_customer_lead = product.product_tmpl_id.sale_delay or 0.0
        elif self.is_purchase_source:
            vendor = order.partner_id if order else product_tmpl.ti_primary_vendor_id
            self.purchase_vendor_id = vendor
            taxes = product_tmpl.supplier_taxes_id.filtered(lambda tax: not tax.company_id or tax.company_id == company)
            if order and order.fiscal_position_id:
                taxes = order.fiscal_position_id.map_tax(taxes)
            self.purchase_tax_ids = [(6, 0, taxes.ids)]
            self.line_uom_id = product.product_tmpl_id.uom_po_id or product.uom_id
            self.purchase_price_unit = self._get_purchase_price(product, vendor, quantity)

    def _get_sale_price(self, product, order, quantity):
        if order and order.pricelist_id:
            try:
                return order.pricelist_id._get_product_price(
                    product,
                    quantity,
                    order.partner_id,
                    uom=self.line_uom_id or product.uom_id,
                    date=order.date_order,
                )
            except Exception:
                return product.lst_price
        return product.lst_price

    def _get_purchase_price(self, product, vendor, quantity):
        seller = False
        if vendor:
            try:
                seller = product._select_seller(
                    partner_id=vendor,
                    quantity=quantity,
                    date=fields.Date.context_today(self),
                    uom_id=self.line_uom_id or product.product_tmpl_id.uom_po_id or product.uom_id,
                )
            except Exception:
                seller = product.seller_ids.filtered(lambda item: item.partner_id == vendor)[:1]
        return seller.price if seller else product.standard_price

    def _validate_wizard(self):
        self.ensure_one()
        self._recompute_preview()
        if not self.category_id:
            raise ValidationError(_("Select a product category before creating a governed product."))
        if self.subcategory_id and self.subcategory_id.parent_id and self.subcategory_id.parent_id != self.category_id:
            raise ValidationError(_("Selected subcategory does not belong to the selected category."))
        if self.name != self._standard_name():
            raise ValidationError(_("Product name does not follow company naming standards."))
        missing = [line.attribute_id.name for line in self.spec_line_ids if line.attribute_id.mandatory and not line.display_value]
        if missing:
            raise ValidationError(_("Missing mandatory technical specifications: %s") % ", ".join(missing))
        if self.category_id.requires_attachment and not self.attachment_ids:
            raise ValidationError(_("This category requires drawing/sample attachments before product creation."))
        threshold = self.category_id.duplicate_threshold or self.duplicate_threshold
        duplicate_blocked = any(line.score >= threshold for line in self.duplicate_line_ids)
        if duplicate_blocked and not self.override_duplicate:
            raise ValidationError(_("Similar or identical product already exists."))
        if self.duplicate_line_ids and self.override_duplicate and not self.override_reason:
            raise ValidationError(_("Type a reason before overriding duplicate warnings."))
        if self.override_duplicate and not (
            self.env.user.has_group("ti_product_intelligence.group_ti_product_steward")
            or self.env.user.has_group("ti_product_intelligence.group_ti_product_manager")
        ):
            raise AccessError(_("Only Product Stewards or PIS Managers can override duplicates."))

    def action_check_duplicates(self):
        self.ensure_one()
        self._recompute_preview()
        if not self.category_id:
            raise ValidationError(_("Select a product category before checking duplicates."))
        self.duplicate_line_ids = [(5, 0, 0)]
        temp_product = self.env["product.template"].new({
            "name": self.name,
            "ti_category_id": self.category_id.id,
            "ti_brand": self.brand,
        })
        normalized_name = normalize_text(" ".join([self.name or "", self.brand or "", self.vendor_code or ""]))
        spec_text = normalize_text(" ".join(self.spec_line_ids.mapped("display_value")))
        Product = self.env["product.template"]
        exact_products = Product.browse()
        exact_reasons = {}
        if self.proposed_uid:
            for product in Product.search(expression.OR([
                [("ti_uid", "=", self.proposed_uid)],
                [("default_code", "=", self.proposed_uid)],
                [("ti_legacy_ref", "=", self.proposed_uid)],
            ]), limit=20):
                exact_products |= product
                exact_reasons[product.id] = _("matching UID/internal reference")
        if self.vendor_code:
            alias_matches = self.env["ti.product.alias"].search([
                ("alias_type", "=", "vendor_code"),
                "|",
                ("name", "=", self.vendor_code),
                ("normalized_name", "=", normalize_text(self.vendor_code)),
            ], limit=50).mapped("product_tmpl_id")
            for product in alias_matches:
                exact_products |= product
                exact_reasons[product.id] = _("matching vendor code")
        candidate_domain = [("ti_category_id", "=", self.category_id.id)]
        candidates = Product.search(candidate_domain, limit=200) - exact_products
        scored = [
            {
                "product": product,
                "score": 100.0,
                "reason": exact_reasons.get(product.id, _("exact duplicate")),
            }
            for product in exact_products
        ]
        scored += temp_product._ti_score_duplicates(candidates, normalized_name, spec_text)
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
        return self._reopen()

    def _create_keyword_commands(self):
        self.ensure_one()
        keywords = []
        for keyword in (self.keyword_text or "").replace(";", ",").split(","):
            keyword = keyword.strip()
            if keyword:
                keywords.append((0, 0, {"name": keyword, "category_id": self.category_id.id}))
        return keywords

    def _create_governed_product(self):
        self.ensure_one()
        self.action_check_duplicates()
        self._validate_wizard()
        rule = self.category_id.uid_rule_id
        if not rule:
            raise ValidationError(_("Configure a UID rule before creating products in this category."))
        uid = rule.generate_uid(self.category_id, self._spec_value_map(), self.brand, self.vendor_id.name, consume_sequence=True)
        blocked = any(line.score >= (self.category_id.duplicate_threshold or self.duplicate_threshold) for line in self.duplicate_line_ids)
        vals = {
            "name": self.name,
            "ti_category_id": self.category_id.id,
            "ti_subcategory_id": self.subcategory_id.id,
            "categ_id": self.category_id.categ_id.id,
            "ti_brand": self.brand,
            "ti_primary_vendor_id": self.vendor_id.id,
            "ti_vendor_code": self.vendor_code,
            "ti_material_details": self.material_details,
            "type": odoo_product_type_from_pis(self.category_id.product_type),
            "ti_uid": uid,
            "default_code": uid,
            "description_purchase": self.description,
            "description_sale": self.description,
            "ti_governance_state": "approved" if self.override_duplicate or not blocked else "pending_review",
            "ti_revision": self.revision,
            "ti_keyword_ids": self._create_keyword_commands(),
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
        if self.line_uom_id:
            vals.update({
                "uom_id": self.line_uom_id.id,
                "uom_po_id": self.line_uom_id.id,
            })
        product = self.env["product.template"].with_context(ti_allow_product_create=True).create(vals)
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
        self.selected_product_tmpl_id = product
        self.proposed_uid = uid
        return product

    def action_create_product(self):
        self.ensure_one()
        product = self._create_governed_product()
        return {
            "type": "ir.actions.act_window",
            "name": _("Product"),
            "res_model": "product.template",
            "res_id": product.id,
            "view_mode": "form",
        }

    def _get_line_product(self):
        self.ensure_one()
        product_tmpl = self.selected_product_tmpl_id or self._create_governed_product()
        product = product_tmpl.product_variant_id
        if not product:
            raise UserError(_("The selected product has no variant to add to the order."))
        return product

    def _sale_line_name(self, product):
        try:
            return product.get_product_multiline_description_sale()
        except Exception:
            return product.display_name

    def _purchase_line_name(self, product):
        description = product.display_name
        if product.description_purchase:
            description = "%s\n%s" % (description, product.description_purchase)
        return description

    def _prepare_sale_order_line_vals(self, product):
        self.ensure_one()
        order = self._get_source_order()
        if not order:
            raise UserError(_("Save the sales order before adding governed products."))
        taxes = self.sale_tax_ids or product.product_tmpl_id.taxes_id
        return {
            "order_id": order.id,
            "product_id": product.id,
            "name": self._sale_line_name(product),
            "product_uom_qty": self.line_quantity or 1.0,
            "product_uom": (self.line_uom_id or product.uom_id).id,
            "price_unit": self.sale_price_unit,
            "discount": self.sale_discount,
            "tax_id": [(6, 0, taxes.ids)],
            "customer_lead": self.sale_customer_lead,
        }

    def _prepare_purchase_order_line_vals(self, product):
        self.ensure_one()
        order = self._get_source_order()
        if not order:
            raise UserError(_("Save the purchase order before adding governed products."))
        taxes = self.purchase_tax_ids or product.product_tmpl_id.supplier_taxes_id
        return {
            "order_id": order.id,
            "product_id": product.id,
            "name": self._purchase_line_name(product),
            "product_qty": self.line_quantity or 1.0,
            "product_uom": (self.line_uom_id or product.product_tmpl_id.uom_po_id or product.uom_id).id,
            "price_unit": self.purchase_price_unit,
            "date_planned": self.purchase_planned_date or fields.Datetime.now(),
            "taxes_id": [(6, 0, taxes.ids)],
        }

    def action_apply_to_order(self):
        self.ensure_one()
        if self.source_model not in ("sale.order", "purchase.order"):
            raise UserError(_("This wizard is not linked to a Sales or Purchase Order."))
        product = self._get_line_product()
        if self.source_model == "sale.order":
            self.env["sale.order.line"].create(self._prepare_sale_order_line_vals(product))
        else:
            self.env["purchase.order.line"].create(self._prepare_purchase_order_line_vals(product))
        return {"type": "ir.actions.act_window_close"}


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


class TiProductSearchResultWizard(models.TransientModel):
    _name = "ti.product.search.result.wizard"
    _description = "PIS Product Search Result"
    _order = "score desc, product_tmpl_id"

    wizard_id = fields.Many2one("ti.product.creation.wizard", required=True, ondelete="cascade")
    product_tmpl_id = fields.Many2one("product.template", string="Product", readonly=True)
    product_id = fields.Many2one("product.product", related="product_tmpl_id.product_variant_id", string="Variant")
    ti_uid = fields.Char(related="product_tmpl_id.ti_uid", string="UID")
    category_id = fields.Many2one(related="product_tmpl_id.ti_category_id", string="Category")
    brand = fields.Char(related="product_tmpl_id.ti_brand", string="Brand")
    technical_specs = fields.Char(related="product_tmpl_id.ti_spec_summary", string="Technical Specs")
    vendor_id = fields.Many2one(related="product_tmpl_id.ti_primary_vendor_id", string="Vendor")
    internal_reference = fields.Char(related="product_tmpl_id.default_code", string="Internal Reference")
    existing_cost = fields.Float(related="product_tmpl_id.ti_latest_cost_price", string="Existing Cost", groups="ti_product_intelligence.group_ti_price_cost,ti_product_intelligence.group_ti_product_manager")
    existing_sale_price = fields.Float(related="product_tmpl_id.ti_latest_sale_price", string="Existing Sale Price", groups="ti_product_intelligence.group_ti_price_sale,ti_product_intelligence.group_ti_product_manager")
    keyword_summary = fields.Char(compute="_compute_keyword_summary", string="Keywords")
    score = fields.Float(readonly=True)
    match_reason = fields.Char(readonly=True)

    @api.depends("product_tmpl_id.ti_alias_ids.name", "product_tmpl_id.ti_keyword_ids.name")
    def _compute_keyword_summary(self):
        for line in self:
            aliases = line.product_tmpl_id.ti_alias_ids.mapped("name")
            keywords = line.product_tmpl_id.ti_keyword_ids.mapped("name")
            line.keyword_summary = ", ".join((keywords + aliases)[:8])

    def action_select_existing_product(self):
        self.ensure_one()
        self.wizard_id._fill_from_product(self.product_tmpl_id)
        return self.wizard_id._reopen()


class TiProductCreationDuplicateWizard(models.TransientModel):
    _name = "ti.product.creation.duplicate.wizard"
    _description = "PIS Product Creation Duplicate Candidate"
    _order = "score desc"

    wizard_id = fields.Many2one("ti.product.creation.wizard", required=True, ondelete="cascade")
    product_tmpl_id = fields.Many2one("product.template", readonly=True)
    ti_uid = fields.Char(related="product_tmpl_id.ti_uid")
    category_id = fields.Many2one(related="product_tmpl_id.ti_category_id", string="Category")
    score = fields.Float(readonly=True)
    reason = fields.Char(readonly=True)
