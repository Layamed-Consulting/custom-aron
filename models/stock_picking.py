from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        res = super().button_validate()

        for picking in self:
            sale = picking.sale_id
            if not sale:
                continue

            # Create & post invoice (already working)
            if any(move.product_id.invoice_policy == 'delivery' for move in picking.move_ids) or not sale.invoice_ids:
                invoices = sale._create_invoices()
                if invoices:
                    invoices.action_post()

            # Update stock.website.order status
            website_orders = self.env['stock.website.order'].search([
                ('sale_order_ref', '=', sale.name)
            ])

            if website_orders:
                website_orders.write({
                    'status': 'ready_to_delivery'
                })

        return res

class StockPickingBatch(models.Model):
    _inherit = 'stock.picking.batch'

    def _get_or_create_package(self, package_name):
        """
        Get existing package or create new one if it doesn't exist.
        Package will be reusable.
        """
        # Search for existing package with this name
        package = self.env['stock.quant.package'].search([
            ('name', '=', package_name)
        ], limit=1)

        if package:
            _logger.info(f"Reusing existing package: {package_name}")
            return package

        # Create new package if it doesn't exist
        package = self.env['stock.quant.package'].create({
            'name': package_name,
            'package_use': 'reusable',  # Set as reusable
        })
        _logger.info(f"Created new reusable package: {package_name}")

        return package

    def action_generate_destination_packages(self):
        """
        Generate or reuse destination packages for each picking in the batch.
        All move lines with the same picking_id get the same result_package_id.
        Package format: TR-001, TR-002, etc.
        Packages are reusable across different batches.
        """
        self.ensure_one()

        if not self.picking_ids:
            raise UserError(_("Il n'y a aucun transfert dans ce batch."))

        packages_created = 0
        packages_reused = 0
        picking_package_map = {}
        package_counter = 1  # Start from TR-001

        _logger.info(f"Starting package generation for batch {self.name}")

        for picking in self.picking_ids:
            # Check if picking has move lines
            if not picking.move_line_ids:
                _logger.warning(f"Picking {picking.name} has no move lines, skipping")
                continue

            # Check if this picking already has packages assigned
            existing_packages = picking.move_line_ids.mapped('result_package_id')
            if existing_packages:
                _logger.info(
                    f"Picking {picking.name} already has packages assigned: {existing_packages.mapped('name')}")
                continue

            # Generate package name
            package_name = f'TR-{package_counter:03d}'

            # Get or create the package
            package = self._get_or_create_package(package_name)

            # Track if package was created or reused
            if package.create_date.date() == fields.Date.today():
                # Check if it was just created (today)
                # This is a simple check, you might want to refine this
                was_existing = self.env['stock.quant.package'].search_count([
                    ('name', '=', package_name),
                    ('create_date', '<', fields.Datetime.now())
                ]) > 0

                if was_existing:
                    packages_reused += 1
                else:
                    packages_created += 1
            else:
                packages_reused += 1

            # Assign this package to all move lines of this picking
            move_lines_updated = 0
            for move_line in picking.move_line_ids:
                move_line.write({
                    'result_package_id': package.id
                })
                move_lines_updated += 1

            _logger.info(f"Assigned package {package_name} to {move_lines_updated} move lines in {picking.name}")

            picking_package_map[picking.name] = package_name
            package_counter += 1

        # Prepare message for notification
        message_lines = [
            f"{packages_created} nouveau(x) package(s) créé(s)",
            f"{packages_reused} package(s) réutilisé(s)",
            "Attribution:"
        ]
        for picking_name, package_name in picking_package_map.items():
            message_lines.append(f"• {picking_name} → {package_name}")


        total_packages = packages_created + packages_reused
        _logger.info(f"Package assignment completed: {packages_created} created, {packages_reused} reused")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Packages Assignés',
                'message': f"package(s) créé(s)",
                'type': 'success',
                'sticky': False
            }
        }
