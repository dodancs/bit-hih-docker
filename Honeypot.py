import socket
import threading
import time
import math
from Utils import CannotBindPort, debug, info, error

class Honeypot:
    _SESSIONS = [] # list of [container_id, client_socket, honeypot_socket, c>h_thread, h>c_thread]
    _SERVER_SOCKET = None # honeypot server listening socket
    _SERVER_THREAD = None # server thread
    _CONFIG = None # configuration
    _CONTAINER_CONFIG = {} # docker container configuration
    _HONEYPOT = None # honeypot configuration
    _DOCKER_CLIENT = None # docker client

    # class constructor
    def __init__(self, config, honeypot, docker_client):
        self._CONFIG = config
        self._HONEYPOT = honeypot
        self._DOCKER_CLIENT = docker_client

        try:
            self._CONTAINER_CONFIG['command'] = self._HONEYPOT['options']['command']
        except:
            self._CONTAINER_CONFIG['command'] = None

        try:
            self._CONTAINER_CONFIG['environment'] = self._HONEYPOT['options']['environment']
        except:
            self._CONTAINER_CONFIG['environment'] = []

        try:
            self._CONTAINER_CONFIG['network'] = self._HONEYPOT['options']['network']
        except:
            self._CONTAINER_CONFIG['network'] = None

        try:
            self._CONTAINER_CONFIG['network_mode'] = self._HONEYPOT['options']['network_mode']
        except:
            self._CONTAINER_CONFIG['network_mode'] = None

        try:
            self._CONTAINER_CONFIG['read_only'] = self._HONEYPOT['options']['read_only']
        except:
            self._CONTAINER_CONFIG['read_only'] = False

        try:
            self._CONTAINER_CONFIG['user'] = self._HONEYPOT['options']['user']
        except:
            self._CONTAINER_CONFIG['user'] = None

        try:
            self._CONTAINER_CONFIG['volumes'] = self._HONEYPOT['options']['volumes']
        except:
            self._CONTAINER_CONFIG['volumes'] = {}

        self.startService()

    # start the honeypot service
    def startService(self):

        # create new TCP socket
        self._SERVER_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # allow multiple connections on the same address
        self._SERVER_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # bind IP address and port
        self._SERVER_SOCKET.bind((self._CONFIG['bind'], self._HONEYPOT['port']))
        debug('Binding IP address {} and port {} to honeypot for {}'.format(str(self._CONFIG['bind']), str(self._HONEYPOT['port']), self._HONEYPOT['name']))

        try:
            # start socket and set maximum number of connections
            conns = math.floor(self._CONFIG['max_connections'] / self._CONFIG['honeypots_num'])
            debug('Starting socket with {} maximum connections'.format(conns))
            self._SERVER_SOCKET.listen(conns)
        except:
            raise CannotBindPort(self._HONEYPOT)

        info('Server for \'{}\' honeypot has started on {}.'.format(
            self._HONEYPOT['name'], str(self._CONFIG['bind']) + ':' + str(self._HONEYPOT['port'])))

        # start listener thread
        self._SERVER_THREAD = threading.Thread(target=self.waitForConnection)
        self._SERVER_THREAD.daemon = True
        self._SERVER_THREAD.start()

    # wait for socket connections
    def waitForConnection(self):
        while True:
            client_socket, client_address = self._SERVER_SOCKET.accept()
            info('[{}] New connection from {}.'.format(self._HONEYPOT['name'], ':'.join(str(x) for x in client_address)))
            
            # start a new container
            container = self.launchContainer()

            # get container IP address
            ip = container.attrs['NetworkSettings']['IPAddress']

            debug('[{}] Started container ({}) on host \'{}\' for {}.'.format(
            self._HONEYPOT['name'], container.id, ip, ':'.join(str(x) for x in client_address)))

            # open socket to container
            honeypot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            honeypot_socket.connect((ip, self._HONEYPOT['container_port']))

            # start data transfer threads
            c_h = threading.Thread(target=self.dataTransfer, args=(client_socket, honeypot_socket))
            h_c = threading.Thread(target=self.dataTransfer, args=(honeypot_socket, client_socket, True))
            c_h.daemon = True
            h_c.daemon = True
            c_h.start()
            h_c.start()

            self._SESSIONS.append([container.id, client_socket, honeypot_socket, c_h, h_c])

        # stop server socket
        try:
            self._SERVER_SOCKET.shutdown(socket.SHUT_RDWR)
            self._SERVER_SOCKET.close()
        except:
            pass

    # launch service container for new connection
    def launchContainer(self):
        c = self._DOCKER_CLIENT.containers.run(
            image=self._HONEYPOT['image'],
            command=self._CONTAINER_CONFIG['command'],
            auto_remove=True,
            detach=True,
            environment=self._CONTAINER_CONFIG['environment'],
            network=self._CONTAINER_CONFIG['network'],
            network_mode=self._CONTAINER_CONFIG['network_mode'],
            read_only=self._CONTAINER_CONFIG['read_only'],
            user=self._CONTAINER_CONFIG['user'],
            volumes=self._CONTAINER_CONFIG['volumes']
        )

        # wait for container to start
        cc = self._DOCKER_CLIENT.containers.get(c.id)

        return cc

    def dataTransfer(self, source, destination, direction = False):
        debug('[{}] Starting transfer thread {} {} {}.'.format(self._CONTAINER_CONFIG['name'], ':'.join(str(x) for x in source.getsockname()), '<-' if direction else '->', ':'.join(str(x) for x in destination.getsockname())))
        try:
            while True:
                # read 1024 bytes
                buffer = source.recv(0x400)
                # if no more data has been received
                if len(buffer) == 0:
                    break
                destination.send(self.dataHandler(buffer))
        except:
            pass

        debug('[{}] Stopped transfer thread {} {} {}.'.format(self._CONTAINER_CONFIG['name'], ':'.join(str(x) for x in source.getsockname()), '<-' if direction else '->', ':'.join(str(x) for x in destination.getsockname())))

        self.stopSockets(source, destination)


    def dataHandler(self, buffer):
        return buffer

    def stopSockets(self, s1, s2):
        container = None
        source = None
        destination = None
        session = None

        # remove session
        for i in range(len(self._SESSIONS)):
            if (self._SESSIONS[i][1] == s1 and self._SESSIONS[i][2] == s2) or (self._SESSIONS[i][2] == s1 and self._SESSIONS[i][1] == s2):
                session = i
                break

        if session != None:
            container = self._SESSIONS[session][0]
            source = self._SESSIONS[session][1]
            destination = self._SESSIONS[session][2]

        # close sockets
        try:
            s1.shutdown(socket.SHUT_RDWR)
            s1.close()
            s2.shutdown(socket.SHUT_RDWR)
            s2.close()
            info('[{}] Connection from {} closed.'.format(self._HONEYPOT['name'], ':'.join(str(x) for x in source.getsockname())))
        except:
            pass

        try:
            c = self._DOCKER_CLIENT.containers.get(container)
            c.stop()
            debug('[{}] Stopped container ({}) on host \'{}\' for {}.'.format(
            self._HONEYPOT['name'], container, destination.getsockname()[0], ':'.join(str(x) for x in source.getsockname())))
        except:
            pass
        
        if session != None:
            del self._SESSIONS[session]

    def kill(self):
        for session in self._SESSIONS:
            # close sockets
            try:
                session[1].shutdown(socket.SHUT_RDWR)
                session[1].close()
                session[2].shutdown(socket.SHUT_RDWR)
                session[2].close()
                session[3].join()
                session[4].join()
            except:
                pass

            try:
                c = self._DOCKER_CLIENT.containers.get(session[0])
                c.stop()
            except:
                pass
        
        try:
            self._SERVER_SOCKET.shutdown(socket.SHUT_RDWR)
            self._SERVER_SOCKET.close()
        except:
            pass

        self._SERVER_THREAD.join()

