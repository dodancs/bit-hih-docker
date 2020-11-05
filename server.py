import json
from jsonschema import validate
import os
import sys
import signal
from termcolor import colored, cprint
import logging
import logging.handlers
import docker
import ipaddress
import socket
import threading
import time
import itertools

########################
#       Logging        #
########################

logger = logging.getLogger('hih-docker')
logging_format = logging.Formatter(
    '%(name)s: [%(levelname)s] %(message)s'
)
if os.name != 'nt':
    handler_linux = logging.handlers.SysLogHandler(address='/dev/log')
    handler_linux.setFormatter(logging_format)
    logger.addHandler(handler_linux)
logger.setLevel(logging.INFO)

########################
#        Helpers       #
########################

_VERSION = '1.0.0'  # app version
_DEBUG = False  # enable or disable debugging output
_CONFIG_FILE = 'config.json'  # config file name
_CONFIG = None  # parsed configuration
_CONFIG_OVERRIDE_BIND = None  # override bind IP address from config
_CONFIG_OVERRIDE_CONNS = None  # override maximum number of connections from config
_HOST = None  # bind host
_DOCKER_CLIENT = None  # Docker client
_DOCKER_IMAGES = []  # all docker images used
_FORCE_PULL = False  # dorce pull fresh docker images
_SESSIONS = {}  # connected sessions
_SERVER_SOCKETS = []  # running servers
_SOCKETS = []  # client sockets
_PORTS_USED = []  # used local ports
_PORTS_LOCK = None  # lock for multithreaded access
_THREADS = []  # all threads


def info(message):
    cprint('[INFO]: %s' % message, 'white')
    logging.info(message)


def debug(message):
    if _DEBUG:
        cprint('[DEBUG]: %s' % message, 'yellow')
    logging.debug(message)


def error(message):
    cprint('[ERROR]: %s' % message, 'white', 'on_red')
    logging.error(message)


def printHelp():
    cprint(
        'python3 ./server.py [OPTIONS]\n\
    -h --help                   Show help\n\
    -v --version                Show program version\n\
    -d --debug                  Show debug messages\n\
       --bind [ADDR]            Override IP address bind\n\
       --max-connections [N]    Override maximum number of connections to the server\n\
    -c --config [FILE]          Use custom config file location\n\
       --force-pull             Force pull images from Docker registry\
    ', 'cyan')
    exit(1)


def printVersion():
    global _VERSION
    cprint('HIH-Docker version {}'.format(_VERSION), 'cyan')
    exit(0)


def Diff(li1, li2):
    return (list(list(set(li1) - set(li2)) + list(set(li2) - set(li1))))


def stopAll(signal, frame):
    global _SERVER_SOCKETS, _SESSIONS, _DOCKER_CLIENT, _THREADS
    info('Stopping all services...')
    for i in _SESSIONS.keys():
        try:
            h = _DOCKER_CLIENT.containers.get(i)
            h.stop()
        except:
            pass
    for s in itertools.chain(_SERVER_SOCKETS, _SOCKETS):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except:
            pass
        s.close()
    # for t in _THREADS:
    #     t.join()

    sys.exit(0)


########################
#      Exceptions      #
########################


class CannotBindPort(Exception):
    def __init__(self, honeypot):
        self.honeypot = honeypot
        self.message = 'Cannot bind local port \'{}\' - already in use!'.format(
            honeypot['port'])
        super().__init__(self.message)


class NoPortsAvailable(Exception):
    def __init__(self):
        self.message = 'No more ports available! Cannot start honeypot.'.format()
        super().__init__(self.message)

########################
#     Config loader    #
########################


def loadConfig():
    global _CONFIG, _CONFIG_FILE

    info('Loading server configuration...')

    _CONFIG_SCHEMA = json.loads(open('config.schema.json').read())

    try:
        _CONFIG = json.loads(open(_CONFIG_FILE).read())
    except Exception as e:
        error('Cannot open configuration file!')
        logging.error(e)
        exit(1)

    try:
        validate(instance=_CONFIG, schema=_CONFIG_SCHEMA)
    except Exception as e:
        error('Server configuration is invalid!')
        logging.error(e)
        exit(1)

    info('Server configuration loaded successfully!')

    debug('Loaded config: {}'.format(_CONFIG))

########################
#    Initialization    #
########################


def init():
    global _CONFIG, _DOCKER_IMAGES, _DOCKER_CLIENT, _HOST, _FORCE_PULL, _PORTS_LOCK

    signal.signal(signal.SIGTERM, stopAll)
    signal.signal(signal.SIGINT, stopAll)

    _PORTS_LOCK = threading.Lock()

    # initialize Docker connector
    _DOCKER_CLIENT = docker.from_env()
    debug('List of running docker containers: {}'.format(
        _DOCKER_CLIENT.containers.list()))

    # initialize script
    loadConfig()

    _HOST = _CONFIG['bind']

    # scan for used images
    for honeypot in _CONFIG['honeypots']:
        if honeypot['image'] not in _DOCKER_IMAGES:
            _DOCKER_IMAGES.append(honeypot['image'])
    debug('Docker images parsed from config: {}'.format(_DOCKER_IMAGES))

    # pull docker images
    info('Updating Docker images...')
    for image in _DOCKER_IMAGES:
        info('Checking for {}...'.format(image))
        if not _FORCE_PULL:
            try:
                _DOCKER_CLIENT.images.get(image)
                info('Image {} is available.'.format(image))
            except:
                info('Pulling {}...'.format(image))
                _DOCKER_CLIENT.images.pull(image)
        else:
            info('Pulling {}...'.format(image))
            _DOCKER_CLIENT.images.pull(image)

    # bind honeypot servers
    for honeypot in _CONFIG['honeypots']:
        try:
            server(honeypot)
        except Exception as e:
            error(e.message)
            exit(1)

    while True:
        time.sleep(1)

########################
#      TCP server      #
########################


def server(honeypot):
    global _HOST, _CONFIG_OVERRIDE_CONNS, _SERVER_SOCKETS, _THREADS

    # create new TCP socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        # allow multiple connections on the same address
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # bind IP address and port
        s.bind((_HOST, honeypot['port']))
        # set maximum number of connections
        s.listen(_CONFIG['max_connections'] if _CONFIG_OVERRIDE_CONNS ==
                 None else _CONFIG_OVERRIDE_CONNS)
        _SERVER_SOCKETS.append(s)
    except:
        raise CannotBindPort(honeypot)

    info('Server for \'{}\' honeypot has started on {}.'.format(
        honeypot['name'], str(_HOST) + ':' + str(honeypot['port'])))

    t = threading.Thread(target=waitForConnection, args=(
        honeypot, s))
    t.daemon = True
    t.start()
    _THREADS.append(t)


def waitForConnection(honeypot, s):
    global _SOCKETS

    while True:
        local_socket, local_address = s.accept()
        info('New connection from {}:{}.'.format(
            local_address[0], local_address[1]))
        _SOCKETS.append(local_socket)
        launchHoneypot(honeypot, local_socket, local_address)

    s.shutdown(socket.SHUT_RDWR)
    s.close()


def dataTransfer(honeypot, h_id, local_address, src, dst, direction):
    global _DOCKER_CLIENT, _PORTS_USED, _SESSIONS

    try:
        src_name = src.getsockname()
        src_address = src_name[0]
        src_port = src_name[1]
        dst_name = dst.getsockname()
        dst_address = dst_name[0]
        dst_port = dst_name[1]
        while True:
            buffer = src.recv(0x400)
            if len(buffer) == 0:
                break
            dst.send(dataHandler(buffer))
        src.shutdown(socket.SHUT_RDWR)
        src.close()
        dst.shutdown(socket.SHUT_RDWR)
        dst.close()
    except:
        pass

    try:
        h = _DOCKER_CLIENT.containers.get(h_id)
        _PORTS_USED.remove(_SESSIONS[h_id])
        h.stop()
        debug('Stopped \'{}\' container for host: {} - {}.'.format(
            honeypot['name'], local_address[0], h_id))
    except:
        pass


def dataHandler(buffer):
    return buffer


########################
#  Honeypot management #
########################


def getPort():
    global _CONFIG, _PORTS_USED, _PORTS_LOCK
    _PORTS_LOCK.acquire()
    available = [*range(_CONFIG['ports_range'][0],
                        _CONFIG['ports_range'][1] + 1, 1)]
    available = Diff(available, _PORTS_USED)

    if (len(available) > 0):
        _PORTS_USED.append(available[0])
        _PORTS_LOCK.release()
        return available[0]
    else:
        _PORTS_LOCK.release()
        raise NoPortsAvailable()


def launchHoneypot(honeypot, local_socket, local_address):
    global _DOCKER_CLIENT, _SESSIONS, _CONFIG_OVERRIDE_BIND, _THREADS

    try:
        h_command = command = honeypot['options']['command']
    except:
        h_command = None

    try:
        h_environment = command = honeypot['options']['environment']
    except:
        h_environment = []

    try:
        h_network = command = honeypot['options']['network']
    except:
        h_network = None

    try:
        h_network_mode = command = honeypot['options']['network_mode']
    except:
        h_network_mode = None

    h_ports = {}
    h_ports[honeypot['container_port']] = (_HOST, getPort())
    try:
        h_ports.update(command=honeypot['options']['ports'])
    except:
        pass

    try:
        h_read_only = command = honeypot['options']['read_only']
    except:
        h_read_only = False

    try:
        h_user = command = honeypot['options']['user']
    except:
        h_user = None

    try:
        h_volumes = command = honeypot['options']['volumes']
    except:
        h_volumes = {}

    h = _DOCKER_CLIENT.containers.run(
        image=honeypot['image'],
        command=h_command,
        auto_remove=True,
        detach=True,
        environment=h_environment,
        network=h_network,
        network_mode=h_network_mode,
        ports=h_ports,
        read_only=h_read_only,
        user=h_user,
        volumes=h_volumes)

    hh = _DOCKER_CLIENT.containers.get(h.id)

    # print(hh.attrs['NetworkSettings'])
    # h_ip = hh.attrs['NetworkSettings']['IPAddress']
    h_port = h_ports[honeypot['container_port']][1]

    # print('Docker IP: {}:{}'.format(h_ip, h_port))

    debug('Started \'{}\' container on port {} for host: {} - {}.'.format(
        honeypot['name'], h_port, local_address[0], h.id))

    _SESSIONS[h.id] = h_port
    print(_SESSIONS)

    remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    remote_socket.connect(('127.0.0.1', h_port))
    _SOCKETS.append(remote_socket)

    s = threading.Thread(target=dataTransfer, args=(
        honeypot, h.id, local_address, remote_socket, local_socket, False))
    r = threading.Thread(target=dataTransfer, args=(
        honeypot, h.id, local_address, local_socket, remote_socket, True))
    s.daemon = True
    r.daemon = True
    s.start()
    r.start()
    _THREADS.append(s)
    _THREADS.append(r)


########################
#   Argument parsing   #
########################

sys.argv.pop(0)
while len(sys.argv) > 0:
    arg = sys.argv.pop(0)

    if arg in ['--help', '-h']:
        printHelp()

    elif arg in ['--version', '-v']:
        printVersion()

    # enable debugging
    elif arg in ['--debug', '-d']:
        _DEBUG = True
        logger.setLevel(logging.DEBUG)

    elif arg in ['--config', '-c']:
        if len(sys.argv) < 1:
            error('Missing arguments')
            exit(1)
        _CONFIG_FILE = sys.argv.pop(0)

    elif arg in ['--bind']:
        if len(sys.argv) < 1:
            error('Missing arguments')
            exit(1)

        _CONFIG_OVERRIDE_BIND = sys.argv.pop(0)
        try:
            ipaddress.IPv4Address(_CONFIG_OVERRIDE_BIND)
            _HOST = _CONFIG_OVERRIDE_BIND
        except:
            error('Please specify a valid IP address')
            exit(1)

    elif arg in ['--max-connections']:
        if len(sys.argv) < 1:
            error('Missing arguments')
            exit(1)
        try:
            _CONFIG_OVERRIDE_CONNS = int(sys.argv.pop(0))
            if _CONFIG_OVERRIDE_CONNS < 1:
                raise Exception()
        except:
            error('Maximum number of connections must be positive a number')
            exit(1)

    elif arg in ['--force-pull']:
        _FORCE_PULL = True

    else:
        printHelp()

init()
