import json
from jsonschema import validate
import sys
import signal
import docker
import ipaddress
import socket
import threading
import time
import itertools
from Honeypot import Honeypot
import Utils
from Utils import debug, info, error, logging, printHelp, printVersion, logger

_CONFIG_FILE = 'config.json'  # config file name
_CONFIG = None  # parsed configuration
_DOCKER_CLIENT = None  # Docker client
_DOCKER_IMAGES = []  # all docker images used
_FORCE_PULL = False  # dorce pull fresh docker images
_HONEYPOTS = [] # active honeypots

def stopAll(signal, frame):
    info('Stopping all servers...')
    
    for honeypot in _HONEYPOTS:
        honeypot.kill()

    info('All servers stopped successfully.')
    exit(0)


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

    _CONFIG['honeypots_num'] = len(_CONFIG['honeypots'])

    info('Server configuration loaded successfully!')

    debug('Loaded config: {}'.format(_CONFIG))

########################
#    Initialization    #
########################


def init():
    global _CONFIG, _DOCKER_IMAGES, _DOCKER_CLIENT, _FORCE_PULL

    signal.signal(signal.SIGTERM, stopAll)
    signal.signal(signal.SIGINT, stopAll)

    # initialize Docker connector
    _DOCKER_CLIENT = docker.from_env()
    debug('List of running docker containers: {}'.format(
        _DOCKER_CLIENT.containers.list()))

    # initialize script
    loadConfig()

    # scan for used images
    for honeypot in _CONFIG['honeypots']:
        if honeypot['image'] not in _DOCKER_IMAGES:
            _DOCKER_IMAGES.append(honeypot['image'])

    info('Loaded {} honeypots.'.format(_CONFIG['honeypots_num']))

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
        _HONEYPOTS.append(Honeypot(config=_CONFIG, honeypot=honeypot, docker_client=_DOCKER_CLIENT))

    while True:
        time.sleep(1)


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
        Utils._DEBUG = True
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

        override_bind = sys.argv.pop(0)
        try:
            ipaddress.IPv4Address(override_bind)
            _CONFIG['bind'] = override_bind
        except:
            error('Please specify a valid IP address')
            exit(1)

    elif arg in ['--max-connections']:
        if len(sys.argv) < 1:
            error('Missing arguments')
            exit(1)
        try:
            override_cons = int(sys.argv.pop(0))
            if override_cons < 1:
                raise Exception()
            _CONFIG['max_connections'] = override_cons
        except:
            error('Maximum number of connections must be positive a number')
            exit(1)

    elif arg in ['--force-pull']:
        _FORCE_PULL = True

    else:
        printHelp()

init()
