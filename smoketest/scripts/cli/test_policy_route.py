#!/usr/bin/env python3
#
# Copyright (C) 2021-2022 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import unittest

from base_vyostest_shim import VyOSUnitTestSHIM

from vyos.util import cmd

mark = '100'
table_mark_offset = 0x7fffffff
table_id = '101'
interface = 'eth0'
interface_ip = '172.16.10.1/24'

class TestPolicyRoute(VyOSUnitTestSHIM.TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestPolicyRoute, cls).setUpClass()

        cls.cli_set(cls, ['interfaces', 'ethernet', interface, 'address', interface_ip])
        cls.cli_set(cls, ['protocols', 'static', 'table', table_id, 'route', '0.0.0.0/0', 'interface', interface])

    @classmethod
    def tearDownClass(cls):
        cls.cli_delete(cls, ['interfaces', 'ethernet', interface, 'address', interface_ip])
        cls.cli_delete(cls, ['protocols', 'static', 'table', table_id])

        super(TestPolicyRoute, cls).tearDownClass()

    def tearDown(self):
        self.cli_delete(['interfaces', 'ethernet', interface, 'policy'])
        self.cli_delete(['policy', 'route'])
        self.cli_delete(['policy', 'route6'])
        self.cli_commit()

        nftables_search = [
            ['set N_smoketest_network'],
            ['set N_smoketest_network1'],
            ['chain VYOS_PBR_smoketest']
        ]

        self.verify_nftables(nftables_search, 'ip filter', inverse=True)

    def verify_nftables(self, nftables_search, table, inverse=False):
        nftables_output = cmd(f'sudo nft list table {table}')

        for search in nftables_search:
            matched = False
            for line in nftables_output.split("\n"):
                if all(item in line for item in search):
                    matched = True
                    break
            self.assertTrue(not matched if inverse else matched, msg=search)

    def test_pbr_group(self):
        self.cli_set(['firewall', 'group', 'network-group', 'smoketest_network', 'network', '172.16.99.0/24'])
        self.cli_set(['firewall', 'group', 'network-group', 'smoketest_network1', 'network', '172.16.101.0/24'])
        self.cli_set(['firewall', 'group', 'network-group', 'smoketest_network1', 'include', 'smoketest_network'])

        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'source', 'group', 'network-group', 'smoketest_network'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'destination', 'group', 'network-group', 'smoketest_network1'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'set', 'mark', mark])

        self.cli_set(['interfaces', 'ethernet', interface, 'policy', 'route', 'smoketest'])

        self.cli_commit()

        nftables_search = [
            [f'iifname "{interface}"','jump VYOS_PBR_smoketest'],
            ['ip daddr @N_smoketest_network1', 'ip saddr @N_smoketest_network'],
        ]

        self.verify_nftables(nftables_search, 'ip mangle')

        self.cli_delete(['firewall'])

    def test_pbr_mark(self):
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'source', 'address', '172.16.20.10'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'destination', 'address', '172.16.10.10'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'set', 'mark', mark])

        self.cli_set(['interfaces', 'ethernet', interface, 'policy', 'route', 'smoketest'])

        self.cli_commit()

        mark_hex = "{0:#010x}".format(int(mark))

        nftables_search = [
            [f'iifname "{interface}"','jump VYOS_PBR_smoketest'],
            ['ip daddr 172.16.10.10', 'ip saddr 172.16.20.10', 'meta mark set ' + mark_hex],
        ]

        self.verify_nftables(nftables_search, 'ip mangle')

    def test_pbr_table(self):
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'protocol', 'tcp'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'destination', 'port', '8888'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'tcp', 'flags', 'syn'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'tcp', 'flags', 'not', 'ack'])
        self.cli_set(['policy', 'route', 'smoketest', 'rule', '1', 'set', 'table', table_id])
        self.cli_set(['policy', 'route6', 'smoketest6', 'rule', '1', 'protocol', 'tcp_udp'])
        self.cli_set(['policy', 'route6', 'smoketest6', 'rule', '1', 'destination', 'port', '8888'])
        self.cli_set(['policy', 'route6', 'smoketest6', 'rule', '1', 'set', 'table', table_id])

        self.cli_set(['interfaces', 'ethernet', interface, 'policy', 'route', 'smoketest'])
        self.cli_set(['interfaces', 'ethernet', interface, 'policy', 'route6', 'smoketest6'])

        self.cli_commit()

        mark_hex = "{0:#010x}".format(table_mark_offset - int(table_id))

        # IPv4

        nftables_search = [
            [f'iifname "{interface}"', 'jump VYOS_PBR_smoketest'],
            ['tcp flags & (syn | ack) == syn', 'tcp dport { 8888 }', 'meta mark set ' + mark_hex]
        ]

        self.verify_nftables(nftables_search, 'ip mangle')

        # IPv6

        nftables6_search = [
            [f'iifname "{interface}"', 'jump VYOS_PBR6_smoketest'],
            ['meta l4proto { tcp, udp }', 'th dport { 8888 }', 'meta mark set ' + mark_hex]
        ]

        self.verify_nftables(nftables6_search, 'ip6 mangle')

        # IP rule fwmark -> table

        ip_rule_search = [
            ['fwmark ' + hex(table_mark_offset - int(table_id)), 'lookup ' + table_id]
        ]

        ip_rule_output = cmd('ip rule show')

        for search in ip_rule_search:
            matched = False
            for line in ip_rule_output.split("\n"):
                if all(item in line for item in search):
                    matched = True
                    break
            self.assertTrue(matched)


if __name__ == '__main__':
    unittest.main(verbosity=2)
