from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.ofproto import ofproto_v1_3
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.ofp_pktinfilter import packet_in_filter, RequiredTypeFilter
from fwd_util import FwdUtil
from hop_db import HopDB
from ryu.topology import api as topo_api
from conf_mgr import SDNMDRConfigManager

class SdnmdrRouting(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        'fwd': FwdUtil,
        'hop_db': HopDB
    }

    def __init__(self, *args, **kwargs):
        super(SdnmdrRouting, self).__init__(*args, **kwargs)
        self.fwd_util = kwargs['fwd']
        self.hop_db = kwargs['hop_db']
        self.cfg_mgr = SDNMDRConfigManager()

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    @packet_in_filter(RequiredTypeFilter, {'types': [ipv4.ipv4]})
    def outer_route_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        ofproto = dp.ofproto

        pkt = packet.Packet(msg.data)
        ipv4_header = pkt.get_protocol(ipv4.ipv4)

        src_ip = ipv4_header.src
        dst_ip = ipv4_header.dst

        if self.cfg_mgr.is_internal_host(dst_ip):
            return
        nexthop_info = self.hop_db.get_nexthop_by_ip(dst_ip)
        if not nexthop_info:
            return
        nexthop_prefix = nexthop_info[0]
        nexthop = nexthop_info[1]
        gateway = self.conf_mgr.get_gateway(nexthop)

        if gateway is None:
            return

        host_match = dp.ofproto_parser.OFPMatch(ipv4_dst=(str(nexthop_prefix.ip), str(nexthop_prefix.netmask)), eth_type=2048)
        pre_actions = [dp.ofproto_parser.OFPActionSetField(eth_dst=gateway.neiswitch_mac)]
        self.logger.info("outer")
        self.fwd_util.setup_shortest_path(dpid, gateway.dpid, gateway.out_port, host_match, pre_actions)

        switch = topo_api.get_switch(self, gateway.dpid)[0]
        self.fwd_util.packet_out(switch.dp, msg, gateway.out_port)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    @packet_in_filter(RequiredTypeFilter, {'types': [ipv4.ipv4]})
    def inner_route_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        ofproto = dp.ofproto

        pkt = packet.Packet(msg.data)
        ipv4_header = pkt.get_protocol(ipv4.ipv4)

        src_ip = ipv4_header.src
        dst_ip = ipv4_header.dst
        if not self.cfg_mgr.is_internal_host(dst_ip):
            return

        dst_host = self.fwd_util.get_host(dst_ip)

        self.logger.info("dst_host is %s", dst_host)

        if dst_host is None:
            return

        host_match = dp.ofproto_parser.OFPMatch(ipv4_dst=dst_ip, eth_type=2048)
        pre_actions = [dp.ofproto_parser.OFPActionSetField(eth_dst=dst_host.mac)]

  
        self.logger.info("inner")
        self.logger.info("dpid is %s", dpid)
        self.logger.info("dst_host.port.dpid is %s", dst_host.port.dpid)
        self.logger.info("dst_host.port.port_no is %s", dst_host.port.port_no)
        self.logger.info("host_match is %s", host_match)
        self.logger.info("pre_actions is %s", pre_actions)


        self.fwd_util.setup_shortest_path(dpid, dst_host.port.dpid, dst_host.port.port_no, host_match, pre_actions)
        switch = topo_api.get_switch(self, dst_host.port.dpid)[0]
        self.fwd_util.packet_out(switch.dp, msg, dst_host.port.port_no)
