from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import arp
from ryu.lib.ofp_pktinfilter import packet_in_filter, RequiredTypeFilter
from ryu.topology import api as topo_api
from conf_mgr import SDNMDRConfigManager
from fwd_util import FwdUtil

class ArpProxy(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    _CONTEXTS = {
        'fwd': FwdUtil,
    }

    def __init__(self, *args, **kwargs):
        super(ArpProxy, self).__init__(*args, **kwargs)
        self.fwd_util = kwargs['fwd']
        self.cfg_mgr = SDNMDRConfigManager()

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    @packet_in_filter(RequiredTypeFilter, {'types': [arp.arp]})
    def arp_packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.match['in_port']
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt = packet.Packet(msg.data)
        arp_header = pkt.get_protocol(arp.arp)
        src_ip = arp_header.src_ip
        self.logger.info(src_ip)
        src_mac = arp_header.src_mac
        self.logger.info(src_mac)
        dst_ip = arp_header.dst_ip
        self.logger.info(dst_ip)
        dst_mac = None
        self.logger.info(dst_mac)


        dst_host = self.fwd_util.get_host(dst_ip)
        self.logger.info(dst_host)


        if dst_host is not None:
            dst_mac = dst_host.mac
            self.logger.info(dst_mac)

        elif dst_ip == "172.17.1.1":
              dst_mac = "00:0c:29:91:79:96"

        elif self.cfg_mgr.is_internal_host(dst_ip):
              self.flood(msg)
              return

        if arp_header.opcode != arp.ARP_REQUEST:
            return

        if not dst_mac:
            return
        self.logger.info('find mac for %s :%s:', dst_ip,dst_mac )
        actions = [parser.OFPActionOutput(in_port)]
        arp_reply = packet.Packet()
        arp_reply.add_protocol(
            ethernet.ethernet(
                ethertype=ether_types.ETH_TYPE_ARP,
                src=dst_mac,
                dst=src_mac
            )
        )
        arp_reply.add_protocol(
            arp.arp(
                opcode=arp.ARP_REPLY,
                src_ip=dst_ip,
                src_mac=dst_mac,
                dst_ip=src_ip,
                dst_mac=src_mac
            )
        )
        arp_reply.serialize()
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions, data=arp_reply.data)
        datapath.send_msg(out)

    def flood(self, msg):
        switches = topo_api.get_all_switch(self)
        links = topo_api.get_all_link(self)
        link_point_set = set()
        for link in links:
            src_dpid = link.src.dpid
            dst_dpid = link.dst.dpid
            src_port = link.src.port_no
            dst_port = link.dst.port_no
            link_point_set.add((src_dpid,src_port))
            link_point_set.add((dst_dpid, dst_port))
        for switch in switches:
            dp = switch.dp
            self.logger.info(dp)
            for port in switch.ports:
                self.logger.info(port)
                if (port.dpid, port.port_no) in link_point_set:
                    self.logger.info("%s,%s",port.dpid,port.port_no)
                    continue
                self.logger.info("%s,%s",dp,port.port_no)
                self.fwd_util.packet_out(dp, msg, port.port_no)
        return
