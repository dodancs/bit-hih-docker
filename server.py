import json
from jsonschema import validate
import os
import sys
from termcolor import colored, cprint
import uuid
import logging
import logging.handlers
import docker

#####################
#      Logging      #
#####################

logger = logging.getLogger('canary-server')
handler = logging.handlers.SysLogHandler(address='/dev/log')
handler.setFormatter(logging.Formatter(
    '%(name)s: [%(levelname)s] %(message)s'
))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

#####################
#       Helpers     #
#####################

_DEBUG = False
_CONFIG = None
_DOCKER_CLIENT = None
_DOCKER_IMAGES = []


def info(message):
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
        'Please run sync.py with a parameter:\n~$ python3 ./sync.py {parameter}\n\
            \t-s\tSetup basic server environment\n\
            \t-d\tRun in daemon mode - automatically check and sync canaries', 'cyan')
    exit(1)

#####################
#   Config loader   #
#####################


def loadConfig():
    global _CONFIG

    info('Loading server configuration...')

    _CONFIG_FILENAME = 'config.json'
    _CONFIG_SCHEMA = json.loads(open('config.schema.json').read())

    try:
        _CONFIG = json.loads(open(_CONFIG_FILENAME).read())
    except Exception as e:
        error('Cannot open configuration file! Looking for {}'.format(
            os.path.join(os.getcwd(), _CONFIG_FILENAME)))
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


########################
#   Argument parsing   #
########################

sys.argv.pop()
for arg in sys.argv:

    if '--help' in sys.argv or '-h' in sys.argv:
        printHelp()

    # enable debugging
    elif '--debug' in sys.argv or '-D' in sys.argv:
        _DEBUG = True
        logger.setLevel(logging.DEBUG)

    else:
        printHelp()

init()
