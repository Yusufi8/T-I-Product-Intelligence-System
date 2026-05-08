import re
from difflib import SequenceMatcher

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.osv import expression


TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")
SPACE_PATTERN = re.compile(r"\s+")
SYNONYMS = {
    "deepgroove": "dg",
    "deep": "dg",
    "groove": "dg",
    "double": "dbl",
    "single": "sgl",
    "phase": "ph",
    "horsepower": "hp",
    "h.p": "hp",
    "rpm": "rpm",
    "r.p.m": "rpm",
}


def normalize_text(value):
    """Return a stable normalized token string for UID/search/duplicate logic."""
    value = (value or "").lower().replace("&", " and ")
    value = TOKEN_PATTERN.sub(" ", value)
    tokens = []
    for token in SPACE_PATTERN.sub(" ", value).strip().split(" "):
        if not token:
            continue
        token = SYNONYMS.get(token, token)
        if token.endswith("zz") and len(token) > 2:
            tokens.append(token[:-2])
            tokens.append("zz")
        else:
            tokens.append(token)
    return " ".join(sorted(tokens))


def slug_token(value):
    value = (value or "").upper()
    return re.sub(r"[^A-Z0-9]+", "", value)


class TiProductCategory(models.Model):
    _name = "ti.product.category"
    _description = "PIS Product Category Profile"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, name"

    name = fields.Char(required=True, tracking=True, index=True)
    code = fields.Char(required=True, tracking=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    categ_id = fields.Many2one("product.category", string="Odoo Category", required=True, index=True)
    product_type = fields.Selection(
        [
            ("raw_material", "Raw Material"),
            ("bought_out", "Bought Out"),
            ("finished_goods", "Finished Goods"),
            ("consumable", "Consumable"),
            ("service", "Service"),
        ],
        default="raw_material",
        required=True,
        tracking=True,
    )
    requires_attachment = fields.Boolean(string="Require Drawing/Sample Attachment")
    uid_rule_id = fields.Many2one("ti.product.uid.rule", string="Default UID Rule")
    attribute_ids = fields.One2many("ti.product.attribute", "category_id", string="Technical Specifications")
    duplicate_threshold = fields.Float(default=85.0, help="Scores at or above this value block normal creation.")
    review_threshold = fields.Float(default=60.0, help="Scores at or above this value are logged for steward review.")

    _sql_constraints = [
        ("code_unique", "unique(code)", "The PIS category code must be unique."),
    ]


class TiProductAttribute(models.Model):
    _name = "ti.product.attribute"
    _description = "PIS Technical Specification"
    _order = "category_id, sequence, name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    category_id = fields.Many2one("ti.product.category", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    mandatory = fields.Boolean(default=True)
    uid_token = fields.Boolean(default=True, help="Include this specification in UID tokens when the rule asks for specs.")
    data_type = fields.Selection(
        [
            ("char", "Text"),
            ("float", "Number"),
            ("selection", "Controlled Value"),
            ("many2one", "Reference"),
        ],
        default="char",
        required=True,
    )
    value_ids = fields.One2many("ti.product.attribute.value", "attribute_id", string="Allowed Values")
    search_weight = fields.Float(default=10.0)
    help_text = fields.Char()

    _sql_constraints = [
        ("category_code_unique", "unique(category_id, code)", "Specification code must be unique per category."),
    ]


class TiProductAttributeValue(models.Model):
    _name = "ti.product.attribute.value"
    _description = "PIS Technical Specification Value"
    _order = "attribute_id, sequence, name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    attribute_id = fields.Many2one("ti.product.attribute", required=True, ondelete="cascade", index=True)
    normalized_value = fields.Char(compute="_compute_normalized_value", store=True, index=True)

    @api.depends("name", "code")
    def _compute_normalized_value(self):
        for record in self:
            record.normalized_value = normalize_text(record.code or record.name)


class TiProductSpecLine(models.Model):
    _name = "ti.product.spec.line"
    _description = "PIS Product Technical Specification Line"
    _order = "sequence, attribute_id"

    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade", index=True)
    category_id = fields.Many2one(related="product_tmpl_id.ti_category_id", store=True, index=True)
    attribute_id = fields.Many2one("ti.product.attribute", required=True, index=True)
    sequence = fields.Integer(related="attribute_id.sequence", store=True)
    value_char = fields.Char(string="Text Value")
    value_float = fields.Float(string="Numeric Value")
    value_id = fields.Many2one("ti.product.attribute.value", string="Controlled Value")
    display_value = fields.Char(compute="_compute_display_value", store=True)
    normalized_value = fields.Char(compute="_compute_display_value", store=True, index=True)

    _sql_constraints = [
        ("product_attribute_unique", "unique(product_tmpl_id, attribute_id)", "Each technical specification can appear once per product."),
    ]

    @api.depends("value_char", "value_float", "value_id", "attribute_id.data_type")
    def _compute_display_value(self):
        for line in self:
            if line.attribute_id.data_type == "float":
                value = ("%s" % line.value_float).rstrip("0").rstrip(".")
            elif line.attribute_id.data_type == "selection":
                value = line.value_id.name or ""
            else:
                value = line.value_char or ""
            line.display_value = value
            line.normalized_value = normalize_text(value)


class TiProductUidRule(models.Model):
    _name = "ti.product.uid.rule"
    _description = "PIS UID Generation Rule"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category_id = fields.Many2one("ti.product.category", index=True)
    product_type = fields.Selection(related="category_id.product_type", store=True, readonly=False)
    template = fields.Char(
        required=True,
        default="{type}-{category}-{specs}-{seq}",
        help="Allowed tokens: {type}, {category}, {specs}, {brand}, {vendor}, {seq}.",
    )
    sequence_id = fields.Many2one("ir.sequence", required=True)
    sequence_padding = fields.Integer(default=3)

    def generate_uid(self, category, spec_values=None, brand=None, vendor=None):
        self.ensure_one()
        spec_values = spec_values or {}
        seq = self.sequence_id.next_by_id()
        product_type = {
            "raw_material": "RM",
            "bought_out": "BO",
            "finished_goods": "FG",
            "consumable": "CN",
            "service": "SV",
        }.get(category.product_type, "PRD")
        spec_tokens = []
        for attribute in category.attribute_ids.filtered("uid_token").sorted("sequence"):
            value = spec_values.get(attribute.id) or spec_values.get(attribute.code)
            if value:
                spec_tokens.append(slug_token(value))
        token_map = {
            "type": product_type,
            "category": slug_token(category.code),
            "specs": "-".join(spec_tokens),
            "brand": slug_token(brand),
            "vendor": slug_token(vendor),
            "seq": str(seq).zfill(self.sequence_padding) if str(seq).isdigit() else str(seq),
        }
        uid = self.template
        for token, value in token_map.items():
            uid = uid.replace("{%s}" % token, value or "")
        uid = re.sub(r"-{2,}", "-", uid).strip("-")
        return uid


class TiProductAlias(models.Model):
    _name = "ti.product.alias"
    _description = "PIS Product Alias / Legacy Reference"
    _order = "product_tmpl_id, alias_type, name"

    name = fields.Char(required=True, index=True)
    alias_type = fields.Selection(
        [
            ("legacy_ref", "Legacy Reference"),
            ("vendor_code", "Vendor Code"),
            ("alternate_name", "Alternate Name"),
            ("brand_code", "Brand Code"),
            ("keyword", "Keyword"),
        ],
        default="alternate_name",
        required=True,
        index=True,
    )
    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one("res.partner", string="Vendor/Customer", index=True)
    normalized_name = fields.Char(compute="_compute_normalized_name", store=True, index=True)

    @api.depends("name")
    def _compute_normalized_name(self):
        for alias in self:
            alias.normalized_name = normalize_text(alias.name)


class TiProductKeyword(models.Model):
    _name = "ti.product.keyword"
    _description = "PIS Product Keyword"
    _order = "name"

    name = fields.Char(required=True, index=True)
    normalized_name = fields.Char(compute="_compute_normalized_name", store=True, index=True)
    category_id = fields.Many2one("ti.product.category", index=True)
    product_tmpl_id = fields.Many2one("product.template", ondelete="cascade", index=True)

    @api.depends("name")
    def _compute_normalized_name(self):
        for keyword in self:
            keyword.normalized_name = normalize_text(keyword.name)


class TiProductDuplicateLog(models.Model):
    _name = "ti.product.duplicate.log"
    _description = "PIS Duplicate Detection Log"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "score desc, create_date desc"

    name = fields.Char(default="Duplicate Review", required=True)
    product_tmpl_id = fields.Many2one("product.template", string="New/Source Product", index=True)
    duplicate_product_tmpl_id = fields.Many2one("product.template", string="Possible Duplicate", index=True)
    category_id = fields.Many2one("ti.product.category", index=True)
    score = fields.Float(index=True)
    reason = fields.Text()
    state = fields.Selection(
        [
            ("new", "New"),
            ("blocked", "Blocked"),
            ("review", "Needs Review"),
            ("approved", "Override Approved"),
            ("merged", "Merged"),
            ("dismissed", "Dismissed"),
        ],
        default="new",
        tracking=True,
        index=True,
    )
    override_user_id = fields.Many2one("res.users", readonly=True)
    override_date = fields.Datetime(readonly=True)

    def action_approve_override(self):
        if not self.env.user.has_group("ti_product_intelligence.group_ti_product_steward") and not self.env.user.has_group("ti_product_intelligence.group_ti_product_manager"):
            raise AccessError(_("Only Product Stewards or PIS Managers can approve duplicate overrides."))
        self.write({
            "state": "approved",
            "override_user_id": self.env.user.id,
            "override_date": fields.Datetime.now(),
        })

    def action_dismiss(self):
        self.write({"state": "dismissed"})


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ti_uid = fields.Char(string="PIS UID", copy=False, index=True, tracking=True)
    ti_legacy_ref = fields.Char(string="Legacy Reference", copy=False, index=True)
    ti_category_id = fields.Many2one("ti.product.category", string="PIS Category", index=True, tracking=True)
    ti_brand = fields.Char(string="Brand/Make", index=True)
    ti_primary_vendor_id = fields.Many2one("res.partner", string="Primary Vendor", index=True)
    ti_governance_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_review", "Pending Review"),
            ("approved", "Approved"),
            ("blocked", "Blocked"),
            ("archived", "Archived"),
        ],
        default="draft",
        index=True,
        tracking=True,
    )
    ti_spec_line_ids = fields.One2many("ti.product.spec.line", "product_tmpl_id", string="Technical Specifications")
    ti_alias_ids = fields.One2many("ti.product.alias", "product_tmpl_id", string="Aliases")
    ti_normalized_name = fields.Char(compute="_compute_ti_search_fields", store=True, index=True)
    ti_spec_search_text = fields.Text(compute="_compute_ti_search_fields", store=True)
    ti_keyword_search_text = fields.Text(compute="_compute_ti_search_fields", store=True)
    ti_duplicate_count = fields.Integer(compute="_compute_ti_duplicate_count")
    ti_latest_cost_price = fields.Float(compute="_compute_ti_prices", groups="ti_product_intelligence.group_ti_price_cost,ti_product_intelligence.group_ti_product_manager")
    ti_latest_sale_price = fields.Float(compute="_compute_ti_prices", groups="ti_product_intelligence.group_ti_price_sale,ti_product_intelligence.group_ti_product_manager")
    ti_margin_percent = fields.Float(compute="_compute_ti_prices", groups="ti_product_intelligence.group_ti_price_sale,ti_product_intelligence.group_ti_product_manager")

    _sql_constraints = [
        ("ti_uid_unique", "unique(ti_uid)", "The PIS UID/internal reference must be unique."),
    ]

    def init(self):
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS product_template_ti_keyword_search_idx ON product_template USING gin (to_tsvector('simple', coalesce(ti_keyword_search_text, '')))")
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS product_template_ti_spec_search_idx ON product_template USING gin (to_tsvector('simple', coalesce(ti_spec_search_text, '')))")

    @api.depends(
        "name",
        "ti_uid",
        "default_code",
        "ti_legacy_ref",
        "ti_brand",
        "ti_spec_line_ids.display_value",
        "ti_spec_line_ids.attribute_id.name",
        "ti_alias_ids.name",
    )
    def _compute_ti_search_fields(self):
        for product in self:
            spec_parts = []
            for line in product.ti_spec_line_ids:
                if line.display_value:
                    spec_parts.append("%s %s" % (line.attribute_id.name, line.display_value))
            alias_parts = product.ti_alias_ids.mapped("name")
            product.ti_normalized_name = normalize_text(" ".join([product.name or "", product.ti_brand or ""]))
            product.ti_spec_search_text = normalize_text(" ".join(spec_parts))
            product.ti_keyword_search_text = normalize_text(" ".join([
                product.name or "",
                product.ti_uid or "",
                product.default_code or "",
                product.ti_legacy_ref or "",
                product.ti_brand or "",
                " ".join(spec_parts),
                " ".join(alias_parts),
            ]))

    def _compute_ti_duplicate_count(self):
        groups = self.env["ti.product.duplicate.log"].read_group(
            [("product_tmpl_id", "in", self.ids), ("state", "in", ["blocked", "review", "new"])],
            ["product_tmpl_id"],
            ["product_tmpl_id"],
        )
        mapped = {row["product_tmpl_id"][0]: row["product_tmpl_id_count"] for row in groups}
        for product in self:
            product.ti_duplicate_count = mapped.get(product.id, 0)

    def _compute_ti_prices(self):
        CostHistory = self.env["product.cost.history"]
        SaleHistory = self.env["product.sale.price.history"]
        for product in self:
            cost = CostHistory.search([("product_tmpl_id", "=", product.id)], order="date desc, id desc", limit=1)
            sale = SaleHistory.search([("product_tmpl_id", "=", product.id)], order="date desc, id desc", limit=1)
            product.ti_latest_cost_price = cost.new_price if cost else product.standard_price
            product.ti_latest_sale_price = sale.new_price if sale else product.list_price
            product.ti_margin_percent = product.ti_latest_sale_price and ((product.ti_latest_sale_price - product.ti_latest_cost_price) / product.ti_latest_sale_price) * 100 or 0.0

    @api.model_create_multi
    def create(self, vals_list):
        if (
            self.env.uid != SUPERUSER_ID
            and not self.env.context.get("ti_allow_product_create")
            and self.env.user.has_group("ti_product_intelligence.group_ti_product_user")
            and not self.env.user.has_group("ti_product_intelligence.group_ti_product_steward")
            and not self.env.user.has_group("ti_product_intelligence.group_ti_product_manager")
        ):
            raise AccessError(_("Use the PIS governed product creation wizard to create products."))
        for vals in vals_list:
            if vals.get("default_code") and not vals.get("ti_legacy_ref") and not vals.get("ti_uid"):
                vals["ti_legacy_ref"] = vals["default_code"]
        products = super().create(vals_list)
        products._ti_sync_default_code()
        products._ti_create_legacy_alias()
        return products

    def write(self, vals):
        price_changes = []
        for product in self:
            price_changes.append((product, product.standard_price, product.list_price))
        result = super().write(vals)
        if "ti_uid" in vals:
            self._ti_sync_default_code()
        if "standard_price" in vals or "list_price" in vals:
            for product, old_cost, old_sale in price_changes:
                if "standard_price" in vals and product.standard_price != old_cost:
                    self.env["product.cost.history"].sudo().create_from_price_change(product, old_cost, product.standard_price, "product.template", product.id)
                if "list_price" in vals and product.list_price != old_sale:
                    self.env["product.sale.price.history"].sudo().create_from_price_change(product, old_sale, product.list_price, "product.template", product.id)
        return result

    def _ti_sync_default_code(self):
        for product in self.filtered("ti_uid"):
            if product.default_code != product.ti_uid:
                product.with_context(ti_skip_price_history=True).default_code = product.ti_uid

    def _ti_create_legacy_alias(self):
        Alias = self.env["ti.product.alias"]
        for product in self.filtered("ti_legacy_ref"):
            exists = Alias.search_count([
                ("product_tmpl_id", "=", product.id),
                ("alias_type", "=", "legacy_ref"),
                ("name", "=", product.ti_legacy_ref),
            ])
            if not exists:
                Alias.create({
                    "product_tmpl_id": product.id,
                    "alias_type": "legacy_ref",
                    "name": product.ti_legacy_ref,
                })

    @api.constrains("ti_category_id", "ti_spec_line_ids")
    def _check_mandatory_specs(self):
        for product in self.filtered("ti_category_id"):
            missing = []
            lines_by_attribute = {line.attribute_id.id: line for line in product.ti_spec_line_ids}
            for attribute in product.ti_category_id.attribute_ids.filtered("mandatory"):
                line = lines_by_attribute.get(attribute.id)
                if not line or not line.display_value:
                    missing.append(attribute.name)
            if missing and product.ti_governance_state in ("pending_review", "approved"):
                raise ValidationError(_("Missing mandatory technical specifications: %s") % ", ".join(missing))

    def ti_find_duplicate_candidates(self, category=None, normalized_name=None, spec_text=None, limit=20):
        self.ensure_one()
        category = category or self.ti_category_id
        normalized_name = normalized_name or self.ti_normalized_name
        spec_text = spec_text or self.ti_spec_search_text
        domain = [("id", "!=", self.id)]
        if category:
            domain.append(("ti_category_id", "=", category.id))
        search_text = " ".join([normalized_name or "", spec_text or ""]).strip()
        if search_text:
            token_domains = []
            for token in search_text.split(" ")[:8]:
                token_domains.append(("ti_keyword_search_text", "ilike", token))
            if token_domains:
                domain = expression.AND([domain, expression.OR(token_domains)])
        candidates = self.search(domain, limit=limit)
        return self._ti_score_duplicates(candidates, normalized_name, spec_text)

    def _ti_score_duplicates(self, candidates, normalized_name, spec_text):
        self.ensure_one()
        results = []
        source_text = " ".join([normalized_name or "", spec_text or ""]).strip()
        for candidate in candidates:
            target_text = " ".join([candidate.ti_normalized_name or "", candidate.ti_spec_search_text or ""]).strip()
            name_score = SequenceMatcher(None, normalized_name or "", candidate.ti_normalized_name or "").ratio() * 100
            spec_score = SequenceMatcher(None, spec_text or "", candidate.ti_spec_search_text or "").ratio() * 100
            full_score = SequenceMatcher(None, source_text, target_text).ratio() * 100
            alias_score = 0
            source_aliases = set(self.ti_alias_ids.mapped("normalized_name"))
            target_aliases = set(candidate.ti_alias_ids.mapped("normalized_name"))
            if source_aliases and source_aliases.intersection(target_aliases):
                alias_score = 100
            score = max(full_score, (name_score * 0.45) + (spec_score * 0.45) + (alias_score * 0.10))
            reasons = []
            if name_score >= 75:
                reasons.append(_("similar name"))
            if spec_score >= 75:
                reasons.append(_("similar technical specifications"))
            if alias_score:
                reasons.append(_("matching alias/vendor code"))
            results.append({
                "product": candidate,
                "score": round(score, 2),
                "reason": ", ".join(reasons) or _("keyword similarity"),
            })
        return sorted(results, key=lambda item: item["score"], reverse=True)

    def action_generate_pis_uid(self):
        for product in self:
            if not product.ti_category_id:
                raise ValidationError(_("Select a PIS category before generating UID."))
            rule = product.ti_category_id.uid_rule_id
            if not rule:
                raise ValidationError(_("Configure a UID rule for category %s.") % product.ti_category_id.name)
            spec_values = {line.attribute_id.id: line.display_value for line in product.ti_spec_line_ids}
            product.ti_uid = rule.generate_uid(product.ti_category_id, spec_values, product.ti_brand, product.ti_primary_vendor_id.name)
        return True

    def action_open_duplicate_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Duplicate Logs"),
            "res_model": "ti.product.duplicate.log",
            "view_mode": "tree,form",
            "domain": [("product_tmpl_id", "=", self.id)],
        }

    def _cron_ti_duplicate_scan(self):
        Log = self.env["ti.product.duplicate.log"].sudo()
        for product in self:
            candidates = product.ti_find_duplicate_candidates(limit=20)
            review_threshold = product.ti_category_id.review_threshold or 60.0
            duplicate_threshold = product.ti_category_id.duplicate_threshold or 85.0
            for item in candidates:
                if item["score"] < review_threshold:
                    continue
                exists = Log.search_count([
                    ("product_tmpl_id", "=", product.id),
                    ("duplicate_product_tmpl_id", "=", item["product"].id),
                    ("state", "in", ["new", "review", "blocked"]),
                ])
                if exists:
                    continue
                Log.create({
                    "product_tmpl_id": product.id,
                    "duplicate_product_tmpl_id": item["product"].id,
                    "category_id": product.ti_category_id.id,
                    "score": item["score"],
                    "reason": item["reason"],
                    "state": "blocked" if item["score"] >= duplicate_threshold else "review",
                })
        return True


class ProductProduct(models.Model):
    _inherit = "product.product"

    def name_get(self):
        result = []
        for product in self:
            template = product.product_tmpl_id
            label = template.name
            if template.ti_uid:
                label = "[%s] %s" % (template.ti_uid, label)
            elif product.default_code:
                label = "[%s] %s" % (product.default_code, label)
            result.append((product.id, label))
        return result

    @api.model
    def _name_search(self, name="", args=None, operator="ilike", limit=100, name_get_uid=None):
        args = args or []
        if name:
            normalized = normalize_text(name)
            template_domain = expression.OR([
                [("ti_uid", operator, name)],
                [("default_code", operator, name)],
                [("ti_legacy_ref", operator, name)],
                [("ti_keyword_search_text", "ilike", normalized)],
                [("ti_alias_ids.normalized_name", "ilike", normalized)],
            ])
            templates = self.env["product.template"].search(template_domain, limit=limit)
            if templates:
                product_domain = expression.AND([[("product_tmpl_id", "in", templates.ids)], args])
                return self._search(product_domain, limit=limit, access_rights_uid=name_get_uid)
        return super()._name_search(name=name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid)
