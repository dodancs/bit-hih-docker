import json
from jsonschema import validate
import os
import sys
from termcolor import colored, cprint
import uuid
import logging
import logging.handlers
import docker
import ipaddress

#####################
#      Logging      #
#####################

logger = logging.getLogger('canary-server')
logging_format = logging.Formatter(
    '%(name)s: [%(levelname)s] %(message)s'
)
if os.name != 'nt':
    handler_linux = logging.handlers.SysLogHandler(address='/dev/log')
    handler_linux.setFormatter(logging_format)
    logger.addHandler(handler_linux)
logger.setLevel(logging.INFO)

#####################
#       Helpers     #
#####################

_VERSION = '1.0.0'
_DEBUG = False
_CONFIG_FILE = 'config.json'
_CONFIG = None
_CONFIG_OVERRIDE_BIND = None
_CONFIG_OVERRIDE_CONNS = None
_DOCKER_CLIENT = None
_DOCKER_IMAGES = []
_PULL = True


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
       --dont-pull              Don\'t pull images from Docker hub\
    ', 'cyan')
    exit(1)


def printVersion():
    global _VERSION
    cprint('HIH-Docker version {}'.format(_VERSION), 'cyan')
    exit(0)

#####################
#   Config loader   #
#####################


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

    debug(_CONFIG)


def init():
    global _CONFIG, _DOCKER_IMAGES, _DOCKER_CLIENT

    # initialize Docker connector
    _DOCKER_CLIENT = docker.from_env()
    debug(_DOCKER_CLIENT.containers.list())

    # initialize script
    loadConfig()

    # scan for used images
    for honeypot in _CONFIG['honeypots']:
        if honeypot['image'] not in _DOCKER_IMAGES:
            _DOCKER_IMAGES.append(honeypot['image'])
    debug(_DOCKER_IMAGES)

    # pull docker images
    if _PULL:
        info('Updating Docker images...')
        for image in _DOCKER_IMAGES:
            info('Pulling {}...'.format(image))
            _DOCKER_CLIENT.images.pull(image)


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

    elif arg in ['--dont-pull']:
        _PULL = False

    else:
        printHelp()

init()
