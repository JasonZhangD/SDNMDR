import networkx as nx
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.topology import api as topo_api


class FwdUtil(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(FwdUtil, self).__init__(*args, **kwargs)
        self.dps = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def setup_shortest_path(self,
                            from_dpid,
                            to_dpid,
                            to_port_no,
                            to_dst_match,
                            pre_actions=[]):
        nx_grapth = self.get_nx_graph()
        path = self.get_shortest_path(nx_grapth, from_dpid, to_dpid)
        self.logger.info("path is: %s", path)
        if path is None:
            return
        port_no = 0
        self.logger.info("path numbers: %s", len(path))
        if len(path) == 1:
            dp = self.get_datapath(from_dpid)
            actions = [dp.ofproto_parser.OFPActionOutput(to_port_no)]
            self.add_flow(dp, 1, to_dst_match, pre_actions+actions)
            port_no = to_port_no
        else:
            self.install_path(to_dst_match, path, nx_grapth, pre_actions)
            dst_dp = self.get_datapath(to_dpid)
            actions = [dst_dp.ofproto_parser.OFPActionOutput(to_port_no)]
            self.add_flow(dst_dp, 1, to_dst_match, pre_actions+actions)
            port_no = nx_grapth[path[0]][path[1]]['src_port']

        return port_no

    def get_shortest_path(self, nx_graph, src_dpid, dst_dpid):

        if nx.has_path(nx_graph, src_dpid, dst_dpid):
            return nx.shortest_path(nx_graph, src_dpid, dst_dpid)

        return None

    def get_nx_graph(self):
        graph = nx.DiGraph()
        switches = topo_api.get_all_switch(self)
        links = topo_api.get_all_link(self)

        for switch in switches:
            dpid = switch.dp.id
            graph.add_node(dpid)

        for link in links:
            src_dpid = link.src.dpid
            dst_dpid = link.dst.dpid
            src_port = link.src.port_no
            dst_port = link.dst.port_no
            graph.add_edge(src_dpid,
                           dst_dpid,
                           src_port=src_port,
                           dst_port=dst_port)
        return graph


    def install_path(self, match, path, nx_graph, pre_actions=[]):
        for index, dpid in enumerate(path[:-1]):
            port_no = nx_graph[path[index]][path[index + 1]]['src_port']
            dp = self.get_datapath(dpid)
            actions = [dp.ofproto_parser.OFPActionOutput(port_no)]
            self.add_flow(dp, 1, match, pre_actions+actions)

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        mod = parser.OFPFlowMod(datapath=datapath,
                                priority=priority,
                                match=match,
                                hard_timeout=0,
                                instructions=inst)
        datapath.send_msg(mod)

    def get_datapath(self, dpid):
        if dpid not in self.dps:
            switch = topo_api.get_switch(self, dpid)[0]
            self.dps[dpid] = switch.dp
            return switch.dp

        return self.dps[dpid]

    def get_all_datapaths(self):
        switches = topo_api.get_all_switch(self)

        for switch in switches:
            dp = switch.dp
            dpid = dp.id
            self.dps[dpid] = dp

        return self.dps.values()


    def get_host(self, ip):
        hosts = topo_api.get_all_host(self)
        for host in hosts:
            if ip in host.ipv4:
                return host

        return None


    def packet_out(self, dp, msg, out_port):
        ofproto = dp.ofproto
        actions = [dp.ofproto_parser.OFPActionOutput(out_port)]
        data = None
        self.logger.info("actions is %s", actions)
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = dp.ofproto_parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                  in_port=msg.match['in_port'], actions=actions, data=data)
        self.logger.info("out is %s", out)
        dp.send_msg(out)
