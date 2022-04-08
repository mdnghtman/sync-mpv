#!/usr/bin/env python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from configparser import ConfigParser
import socket
import select
import hashlib
import sys
import threading
import errno
import time
import os


HEADER_LENGTH = 32

IP = "0.0.0.0"
PORT = 51984
FORMAT = 'utf-8'
DISCONNECT_MESSAGE ="!DISCONNECT"

def prepare_concatenation(msg):

    concat = str(msg).encode("utf-8")
    concat += b' ' * (HEADER_LENGTH - len(concat))
    return concat

def send(clientsocket, msg):

    global KEY

    cipher = AES.new(KEY, AES.MODE_CBC)

    if type(msg) is not bytes:
        msg = msg.encode("utf-8")

    msg = encrypt_message(msg)
    send_length = prepare_concatenation(len(msg))

    clientsocket.sendall(send_length)
    clientsocket.sendall(msg)

def encrypt_message(msg):
    
    global KEY

    cipher = AES.new(KEY, AES.MODE_CBC)

    encrypted_msg = cipher.encrypt(pad(msg,AES.block_size))
    encrypted_msg = cipher.iv + encrypted_msg

    return encrypted_msg

def decrypt_message(msg, IV):
    
    global KEY

    cipher = AES.new(KEY, AES.MODE_CBC, IV)
    decrypted_msg = unpad(cipher.decrypt(msg), AES.block_size)

    try:
        decrypted_msg = decrypted_msg.decode("utf-8")
    except UnicodeDecodeError:
        pass

    return decrypted_msg

def receive_message(client_socket):

    try:
        message_header = client_socket.recv(HEADER_LENGTH)

    except:
        return False

    message_length = int(message_header)

    msg = client_socket.recv(message_length)
    decrypted_msg = decrypt_message(msg[16:], msg[:16])

    return decrypted_msg

def parse_config(parser, configfile):

    parser.read(configfile)
    return parser.get('connection', 'password')

def initialize(parser, configfile):
    print("Decide for a 16-digit password.\nPassword will be saved under '~/.config/sync-mpv/serverpassword.conf'\n")
    while True:
        PASSWORD = input("Password: ")
        if len(PASSWORD) == 16:
            break
        print(f"\nPassword is {len(PASSWORD)} digits long. Choose another.")

    parser['connection'] = {
        'password': '%s'%PASSWORD,
    }
    with open(configfile,"w") as f:
        parser.write(f)
    return PASSWORD

def main():
    global KEY

    configfolder = os.path.expanduser("~/.config/sync-mpv/")
    configfile = os.path.expanduser("~/.config/sync-mpv/serverpassword.conf")
    parser = ConfigParser()

    if os.path.exists(configfolder):
        pass
    else:
        os.mkdir(configfolder)

    if os.path.exists(configfile):
        PASSWORD = parse_config(parser, configfile)
    else:
        PASSWORD = initialize(parser, configfile)

    KEY = hashlib.sha256(PASSWORD.encode()).digest()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((IP, PORT))
    server_socket.listen()

    sockets_list = [server_socket]
    clients = {}

    print(f'Listening for connections on {IP}:{PORT}...')

    readycounter = 0
    last_video = None
    while True:
        read_sockets, _, exception_sockets = select.select(sockets_list, [], sockets_list)

        for notified_socket in read_sockets:

            # If notified socket is a server socket - new connection, accept it
            if notified_socket == server_socket:
                readycounter = 0
                
                client_socket, client_address = server_socket.accept()

                user = receive_message(client_socket)

                # If False - client disconnected before he sent his name
                if user is False or user == b'':
                    continue

                sockets_list.append(client_socket)
                clients[client_socket] = user

                print('Accepted new connection from {}:{}, username: {}'.format(*client_address, user))

                for client in clients:
                    send(client, f"number of clients {len(clients)}")

                    if client != server_socket and client != client_socket:
                        send(client, f"userconnected {user}")

                    if last_video is not None:
                        send(client, f"mpv new {last_video}")

            # Else existing socket is sending a message
            else:

                try:
                    message = receive_message(notified_socket)

                # If False, client disconnected, cleanup
                except:
                    #print('Closed connection from: {}'.format(clients[notified_socket]))
                    #sockets_list.remove(notified_socket)

                    #del clients[notified_socket]
                    #readycounter = 0

                    #for client in clients:
                    #    send(client, "number of clients %s"%len(clients))

                    continue

                if message != False:
                    
                # Get user by notified socket, so we will know who sent the message
                    user = clients[notified_socket]

                    print(f'Received message from {user}: {message}')

                    if "mpv new" in message:
                        readycounter = 0
                        last_video = message[8:]

                    #if "mpv skip" in message:
                    #    readycounter = 0

                    if "ready" in message:
                        print(len(clients))
                        readycounter += 1
                        print("readycounter ", readycounter)

                    else: 
                        readycounter = 0

                    if message == "!DISCONNECT":
                        for client_socket in clients:
                            if client_socket != notified_socket:
                                send(client_socket, f"{clients[notified_socket]} disconnected. , {user}")

                        send(notified_socket, message)
                        sockets_list.remove(notified_socket)
                        del clients[notified_socket]

                    if readycounter == len(clients):
                        for client_socket in clients:
                            send(client_socket, "mpv playback")
                        readycounter = 0

                    for client_socket in clients:
                        if "!DISCONNECT" != message:
                            if client_socket != notified_socket:
                                send(client_socket, f"{message} , {user}")
                             
        # It's not really necessary to have this, but will handle some socket exceptions just in case
        for notified_socket in exception_sockets:

            # Remove from list for socket.socket()
            sockets_list.remove(notified_socket)

            # Remove from our list of users
            del clients[notified_socket]

if __name__ == "__main__":
    main()
