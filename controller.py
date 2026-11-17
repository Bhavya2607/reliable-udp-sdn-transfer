from collections import deque
import json
import socket
from os_ken.lib import hub
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, ether_types

HOST_A = ('10.0.0.1', '00:00:00:00:00:01', 1)
HOST_B = ('10.0.0.2', '00:00:00:00:00:04', 1)
# (switch DPID, switch port) pairs for each inter-switch link.
LINK_PORTS = {
    (1, 2): ((1, 2), (2, 1)),
    (1, 3): ((1, 3), (3, 1)),
    (2, 4): ((2, 2), (4, 2)),
    (3, 4): ((3, 2), (4, 3)),
}


class ReliableTransferController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.down_ports = set()
        self.active_path = []
        self.flow_stats = {}
        self.telemetry_thread = hub.spawn(self._telemetry_loop)
        self.stats_thread = hub.spawn(self._stats_loop)

    def _telemetry_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', 9999))
        self.logger.info('Application telemetry listening on UDP/9999')
        while True:
            data, addr = sock.recvfrom(4096)
            try:
                event = json.loads(data.decode())
                if event.get('event') == 'transfer_stall':
                    self.logger.warning('Application stall report from %s: session=%s base=%s expired=%s', addr, event.get('session'), event.get('base'), event.get('expired'))
                elif event.get('event') == 'status':
                    sock.sendto(json.dumps({'active_path': self.active_path, 'down_ports': sorted([list(x) for x in self.down_ports])}).encode(), addr)
            except (ValueError, UnicodeDecodeError):
                self.logger.warning('Invalid application telemetry from %s', addr)

    def _stats_loop(self):
        while True:
            hub.sleep(5)
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                dp.send_msg(parser.OFPFlowStatsRequest(dp))

    def _graph(self):
        graph = {1: [], 2: [], 3: [], 4: []}
        for (a, b), (pa, pb) in LINK_PORTS.items():
            if (a, pa[1]) not in self.down_ports and (b, pb[1]) not in self.down_ports:
                graph[a].append(b)
                graph[b].append(a)
        return graph

    def _path(self):
        graph = self._graph()
        queue = deque([(1, [1])])
        seen = {1}
        while queue:
            node, path = queue.popleft()
            if node == 4:
                return path
            for nxt in graph[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, path + [nxt]))
        return []

    def _port_between(self, a, b):
        pair = LINK_PORTS.get((min(a, b), max(a, b)))
        if not pair:
            return None
        return pair[0][1] if a < b else pair[1][1]

    def _send_flow(self, dp, match, out_port, priority=100):
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        actions = [parser.OFPActionOutput(out_port)]
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=inst, idle_timeout=0, hard_timeout=0))

    def _install_direction(self, src_ip, dst_ip, path, reverse=False):
        if not path:
            return
        source = HOST_B if reverse else HOST_A
        destination = HOST_A if reverse else HOST_B
        nodes = list(reversed(path)) if reverse else path
        for index, dpid in enumerate(nodes):
            dp = self.datapaths.get(dpid)
            if dp is None:
                continue
            in_port = source[2] if index == 0 else self._port_between(dpid, nodes[index - 1])
            out_port = destination[2] if index == len(nodes) - 1 else self._port_between(dpid, nodes[index + 1])
            if in_port is None or out_port is None:
                continue
            parser = dp.ofproto_parser
            match_fields = {'in_port': in_port, 'eth_type': 0x0800, 'ipv4_src': src_ip, 'ipv4_dst': dst_ip, 'ip_proto': 17}
            if reverse:
                match_fields['udp_src'] = 5001
            else:
                match_fields['udp_dst'] = 5001
            self._send_flow(dp, parser.OFPMatch(**match_fields), out_port)
            arp_fields = {
                'in_port': in_port,
                'eth_type': 0x0806,
                'arp_op': 2 if reverse else 1,
                'arp_spa': src_ip,
                'arp_tpa': dst_ip,
            }
            self._send_flow(dp, parser.OFPMatch(**arp_fields), out_port)

    def _refresh_routes(self):
        path = self._path()
        if path != self.active_path:
            self.logger.info('SDN path changed: %s', path if path else 'NO PATH')
        self.active_path = path
        for dp in self.datapaths.values():
            ofp = dp.ofproto
            parser = dp.ofproto_parser
            # Remove only IPv4 forwarding entries; preserve table-miss and non-IPv4 control rules.
            dp.send_msg(parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE, out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY, match=parser.OFPMatch(eth_type=0x0800), table_id=ofp.OFPTT_ALL))
            miss_actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
            miss_inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, miss_actions)]
            dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0, match=parser.OFPMatch(), instructions=miss_inst))
        if path:
            self._install_direction('10.0.0.1', '10.0.0.2', path)
            self._install_direction('10.0.0.2', '10.0.0.1', path, reverse=True)
            self.logger.info('Installed UDP file-transfer routes over %s', path)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.logger.info('Switch connected: %s', dp.id)
            if len(self.datapaths) == 4:
                self._refresh_routes()
        elif ev.state == CONFIG_DISPATCHER:
            self.datapaths.pop(dp.id, None)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        dp = ev.msg.datapath
        port = ev.msg.desc.port_no
        key = (dp.id, port)
        down = bool(ev.msg.desc.state & dp.ofproto.OFPPS_LINK_DOWN)
        if key in {(1, 2), (1, 3), (2, 1), (2, 2), (3, 1), (3, 2), (4, 2), (4, 3)}:
            if down:
                self.down_ports.add(key)
                self.logger.warning('Link port down: switch=%s port=%s', dp.id, port)
            else:
                self.down_ports.discard(key)
                self.logger.info('Link port up: switch=%s port=%s', dp.id, port)
            self._refresh_routes()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        parser = dp.ofproto_parser
        ofp = dp.ofproto
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=0, match=parser.OFPMatch(), instructions=inst))

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        # Unknown/unmatched traffic is intentionally dropped: flooding a diamond
        # topology can create loops and duplicate application datagrams.
        self.logger.debug('Dropping unmatched packet: switch=%s in_port=%s ethertype=%s', dp.id, msg.match.get('in_port'), eth.ethertype if eth else 'unknown')

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        dp = ev.msg.datapath
        totals = {'packets': 0, 'bytes': 0}
        for stat in ev.msg.body:
            if stat.priority > 0:
                totals['packets'] += stat.packet_count
                totals['bytes'] += stat.byte_count
        self.flow_stats[dp.id] = totals
        self.logger.info('Flow stats switch=%s packets=%s bytes=%s', dp.id, totals['packets'], totals['bytes'])
