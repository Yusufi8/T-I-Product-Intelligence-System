# T&I Product Intelligence System for Odoo 16

Enterprise product governance addon for T&I Projects Limited.

This repository contains the Odoo 16 module `ti_product_intelligence`, designed for product master data governance, intelligent UID generation, duplicate prevention, technical specification standardization, PO/SO search acceleration, price history, and Purchase/Sales/Inventory/Manufacturing integration.

## Module

Copy `ti_product_intelligence` into an Odoo 16 addons path, update the app list, then install **T&I Product Intelligence System**.

Required Odoo apps:

- Product
- Purchase
- Sales
- Inventory
- Manufacturing
- Discuss/Mail

## Main Capabilities

- Governed product creation wizard.
- Category-driven technical specifications.
- Configurable UID rules.
- Duplicate detection and duplicate review logs.
- Legacy internal reference preservation.
- Alias, vendor code, and spec-based product search.
- Cost and selling price history.
- Role-based price visibility.
- Product governance dashboards.
- Legacy migration cleanup and merge wizards.

## Validation Performed

- Python syntax compilation.
- XML well-formedness validation.
- Manifest file existence validation.

Full Odoo installation tests should be run inside an Odoo 16 database with `sale_management`, `purchase`, `stock`, and `mrp` installed.

