# HIH Docker - High-interaction honeypot

This project is an implementation of a high-interaction honeypot that uses Docker for hosting the isolated honeypot services.

Author: Dominik Dancs (dominik@dancs.sk)

## Requirements

- Linux operating system
- Docker
- Python 3
- pip

## Installation

### Get the project code

```bash
$ git clone git@github.com:dodancs/bit-hih-docker.git
$ cd ./bit-hih-docker
```

### Set up prerequisites

As this server is written in Python and requires additional modules, you can choose to install these modules system-wide or just locally for this project by creating a virtual Python environment like so:

```bash
$ python3 -m virtualenv env
$ . ./env/bin/activate
```

This server requires several Python modules for it's full operation. All of them are listed in the [requirements.txt](requirements.txt) file. To install all of these dependencies, run the following command:

```bash
$ pip install -r ./requirements.txt
```

## Configuration

[Example configuration file](config.example.json):
```json
{
    "bind": "0.0.0.0",
    "max_connections": 1024,
    "honeypots": [{
        "name": "ssh",
        "image": "linuxserver/openssh-server:latest",
        "options": {
            "environment": [
                "HTTP_PROXY=localhost:3128"
            ],
            "command": [
                "echo", "hello"
            ],
            "network_mode": "bridge",
            "read_only": true,
            "user": "guest",
            "volumes": {
                "/docker/host/path": { "bind": "/destination/in/container", "mode": "rw" }
            }
        },
        "port": 22,
        "container_port": 2222
    }, {
        "name": "http",
        "image": "nginx:alpine",
        "options": {},
        "port": 80,
        "container_port": 80
    }]
}
```

To create a configuration file, either copy the `config.example.json` file and rename it to `config.json` or create a new file with that name.

Global configuration:

| Option | Required | Description |
|--------|----------|-------------|
| `bind` (string) | Yes | IP address to bind honeypot servers to. A value of `0.0.0.0` means bind to all available interfaces and all available IP addresses (accept connection from anywhere). |
| `max_connections` (integer) | Yes | Maximum number of accepted connections. This number is split between all honeypots equaly. |
| `honeypots` (array) | Yes | List of definitions of honeypot instances. |

Honeypot definition:

| Option | Required | Description |
|--------|----------|-------------|
| `name` (string) | Yes | Honeypot service descriptive name (for logging/visual purposes only). |
| `image` (string) | Yes | Docker image that will be hosted as the honeypot. |
| `options` (object) | Yes | Configuration options for the container. If you do not want to specify any additional configuration, provide an empty object `{}`. |
| `port` (integer) | Yes | Port that should be bound locally on the host machine. |
| `container_port` (integer) | Yes | Port that is exposed internally in the Docker container. |

Honeypot container configuration:

| Option | Required | Description |
|--------|----------|-------------|
| `command` (string) | No | Command to run inside the container. |
| `environment` (array) | No | Environment variables passed to the container. Define as an array of pairs of KEY=VALUE: `[ "HTTP_PROXY=http://localhost:3128" ]`. |
| `network` (string) | No | Name of the Docker network this container will be connected to at creation time.<br><br>_NOTE: Incompatible with `network_mode` option!_ |
| `network_mode` (string) | No | `bridge` Create a new network stack for the container on on the bridge network.<br>`none` No networking for this container.<br>`container:<name|id>` Reuse another container’s network stack.<br>`host` Use the host network stack.<br><br>_NOTE: Incompatible with `network` option!_ |
| `read_only` (boolean) | No | Mount the container’s root filesystem as read only. |
| `user` (string) | No | Username or UID to run commands as inside the container. |
| `volumes` (object) | No | A list of configurations for volumes mounted inside the container.<br>First path defines location on the host machine or a Docker volume name.<br>`bind` The path to mount the volume inside the container.<br>`mode` Access permissions: `rw` read/write or `ro` read-only. |

This configuration is validated against the JSON schema. Any incorrect values will result in server crash.

## Usage

The server itself contains basic usage information when you supply the `-h` or `--help` argument or when an unrecognized argument is supplied.

```
python3 ./server.py [OPTIONS]
    -h --help                   Show help
    -v --version                Show program version
    -d --debug                  Show debug messages
       --bind [ADDR]            Override IP address bind
       --max-connections [N]    Override maximum number of connections to the server
    -c --config [FILE]          Use custom config file location
       --force-pull             Force pull images from Docker registry
```

As you can see, you can override some configuration options from the config.json file. This may be usefull when only the bind address needs to change or maximum number of connections, but rest of the configuration remains same for multiple instances.

The `--debug` argument enables debug/verbose messaging. If you run into issues with the server, you can use this option to track down exactly what is happening.

If you supply the `--force-pull` argument, the server will update all Docker images used in the configuration every time on first start. This can be useful if you want to overwrite(update) locally stored versions of Docker images.

------

To launch the server within the virtual Python environment, use the following commands:

```
$ . ./env/bin/activate
$ python ./server.py
```
