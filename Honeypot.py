import socket
import threading
import time
import math
from Utils import CannotBindPort, debug, info, error, Waiter, _DOCKER_LOG_CONFIG

class Honeypot:

    # class constructor
    def __init__(self, config, honeypot, docker_client):
        self._SESSIONS = {} # dict of container : [client_socket, honeypot_socket, c>h_thread, h>c_thread]
        self._CONTAINERS = [] # list of container objects
        self._SERVER_SOCKET = None # honeypot server listening socket
        self._SERVER_THREAD = None # server thread
        self._CONFIG = config# configuration
        self._CONTAINER_CONFIG = {} # docker container configuration
        self._HONEYPOT = honeypot # honeypot configuration
        self._DOCKER_CLIENT = docker_client # docker client
        self._MUTEX = threading.Lock() # session lock

        # parse container options
        try:
            self._CONTAINER_CONFIG['command'] = self._HONEYPOT['options']['command']
        except:
            self._CONTAINER_CONFIG['command'] = None

        try:
            self._CONTAINER_CONFIG['environment'] = self._HONEYPOT['options']['environment']
        except:
            self._CONTAINER_CONFIG['environment'] = None

        try:
            self._CONTAINER_CONFIG['hostname'] = self._HONEYPOT['options']['hostname']
        except:
            self._CONTAINER_CONFIG['hostname'] = None

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
            self._CONTAINER_CONFIG['read_only'] = None

        try:
            self._CONTAINER_CONFIG['user'] = self._HONEYPOT['options']['user']
        except:
            self._CONTAINER_CONFIG['user'] = None

        try:
            self._CONTAINER_CONFIG['volumes'] = self._HONEYPOT['options']['volumes']
        except:
            self._CONTAINER_CONFIG['volumes'] = None

        self.startService()

    # start the honeypot service
    def startService(self):

        # create new TCP socket
        self._SERVER_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # allow multiple connections on the same address
        self._SERVER_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # bind IP address and port
        try:
            self._SERVER_SOCKET.bind((self._CONFIG['bind'], self._HONEYPOT['port']))
            debug('[{}] Binding IP address {} and port {}.'.format(self._HONEYPOT['name'], str(self._CONFIG['bind']), str(self._HONEYPOT['port'])))
        except Exception as e:
            raise CannotBindPort(self._HONEYPOT, e.args[1])

        try:
            # start socket and set maximum number of connections
            conns = math.floor(self._CONFIG['max_connections'] / self._CONFIG['honeypots_num'])
            debug('[{}] Starting socket with {} maximum connections'.format(self._HONEYPOT['name'], conns))
            self._SERVER_SOCKET.listen(conns)
        except:
            raise CannotBindPort(self._HONEYPOT, 'Already in use')

        info('[{}] Server for honeypot has started on {}.'.format(self._HONEYPOT['name'], str(self._CONFIG['bind']) + ':' + str(self._HONEYPOT['port'])))

        # start listener thread
        self._SERVER_THREAD = threading.Thread(target=self.waitForConnection)
        self._SERVER_THREAD.daemon = True
        self._SERVER_THREAD.start()

        debug('[{}] Server listener thread has started.'.format(self._HONEYPOT['name']))

    # wait for socket connections
    def waitForConnection(self):
        while True:
            debug('[{}] Waiting for connections...'.format(self._HONEYPOT['name']))

            try:
                client_socket, client_address = self._SERVER_SOCKET.accept()
            except:
                break
            
            info('[{}] New connection from {}.'.format(self._HONEYPOT['name'], ':'.join(str(x) for x in client_address)))
            
            # finish processing connection without blocking new connections
            process = threading.Thread(target=self.processConnection, args=(client_socket, client_address))
            process.daemon = True
            process.start()

        # stop server socket
        try:
            self._SERVER_SOCKET.shutdown(socket.SHUT_RDWR)
            self._SERVER_SOCKET.close()
        except:
            pass

    # wait for container to start and create data transfer sockets
    def processConnection(self, client_socket, client_address):
        # start a new container
        container = self.launchContainer()
        self._MUTEX.acquire()
        self._CONTAINERS.append(container)
        self._MUTEX.release()

        # get container IP address
        ip = container.attrs['NetworkSettings']['IPAddress']

        debug('[{}] Started container ({}) on host \'{}\' for {}.'.format(
        self._HONEYPOT['name'], container.id, ip, ':'.join(str(x) for x in client_address)))

        # open socket to container
        waiter = Waiter()
        while True:
            try:
                honeypot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                honeypot_socket.connect((ip, self._HONEYPOT['container_port']))
                break
            except:
                waiter.wait()

        debug('[{}] Socket opened to container {}.'.format(self._HONEYPOT['name'], container.id))

        # start data transfer threads
        c_h = threading.Thread(target=self.dataTransfer, args=(container.id, client_socket, honeypot_socket))
        h_c = threading.Thread(target=self.dataTransfer, args=(container.id, honeypot_socket, client_socket, True))
        c_h.daemon = True
        h_c.daemon = True
        c_h.start()
        h_c.start()

        self._MUTEX.acquire()
        self._SESSIONS[container.id] = [client_socket, honeypot_socket, c_h, h_c]
        self._MUTEX.release()

    # launch service container for new connection
    def launchContainer(self):
        c = self._DOCKER_CLIENT.containers.run(
            image=self._HONEYPOT['image'],
            command=self._CONTAINER_CONFIG['command'],
            auto_remove=True,
            detach=True,
            environment=self._CONTAINER_CONFIG['environment'],
            hostname=self._CONTAINER_CONFIG['hostname'],
            log_config=_DOCKER_LOG_CONFIG,
            network=self._CONTAINER_CONFIG['network'],
            network_mode=self._CONTAINER_CONFIG['network_mode'],
            read_only=self._CONTAINER_CONFIG['read_only'],
            user=self._CONTAINER_CONFIG['user'],
            volumes=self._CONTAINER_CONFIG['volumes']
        )

        # wait for container to start
        cc = self._DOCKER_CLIENT.containers.get(c.id)

        return cc

    # socket data transferer
    def dataTransfer(self, container, source, destination, direction = False):
        source_address = ':'.join(str(x) for x in source.getsockname())
        destination_address = ':'.join(str(x) for x in destination.getsockname())
        direction_text = '{} {} {}'.format(destination_address, '<-', source_address) if direction else '{} {} {}'.format(source_address, '->', destination_address)
        
        debug('[{}] Starting transfer thread {}.'.format(self._HONEYPOT['name'], direction_text))
        
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

        debug('[{}] Stopped transfer thread {}.'.format(self._HONEYPOT['name'], direction_text))

        # stop the session
        self.stopSession(container)

        # only write stopped message once
        if direction:
            info('[{}] Connection from {} ended.'.format(self._HONEYPOT['name'], source_address))

    # data interceptor / follower
    def dataHandler(self, buffer):
        return buffer

    # stop session and remove any orphans
    def stopSession(self, container):

        # lock access to sessions
        self._MUTEX.acquire()
        # check if session was already terminated
        try:
            self._SESSIONS[container][0]
        except:
            self._MUTEX.release()
            return

        # get sockets
        s1 = self._SESSIONS[container][0]
        s2 = self._SESSIONS[container][1]

        # remove session
        try:
            del self._SESSIONS[container]
        except:
            pass

        # close sockets
        try:
            s1.shutdown(socket.SHUT_RDWR)
            s1.close()
            s2.shutdown(socket.SHUT_RDWR)
            s2.close()
        except:
            pass
        debug('[{}] Sockets closed to container {}.'.format(self._HONEYPOT['name'], container))

        self._MUTEX.release()

        # stop container
        try:
            c = self._DOCKER_CLIENT.containers.get(container)
            if c.status == 'running':
                c.stop()
                debug('[{}] Stopped container {}.'.format(self._HONEYPOT['name'], container))
        except:
            pass

    # kill the honeypot service on SIGINT
    def kill(self):
        info('[{}] Stopping.'.format(self._HONEYPOT['name']))

        # lock access to sessions
        self._MUTEX.acquire()
        for session in self._SESSIONS:
            # close sockets
            try:
                session[0].shutdown(socket.SHUT_RDWR)
                session[0].close()
                session[1].shutdown(socket.SHUT_RDWR)
                session[1].close()
                session[2].join()
                session[3].join()
            except:
                pass

            # stop container
            try:
                c = self._DOCKER_CLIENT.containers.get(session[0])
                if c.status == 'running':
                    c.stop()
            except:
                pass

        # stop any orphaned containers
        for container in self._CONTAINERS:
            try:
                if container.status == 'running':
                    container.stop()
            except:
                pass
        
        # stop server socket
        try:
            self._SERVER_SOCKET.shutdown(socket.SHUT_RDWR)
            self._SERVER_SOCKET.close()
        except:
            pass

        # stop server thread
        self._SERVER_THREAD.join()
        self._MUTEX.release()

