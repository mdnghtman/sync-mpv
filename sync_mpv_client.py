#!/usr/bin/env python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from python_mpv_jsonipc import MPV
from configparser import ConfigParser

import os
import sys
import time
import errno
import socket
import hashlib
import datetime

global connected
global mpv

def receive_message(client_socket):

    try:
        message_header = client_socket.recv(HEADER_LENGTH)
        message_length = int(message_header)

    except:
        return "Reading Error", "Server"

    msg = client_socket.recv(message_length)

    decrypted_msg = decrypt_message(msg[16:], msg[:16])

    return_list = decrypted_msg.split(" , ")
    if len(return_list) > 1:
        msg = return_list[0]
        user = return_list[1]

        return msg, user

    else:
        return decrypted_msg, "Server"

def pause_video(mpv):
    mpv.command("set_property","pause", True)

def play_video(mpv):
    global stop
    stop = False
    mpv.command("set_property","pause", False)

def toggle_play(mpv):
    isPaused = mpv.command("get_property","pause")
    if isPaused == True:
        play_video(mpv)
    else:
        pause_video(mpv)

def new_video(mpv, new_link):
    global t_playback
    if new_link is not None:
        mpv.play(new_link)
    t_playback = 0

def send(clientsocket, msg):
    global KEY
    cipher = AES.new(KEY, AES.MODE_CBC)
    if msg:
        if type(msg) is not bytes:
           msg = msg.encode("utf-8")

        msg = encrypt_message(msg)
        send_length = prepare_concatenation(len(msg))

        clientsocket.send(send_length)
        clientsocket.send(msg)

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

def prepare_concatenation(msg):
    global HEADER_LENGTH
    concat = str(msg).encode("utf-8")
    concat += b' ' * (HEADER_LENGTH - len(concat))
    return concat

def ready_when_seeked(mpv, value):
    while True:
        seek_bool = mpv.command("get_property","seeking")
        if seek_bool == False:
            pause_video(mpv)
            send(client_socket, f"ready {value}")
            break

def exit_gracefully():
    send(client_socket, "!DISCONNECT")

def handle_server(server, addr, MPV_PATH):
    global connected
    global t_playback
    global mpv
    global client_socket
    global stop
    global restart

    t_playback = 0
    t_restart = 0
    restart = 0
    connected = True

    operating_system_used = sys.platform

    if operating_system_used == "win32":
        while True:
            try:
                mpv = MPV(start_mpv=True, mpv_location=MPV_PATH, quit_callback=exit_gracefully)
                break
            except FileNotFoundError:
                MPV_PATH = input("mpv binary not found. Please enter the correct path to mpv.exe : ").strip('"')
                parser = ConfigParser()
                parser.read(os.getenv('APPDATA')+"/sync-mpv/sync-mpv.conf")
                parser.set('connection', 'mpv_path', MPV_PATH)
                with open(os.getenv('APPDATA')+"/sync-mpv/sync-mpv.conf", 'w') as configfile:
                    parser.write(configfile)
    else:
        mpv = MPV(start_mpv=True, quit_callback=exit_gracefully)
    mpv.command("set_property","keep-open",True)    
    mpv.command("set_property","osd-font-size","18")

    # observe playback-time to synchronize when user skips on timeline 

    @mpv.property_observer("playback-time")
    def observe_playback_time(name, value):  
        global t_playback  
        global stop
        if value is not None:
            if value > t_playback+0.25 or value < t_playback-0.1:

                if f"mpv skip {value}" != msg:
                    stop = True
                    t_playback = mpv.command("get_property", "playback-time")
                    print (t_playback)
                    send(client_socket, f"mpv skip {t_playback}")
                    ready_when_seeked(mpv, value)

            t_playback = value
    
    # observe path to distribute new video url to other clients 

    @mpv.property_observer("path")
    def observe_path(name, value):
        global stop
        print(name, value)
        if value is not None:
            print (f"New Path: {value}")
            print(msg)
            if f"mpv new {value}" != msg:   
                stop = True         
                send(client_socket, f"mpv new {value}")
                new_video(mpv, value)
                print("READY - PATH OBSERVED")
                ready_when_seeked(mpv, value)

    # when space pressed inform other clients of play/pause

    @mpv.on_key_press("space")
    def toggle_playback():
        global stop
        if stop == False:
            toggle_play(mpv)
            send(client_socket, "toggle play")

    # when q is pressed exit gracefully

    @mpv.on_key_press("q")
    def terminate():
        global connected
        print("Q")
        send(client_socket, "!DISCONNECT")
        connected = False

    @mpv.on_key_press(",")
    def frame_back_step():
        send(client_socket, "frame-back-step")
        pause_video(mpv)
        mpv.command('frame-back-step')

    @mpv.on_key_press(".")
    def frame_step():
        send(client_socket, "frame-step")
        #pause_video(mpv)
        mpv.command('frame-step')

    @mpv.on_key_press("-")
    def subtract_speed():
        print("n")
        send(client_socket, "subtract_speed")
        mpv.command('add','speed',-0.1)
        speed = mpv.command('get_property','speed')      
        mpv.command("show-text",f"Setting playback-speed to {speed}", "1500")
        print('slowed down')

    @mpv.on_key_press("+")
    def add_speed():
        print("")
        send(client_socket, "add_speed")
        mpv.command('add','speed',0.1)
        speed = mpv.command('get_property','speed')      
        mpv.command("show-text",f"Setting playback-speed to {speed}", "1500")
        print('sped up')

    @mpv.on_key_press("r")
    def resync():
        time_pos = mpv.command("get_property","time-pos")
        print(time_pos)
        send(client_socket, f"mpv skip {time_pos}")
        send(client_socket, "resync")
        ready_when_seeked(mpv, time_pos)

    @mpv.on_key_press("kp7")
    def printest():
        send(client_socket, "zoom-out")
        mpv.command('add', 'video-zoom', '-.25')

    @mpv.on_key_press("kp9")
    def printest():
        send(client_socket, "zoom-in")
        mpv.command('add', 'video-zoom', '.25')

    @mpv.on_key_press("kp8")
    def printest():
        send(client_socket, "move-up")
        mpv.command('add', 'video-pan-y', '.05')

    @mpv.on_key_press("kp2")
    def printest():
        send(client_socket, "move-down")
        mpv.command('add', 'video-pan-y', '-.05')

    @mpv.on_key_press("kp4")
    def printest():
        send(client_socket, "move-left")
        mpv.command('add', 'video-pan-x', '.05')

    @mpv.on_key_press("kp6")
    def printest():
        send(client_socket, "move-right")
        mpv.command('add', 'video-pan-x', '-.05')

    @mpv.on_key_press("kp5")
    def printest():
        send(client_socket, "reset-window")
        mpv.command('set', 'video-pan-y', '0')
        mpv.command('set', 'video-pan-x', '0')
        mpv.command('set', 'video-zoom', '0')

    print(f"[CONNECTION ESTABLISHED] to {addr}")
    
    while connected:
        global stop

        try:
            msg, user = receive_message(server)

            if msg != False:
                if msg == "!DISCONNECT":
                    connected = False
                    break

                if msg == "zoom-in":
                    mpv.command('add', 'video-zoom', '.25')
                    mpv.command("show-text",f"{user} zooms in.","1500")

                if msg == "zoom-out":
                    mpv.command('add', 'video-zoom', '-.25')
                    mpv.command("show-text",f"{user} zooms out.","1500")

                if msg == "move-up":
                    mpv.command('add', 'video-pan-y', '.05')
                    mpv.command("show-text",f"{user} zooms in.","1500")

                if msg == "move-down":
                    mpv.command('add', 'video-pan-y', '-.05')

                if msg == "move-right":
                    mpv.command('add', 'video-pan-x', '-.05')

                if msg == "move-left":
                    mpv.command('add', 'video-pan-x', '.05')

                if msg == "reset-window":
                    mpv.command('set', 'video-pan-y', '0')
                    mpv.command('set', 'video-pan-x', '0')
                    mpv.command('set', 'video-zoom', '0')
                    mpv.command("show-text",f"{user} resets the window.","1500")

                if msg == "frame-step":
                    mpv.command('frame-step')

                if msg == 'add_speed':
                    mpv.command('add','speed',0.1)
                    speed = mpv.command('get_property','speed')      
                    mpv.command("show-text",f"{user} sets playback-speed to {speed}", "1500")
    
                if msg == 'subtract_speed':
                    mpv.command('add','speed',-0.1)
                    speed = mpv.command('get_property','speed')      
                    mpv.command("show-text",f"{user} sets playback-speed to {speed}", "1500") 

                if msg == "frame-back-step":
                    mpv.command('frame-back-step')

                if msg == "mpv pause":
                    pause_video(mpv)

                if msg == "mpv terminate":
                    connected = False

                if msg == "mpv playback":
                    play_video(mpv)

                if "disconnected" in msg:
                    mpv.command("show-text",f"{msg}", "5000")

                if msg == "number of clients":
                    number_of_clients = int(msg.split[" "][3])
                    print ("Number of Clients: %s"%number_of_clients)

                if msg == "resync":
                    mpv.command("show-text",f"{user} resyncs.", "1500") 
                    
                if msg == "toggle play":
                    toggle_play(mpv)
                    mpv.command("show-text",f"{user} toggles", "1500")

                if "mpv skip" in msg:
                    stop = True
                    t_playback = float(msg.split(" ")[2])

                    if t_playback < 3600:
                        converted_time = time.strftime("%M:%S", time.gmtime(t_playback))
                    else:
                        converted_time = time.strftime("%H:%M:%S", time.gmtime(t_playback))

                    mpv.command("set_property","playback-time",msg.split(" ")[2])
                    mpv.command("show-text",f"{user} skips to {converted_time}", "1500")
               
                    ready_when_seeked(mpv, t_playback)

                if "mpv new" in msg:
                    stop = True
                    videopath = msg[8:]
                    new_video(mpv, videopath)
                    mpv.command("show-text",f"{user}: {videopath}","1500")
                    ready_when_seeked(mpv, videopath)

                if "userconnected" in msg:
                    mpv.command("show-text",f"{msg.split(' ')[1]} connected.","1500")

        except IOError as e:
            if e.errno != errno.EAGAIN and e.errno != errno.EWOULDBLOCK:
                print(e)
                print('Reading error: {}'.format(str(e)))
                continue
                #sys.exit()

            # We just did not receive anything
                #break

        except Exception as e:
            # Any other exception - something happened
            print(e)
            print('Reading error: '.format(str(e)))
            #sys.exit()

    mpv.terminate()
    client_socket.shutdown(socket.SHUT_RDWR)
    client_socket.close()

def parse_config(parser, configfile):
    operating_system_used = sys.platform

    parser.read(configfile)
    IP = parser.get('connection', 'ip')
    PORT = parser.getint('connection', 'port')
    USERNAME = parser.get('connection', 'username')
    PASSWORD = parser.get('connection', 'password')
    MPV_PATH = parser.get('connection', 'mpv_path')
    return IP, PORT, USERNAME, PASSWORD, MPV_PATH

def initialize(parser, configfile):
    operating_system_used = sys.platform
    IP = input("IP: ")
    PASSWORD = input("Password: ")
    USERNAME = input("Username: ")
    if operating_system_used == "win32":
        MPV_PATH = input("Path to mpv.exe : ").strip('"')
    else:
        MPV_PATH = "linux-binary"
    parser['connection'] = {
        'ip': IP,
        'port': '51984',
        'username': USERNAME,
        'password': PASSWORD,
        'mpv_path': MPV_PATH
    }
    with open(configfile,"w") as f:
        parser.write(f)

def main():

    global KEY
    global HEADER_LENGTH
    global client_socket

    HEADER_LENGTH = 32
    FORMAT = 'utf-8'
    DISCONNECT_MESSAGE ="!DISCONNECT"
    
    operating_system_used = sys.platform

    if operating_system_used == "win32":
        configfolder = os.getenv('APPDATA')+"/sync-mpv/"
    else:
        configfolder = os.path.expanduser("~/.config/sync-mpv/")

    configfile = configfolder+"sync-mpv.conf"

    parser = ConfigParser()

    if os.path.exists(configfolder):
        pass
    else:
        os.mkdir(configfolder)

    if not os.path.exists(configfile):
        initialize(parser, configfile)

    IP, PORT, USERNAME, PASSWORD, MPV_PATH = parse_config(parser, configfile)
    
    KEY = hashlib.sha256(PASSWORD.encode()).digest()
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Connect to a given ip and port
    while True:
        try:
            client_socket.connect((IP, PORT))
            break
        except ConnectionRefusedError:
            print("\nEnter new IP if server IP has changed.\nLeave blank otherwise.\n")

            IP = input("IP: ")
            if IP == "":
                pass

    config = ConfigParser()
    config.read(configfile)
    config.set('connection','ip', '%s' % IP)

    with open(configfile, "w") as f:
        config.write(f)

    client_socket.setblocking(True)

    send(client_socket, USERNAME)
    handle_server(client_socket, (IP, PORT), MPV_PATH) 

if __name__ == "__main__":
    main()
