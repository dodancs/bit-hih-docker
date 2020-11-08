from termcolor import colored, cprint
import logging
import logging.handlers
import os

_VERSION = '1.0.0'  # app version
_DEBUG = False  # enable or disable debugging output
_APP_NAME = 'hih-docker'

########################
#       Logging        #
########################

logger = logging.getLogger(_APP_NAME)
logging_format = logging.Formatter(
    '%(name)s: [%(levelname)s] %(message)s'
)
handler_linux = logging.handlers.SysLogHandler(address='/dev/log')
handler_linux.setFormatter(logging_format)
logger.addHandler(handler_linux)
logger.setLevel(logging.INFO)

########################
#         Utils        #
########################

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

########################
#      Exceptions      #
########################


class CannotBindPort(Exception):
    def __init__(self, honeypot):
        self.honeypot = honeypot
        self.message = 'Cannot bind local port \'{}\' - already in use!'.format(
            honeypot['port'])
        super().__init__(self.message)