from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.lib.ofp_pktinfilter import packet_in_filter, RequiredTypeFilter
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import arp
from conf_mgr import SDNMDRConfigManager

class ArpProxyV1(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ArpProxyV1, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.cfg_mgr = SDNMDRConfigManager()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    @packet_in_filter(RequiredTypeFilter, {'types': [arp.arp]})
    def _packet_in_handler(self, ev):

        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)

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
        dst_mac = arp_header.dst_mac
        self.logger.info(dst_mac)


        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        self.logger.info("packet in %s %s %s %s", dpid, src_mac, dst_mac, in_port)

        self.mac_to_port[dpid][src_mac] = in_port

        if dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst_mac]

        elif dst_ip == "172.17.1.1":
              dst_mac = "00:0c:29:91:79:96"
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
              out = parser.OFPPacketOut(datapath=datapath,
                                        buffer_id=ofproto.OFP_NO_BUFFER,
                                        in_port=ofproto.OFPP_CONTROLLER,
                                        actions=actions, data=arp_reply.data)
              datapath.send_msg(out)

        elif self.cfg_mgr.is_internal_host(dst_ip):
              out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst_mac, eth_src=src_mac)
            self.logger.info("match is %s", match)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
    
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

