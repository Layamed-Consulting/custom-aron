# -*- coding: utf-8 -*-
from odoo import models


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
