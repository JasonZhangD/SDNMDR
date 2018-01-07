import json
from ryu import cfg
from netaddr import IPNetwork

CONF = cfg.CONF

class Gateway(object):
    def __init__(self, dpid, out_port, neicontroller_ip, neiswitch_mac):
        self.dpid = dpid
        self.out_port = out_port
        self.neicontroller_ip = neicontroller_ip
        self.neiswitch_mac = neiswitch_mac

class SDNMDRConfigManager(object):

    def __init__(self):
        super(SDNMDRConfigManager, self).__init__()
        self.gateways = [Gateway(3, 3, "192.168.96.129", "00:00:00:00:00:15")]
        self.networks = ["172.17.1.0/24"]

    def is_internal_host(self, ip):

        for network in self.networks:
            nw = IPNetwork(network)
            if ip in nw:
                return True

        return False

    def get_gateway(self, ip):
        for gateway in self.gateways:
            if gateway.neicontroller_ip == ip:
                return gateway
