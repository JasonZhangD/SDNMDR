import json

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.services.protocols.bgp.bgpspeaker import BGPSpeaker
from ryu.app.wsgi import route
from ryu.exception import RyuException
from ryu.app.wsgi import WSGIApplication
from ryu.app.wsgi import ControllerBase
from ryu.app.wsgi import Response
from ryu.lib.stringify import StringifyMixin


API_NAME = 'sdnmdr'

def to_int(i):
    return int(str(i), 0)

class RestApiException(RyuException):

    def to_response(self, status):
        body = {
            "error": str(self),
            "status": status,
        }
        return Response(content_type='application/json',
                        body=json.dumps(body), status=status)


class SDNMDRSpeakerNotFound(RestApiException):
    message = 'SDNMDRSpeaker could not be found'

class NeighborNotFound(RestApiException):
    message = 'No such neighbor: %(address)s'

class SdnmdrSpeaker(BGPSpeaker, StringifyMixin):
    _TYPE = {
        'ascii': [
            'router_id',
        ],
    }
    def __init__(self, as_number, router_id, best_path_change_handler, peer_down_handler, peer_up_handler, neighbors=None):
        super(SdnmdrSpeaker, self).__init__(
            as_number=as_number,
            router_id=router_id,
            best_path_change_handler=best_path_change_handler,
            peer_down_handler=peer_down_handler,
            peer_up_handler=peer_up_handler,
            ssh_console=True)

        self.as_number = as_number
        self.router_id = router_id
        self.neighbors = neighbors or {}

class SdnmdrNeighbor(StringifyMixin):
    _TYPE = {
        'ascii': [
            'address',
            'state',
        ],
    }

    def __init__(self, address, remote_as, state='down'):
        super(SdnmdrNeighbor, self).__init__()
        self.address = address
        self.remote_as = remote_as
        self.state = state

class Sdnmdr(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(Sdnmdr, self).__init__(*args, **kwargs)
        wsgi = kwargs['wsgi']
        wsgi.register(SdnmdrController, {Sdnmdr.__name__: self})

        self.speaker = None
        self.ovs = None

    def _best_path_change_handler(self, ev):
        self.logger.info('best path changed:')

    def _peer_down_handler(self, remote_ip, remote_as):
        self.logger.info('peer down:')

    def _peer_up_handler(self, remote_ip, remote_as):
        neighbor = self.speaker.neighbors.get(remote_ip, None)
        if neighbor is None:
            self.logger.debug('No such neighbor: remote_ip=%s, remote_as=%s',
                              remote_ip, remote_as)
            return

        neighbor.state = 'up'

    def add_speaker(self, as_number, router_id):

        self.speaker = SdnmdrSpeaker(
            as_number=as_number,
            router_id=router_id,
            best_path_change_handler=self._best_path_change_handler,
            peer_down_handler=self._peer_down_handler,
            peer_up_handler=self._peer_up_handler)

        return {self.speaker.router_id: self.speaker.to_jsondict()}

    def get_speaker(self):
        if self.speaker is None:
            return SDNMDRSpeakerNotFound()

        return {self.speaker.router_id: self.speaker.to_jsondict()}

    def add_neighbor(self, address, remote_as):
        if self.speaker is None:
            raise SDNMDRSpeakerNotFound()

        self.speaker.neighbor_add(
            address=address,
            remote_as=remote_as, enable_ipv4fs=True)

        neighbor = SdnmdrNeighbor(
            address=address,
            remote_as=remote_as)
        self.speaker.neighbors[address] = neighbor

        return {address: neighbor.to_jsondict()}

    def get_neighbors(self, address=None):
        if self.speaker is None:
            raise SDNMDRSpeakerNotFound()

        if address is not None:
            neighbor = self.speaker.neighbors.get(address, None)
            if neighbor is None:
                raise NeighborNotFound(address=address)
            return {address: neighbor.to_jsondict()}

        neighbors = {}
        for address, neighbor in self.speaker.neighbors.items():
            neighbors[address] = neighbor.to_jsondict()

        return neighbors

def post_method(keywords):
    def _wrapper(method):
        def __wrapper(self, req, **kwargs):
            try:
                try:
                    body = req.json if req.body else {}
                except ValueError:
                    raise ValueError('Invalid syntax %s', req.body)
                kwargs.update(body)
                for key, converter in keywords.items():
                    value = kwargs.get(key, None)
                    if value is None:
                        raise ValueError('%s not specified' % key)
                    kwargs[key] = converter(value)
            except ValueError as e:
                return Response(content_type='application/json',
                                body={"error": str(e)}, status=400)
            try:
                return method(self, **kwargs)
            except Exception as e:
                status = 500
                body = {
                    "error": str(e),
                    "status": status,
                }
                return Response(content_type='application/json',
                                body=json.dumps(body), status=status)
        __wrapper.__doc__ = method.__doc__
        return __wrapper
    return _wrapper

def get_method(keywords=None):
    keywords = keywords or {}

    def _wrapper(method):
        def __wrapper(self, _, **kwargs):
            try:
                for key, converter in keywords.items():
                    value = kwargs.get(key, None)
                    if value is None:
                        continue
                    kwargs[key] = converter(value)
            except ValueError as e:
                return Response(content_type='application/json',
                                body={"error": str(e)}, status=400)
            try:
                return method(self, **kwargs)
            except Exception as e:
                status = 500
                body = {
                    "error": str(e),
                    "status": status,
                }
                return Response(content_type='application/json',
                                body=json.dumps(body), status=status)
        __wrapper.__doc__ = method.__doc__
        return __wrapper
    return _wrapper


class SdnmdrController(ControllerBase):

    def __init__(self, req, link, data, **config):
        super(SdnmdrController, self).__init__(req, link, data, **config)
        self.sdnmdr_app = data[Sdnmdr.__name__]
        self.logger = self.sdnmdr_app.logger

    @route(API_NAME, '/sdnmdr/speakers', methods=['POST'])
    @post_method(
        keywords={
            "as_number": to_int,
            "router_id": str,
        })
    def add_speaker(self, **kwargs):
        body = self.sdnmdr_app.add_speaker(**kwargs)
        return Response(content_type='application/json',
                        body=json.dumps(body))

    @route(API_NAME, '/sdnmdr/speakers', methods=['GET'])
    @get_method()
    def get_speakers(self, **kwargs):
        try:
            body = self.sdnmdr_app.get_speaker()
        except SDNMDRSpeakerNotFound as e:
            return e.to_response(status=404)
        return Response(content_type='application/json',
                        body=json.dumps(body))

    @route(API_NAME, '/sdnmdr/neighbors', methods=['POST'])
    @post_method(
        keywords={
            "address": str,
            "remote_as": to_int,
        })
    def add_neighbor(self, **kwargs):
        try:
            body = self.sdnmdr_app.add_neighbor(**kwargs)
        except SDNMDRSpeakerNotFound as e:
            return e.to_response(status=400)

        return Response(content_type='application/json',
                        body=json.dumps(body))
    def _get_neighbors(self, **kwargs):
        try:
            body = self.sdnmdr_app.get_neighbors(**kwargs)
        except (SDNMDRSpeakerNotFound, NeighborNotFound) as e:
            return e.to_response(status=404)

        return Response(content_type='application/json',
                        body=json.dumps(body))

    @route(API_NAME, '/sdnmdr/neighbors', methods=['GET'])
    @get_method()
    def get_neighbors(self, **kwargs):
        return self._get_neighbors(**kwargs)

    @route(API_NAME, '/sdnmdr/neighbors/{address}', methods=['GET'])
    @get_method(
        keywords={
            "address": str,
        })
    def get_neighbor(self, **kwargs):
        return self._get_neighbors(**kwargs)

