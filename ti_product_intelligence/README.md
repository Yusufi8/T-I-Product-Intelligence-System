# T&I Product Intelligence System

`ti_product_intelligence` is an Odoo 16 addon for product master data governance at T&I Projects Limited.

## What It Implements

- Controlled product creation wizard for governed products.
- Category-specific technical specification templates.
- Configurable UID generation rules using product type, category, specs, brand, vendor, and sequence.
- Duplicate detection using normalized names, aliases, vendor codes, category, and technical specs.
- Legacy internal reference preservation through `ti_legacy_ref` and `ti.product.alias`.
- Product search extension for UID, legacy reference, aliases, and normalized specification text.
- Cost and sale price history models populated from product price edits, purchase confirmations, and sale confirmations.
- Security groups for Sales, Purchase, Inventory, Manufacturing, Product Stewards, and Director/Admin.
- Product governance dashboards using Odoo graph and pivot views.
- Migration and merge wizards for legacy cleanup.

## Operational Workflow

1. Configure PIS categories and technical specifications.
2. Configure or reuse UID rules.
3. Assign users to PIS security groups.
4. Use **Product Intelligence > Operations > Create Governed Product** or the PO/SO governed product button.
5. Run duplicate check before creation.
6. Product Stewards review blocked or medium-confidence duplicate logs.
7. Run migration cleanup in batches for existing `product.template` records.

## Migration Policy

Existing `default_code` values are preserved in `ti_legacy_ref` and as `ti.product.alias` records. PIS UID assignment is generated separately so legacy references remain searchable and auditable.

## Performance Notes

The module stores normalized search fields and creates PostgreSQL GIN indexes for specification and keyword search text. Duplicate scans are batched by scheduled action to avoid large synchronous jobs.

## Test Coverage

The included transaction tests cover UID generation, legacy reference preservation, duplicate similarity for reordered product names, and wizard duplicate detection.

