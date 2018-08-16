# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Enterprise Management Solution, third party addon
#    Copyright (C) 2017- Vertel AB (<http://vertel.se>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import models, fields, api, _
from lxml import etree
import base64
from odoo.exceptions import Warning
import time
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)


# order must be correct
TAGS = [
    'LonBrutto',        #50: Avgiftspliktig bruttolön utom förmåner
    'Forman',           #51: Avgiftspliktiga förmåner
    'AvdrKostn',        #52: Avdrag för utgifter
    'SumUlagAvg',       #53: Sammanlagt underlag för arbetsgivaravgifter och särskild löneskatt
    'UlagAvgHel',       #55:  san  Full arbetsgivaravgift för födda 1953 eller senare (55 = 53 - 57 - 59 - 61 - 65 - 69)
    'AvgHel',           #56: (san) 31,42% av #55
    'UlagAvgAldersp',   #59:  sap  Arbetsgivaravgift för 66-80 år
    'AvgAldersp',       #60: (sap) 16,36% av #59
    'UlagAlderspSkLon', #57??
    'AvgAlderspSkLon',  #58??
    # ~ 'UlagSkLonSarsk',   #61:  sapx Särskild löneskatt för 81 år eller äldre
    # ~ 'SkLonSarsk',       #62: (sapx)6,15% av #61
    # ~ 'UlagAvgAmbassad',  #65: Ambassader och företag utan fast driftställe i Sverige samt särskild löneskatt på vissa försäkringar m.m.
    # ~ 'AvgAmbassad',      #66: Se uträkningsruta
    # ~ 'KodAmerika',       #67: Kod USA, Kanada, Québec m.fl.
    # ~ 'UlagAvgAmerika',   #69:
    # ~ 'AvgAmerika',       #70: Se uträkningsruta
    'UlagStodForetag',  #73: Forskning och utveckling
    'AvdrStodForetag',  #74: Avdrag 10%, dock högst 230000 kr
    'UlagStodUtvidgat', #75: Regionalt stöd för vissa branscher i stödområde
    'AvdrStodUtvidgat', #76: Avdrag 10%, dock högst 7100 kr
    'SumAvgBetala',     #78: Summa arbetsgivaravgifter
    'UlagSkAvdrLon',    #81: Lön och förmåner inkl. SINK
    'SkAvdrLon',        #82: Från lön och förmåner
    # ~ 'UlagSkAvdrPension',#83: Pension, livränta, försäkringsersättning inkl. SINK
    # ~ 'SkAvdrPension',    #84: Från pension m.m.
    # ~ 'UlagSkAvdrRanta',  #85: Ränta och utdelning
    # ~ 'SkAvdrRanta',      #86: Från ränta och utdelning
    'UlagSumSkAvdr',    #87: Summa underlag för skatteanvdrag
    'SumSkAvdr',        #88: Summa avdragen skatt
    # ~ 'SjukLonKostnEhs'   #99: Summa arbetsgivaravgifter och avdragen skatt att betala
]

class account_agd_declaration(models.Model):
    _name = 'account.agd.declaration'
    _inherits = {'account.declaration.line.id': 'line_id'}
    _inherit = 'account.declaration'
    _report_name = 'Agd'

    line_id = fields.Many2one('account.declaration.line.id', auto_join=True, index=True, ondelete="cascade", required=True)
    def _period_start(self):
        return  self.get_next_periods()[0]
    period_start = fields.Many2one(comodel_name='account.period', string='Start period', required=True,default=_period_start)
    # ~ period_stop = fields.Many2one(comodel_name='account.period', string='Slut period',default=_period_stop)
    move_ids = fields.One2many(comodel_name='account.move',inverse_name="agd_declaration_id")
    line_ids = fields.One2many(comodel_name='account.declaration.line',inverse_name="agd_declaration_id")

    @api.multi
    def show_journal_entries(self):
        ctx = {
            'period_start': self.period_start.id,
            'period_stop': self.period_start.id,
            'accounting_yearend': self.accounting_yearend,
            'accounting_method': self.accounting_method,
            'target_move': self.target_move,
        }
        action = self.env['ir.actions.act_window'].for_xml_id('account', 'action_move_journal_line')
        action.update({
            'display_name': _('Verifikat'),
            'domain': [('id', 'in', self.move_ids.mapped('id'))],
            'context': ctx,
        })
        return action

    @api.onchange('period_start')
    def onchange_period_start(self):
        if self.period_start:
            # ~ self.accounting_yearend = (self.period_start == self.fiscalyear_id.period_ids[-1] if self.fiscalyear_id else None)
            # ~ self.period_stop = self.period_start
            self.date = fields.Date.to_string(fields.Date.from_string(self.period_start.date_stop) + timedelta(days=12))
            self.name = '%s %s' % (self._report_name,self.env['account.period'].period2month(self.period_start,short=False))

    @api.onchange('period_start','target_move','accounting_method','accounting_yearend')
    def _vat(self):
        for decl in self:
            if decl.period_start:
                ctx = {
                    'period_start': decl.period_start.id,
                    'period_stop': decl.period_start.id,
                    'accounting_yearend': decl.accounting_yearend,
                    'accounting_method': decl.accounting_method,
                    'target_move': decl.target_move,
                }
                decl.SumSkAvdr = round(self.env.ref('l10n_se_tax_report.agd_report_SumSkAvdr').with_context(ctx).sum_tax_period()) * -1.0
                decl.SumAvgBetala = round(self.env.ref('l10n_se_tax_report.agd_report_SumAvgBetala').with_context(ctx).sum_tax_period()) * -1.0
                decl.ag_betala = decl.SumAvgBetala + decl.SumSkAvdr

    SumSkAvdr    = fields.Float(compute='_vat')
    SumAvgBetala = fields.Float(compute='_vat')
    ag_betala  = fields.Float(compute='_vat')

    @api.multi
    def show_SumSkAvdr(self):
        ctx = {
                'period_start': self.period_start.id,
                'period_stop': self.period_start.id,
                'accounting_yearend': self.accounting_yearend,
                'accounting_method': self.accounting_method,
                'target_move': self.target_move,
            }
        action = self.env['ir.actions.act_window'].for_xml_id('account', 'action_account_moves_all_a')
        action.update({
            'display_name': _('VAT Ag'),
            'domain': [('id', 'in', self.env.ref('l10n_se_tax_report.agd_report_SumSkAvdr').with_context(ctx).get_taxlines().mapped('id'))],
            'context': {},
        })
        return action

    @api.multi
    def show_SumAvgBetala(self):
        ctx = {
                'period_start': self.period_start.id,
                'period_stop': self.period_start.id,
                'accounting_yearend': self.accounting_yearend,
                'accounting_method': self.accounting_method,
                'target_move': self.target_move,
            }
        action = self.env['ir.actions.act_window'].for_xml_id('account', 'action_account_moves_all_a')
        action.update({
            'display_name': _('VAT Ag'),
            'domain': [('id', 'in', self.env.ref('l10n_se_tax_report.agd_report_SumAvgBetala').with_context(ctx).get_taxlines().mapped('id'))],
            'context': {},
        })
        return action

    @api.one
    def do_draft(self):
        super(account_agd_declaration, self).do_draft()
        for move in self.move_ids:
            move.agd_declaration_id = None

    @api.one
    def do_cancel(self):
        super(account_agd_declaration, self).do_draft()
        for move in self.move_ids:
            move.agd_declaration_id = None

    @api.one
    def calculate(self): # make a short cut to print financial report
        if self.state not in ['draft']:
            raise Warning("Du kan inte beräkna i denna status, ändra till utkast")
        if self.state in ['draft']:
            self.state = 'confirmed'
        ctx = {
            'period_start': self.period_start.id,
            'period_stop': self.period_start.id,
            'accounting_yearend': self.accounting_yearend,
            'accounting_method': self.accounting_method,
            'target_move': self.target_move,
        }

        ##
        ####  Create report lines
        ##

        for row in TAGS:
            line = self.env.ref('l10n_se_tax_report.agd_report_%s' % row)
            if not line:
                raise Warning(_('Report line missing %' % row))
            self.env['account.declaration.line'].create({
                'agd_declaration_id': self.id,
                'balance': int(abs(line.with_context(ctx).sum_tax_period() if line.tax_ids else sum([a.with_context(ctx).sum_period() for a in line.account_ids])) or 0.0),
                'name': line.name,
                'level': line.level,
                'move_line_ids': [(6,0,line.with_context(ctx).get_moveline_ids())],
                })

        ##
        #### Mark Used moves
        ##

        for move in self.line_ids.mapped('move_line_ids').mapped('move_id'):
            if not move.agd_declaration_id:
                move.agd_declaration_id = self.id
            else:
                raise Warning(_('Move %s is already assigned to %s' % (move.name, move.agd_declaration_id.name)))

        ##
        #### Create eSDK-file
        ##

        tax_account = self.env['account.tax'].search([('tax_group_id', '=', self.env.ref('l10n_se.tax_group_hr').id), ('name', 'not in', ['eSKDUpload', 'Ag', 'AgBrutU', 'AgAvgU', 'AgAvgAv', 'AgAvg', 'AgAvd', 'AgAvdU', 'AgAvgPreS', 'AgPre', 'UlagVXLon', 'AvgVXLon'])])
        def parse_xml(recordsets):
            root = etree.Element('eSKDUpload', Version="6.0")
            orgnr = etree.SubElement(root, 'OrgNr')
            orgnr.text = self.env.user.company_id.company_registry
            ag = etree.SubElement(root, 'Ag')
            period = etree.SubElement(ag, 'Period')
            period.text = self.period_start.date_start[:4] + self.period_start.date_start[5:7]
            for row in TAGS:
                line = self.env.ref('l10n_se_tax_report.agd_report_%s' % row)
                tax = etree.SubElement(ag, row)
                tax.text = str(int(abs((line.with_context(ctx).sum_tax_period() if line.tax_ids else sum([a.with_context(ctx).sum_period() for a in line.account_ids])) * line.sign))) or '0'
            free_text = etree.SubElement(ag, 'TextUpplysningAg')
            free_text.text = self.free_text or ''
            return root
        xml = etree.tostring(parse_xml(tax_account), pretty_print=True, encoding="ISO-8859-1")
        xml = xml.replace('?>', '?>\n<!DOCTYPE eSKDUpload PUBLIC "-//Skatteverket, Sweden//DTD Skatteverket eSKDUpload-DTD Version 6.0//SV" "https://www.skatteverket.se/download/18.3f4496fd14864cc5ac99cb1/1415022101213/eSKDUpload_6p0.dtd">')
        self.eskd_file = base64.b64encode(xml)

        ##
        #### Create move
        ##

        #TODO check all warnings
        tax_accounts = self.env['account.tax'].with_context({'period_id': self.period_start.id, 'state': self.target_move}).search([('name', '=', 'AgAvgPreS')])
        kontoskatte = self.env['account.account'].with_context({'period_from': self.period_start.id, 'period_to': self.period_start.id}).search([('id', 'in', self.env['account.financial.report'].search([('tax_ids', 'in', tax_accounts.mapped('children_tax_ids').mapped('id'))]).mapped('account_ids').mapped('id'))])
        agd_journal_id = self.env['ir.config_parameter'].get_param('l10n_se_tax_report.agd_journal')
        if not agd_journal_id:
            raise Warning('Konfigurera din arbetsgivardeklaration journal!')
        else:
            agd_journal = self.env['account.journal'].browse(int(agd_journal_id))
            skattekonto = agd_journal.default_debit_account_id
            if len(kontoskatte) > 0 and skattekonto:
                total = 0.0
                entry = self.env['account.move'].create({
                    'journal_id': agd_journal.id,
                    'period_id': self.period_start.id,
                    'date': fields.Date.today(),
                    'ref': u'Arbetsgivardeklaration',
                })
                if entry:
                    move_line_list = []
                    for k in kontoskatte:
                        credit = k.with_context(ctx).sum_period()
                        if credit != 0.0:
                            move_line_list.append((0, 0, {
                                'name': k.name,
                                'account_id': k.id,
                                'debit': int(round(abs(credit))),
                                'credit': 0.0,
                                'move_id': entry.id,
                            }))
                            total += credit
                    move_line_list.append((0, 0, {
                        'name': skattekonto.name,
                        'account_id': skattekonto.id,
                        'partner_id': self.env.ref('base.res_partner-SKV').id,
                        'debit': 0.0,
                        'credit': int(round(abs(total))),
                        'move_id': entry.id,
                    }))
                    entry.write({
                        'line_ids': move_line_list,
                    })
                    self.write({'move_id': entry.id})
            else:
                raise Warning(_('kontoskatte: %sst, skattekonto: %s') %(len(kontoskatte), skattekonto))

    @api.model
    def get_next_periods(self,length=1):
        last_declaration = self.search([],order='date_stop desc',limit=1)
        _logger.warn('get_netx_period date_stop %s >>> %s | %s' % (last_declaration.date_stop,self.search([],order='date_stop asc').mapped('date_stop'),self.search([],order='date_stop desc').mapped('name')))
        return self.env['account.period'].get_next_periods(last_declaration.period_start if last_declaration else None, 1)


class account_move(models.Model):
    _inherit = 'account.move'

    agd_declaration_id = fields.Many2one(comodel_name="account.agd.declaration")


class account_declaration_line(models.Model):
    _inherit = 'account.declaration.line'

    agd_declaration_id = fields.Many2one(comodel_name="account.agd.declaration")
