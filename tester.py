# import socket
import threading
# import time
import pty, tty, termios
import subprocess
import os

def sshCon():
    master, slave = pty.openpty()
    tty.setraw(slave, when=termios.TCSANOW)
    p = subprocess.Popen(["ssh", "honeypot"], close_fds=True, shell=False, stdin=slave, stdout=slave, stderr=slave)
    os.write(master, b'exit\n')
    x = os.read(master, 3000)
    print(x)
    os.close(slave)
    subprocess.Popen.kill(p)
    os.close(master)

for _ in range(100):
    process = threading.Thread(target=sshCon)
    process.start()

