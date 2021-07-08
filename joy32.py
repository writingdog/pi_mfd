#!/usr/bin/python3

import os
import sys
import fcntl  
import termios
import time
import random
import select
import importlib
import re
import atexit
import optparse
import asyncio
import subprocess
import websockets
import pathlib
from evdev import ecodes, list_devices, AbsInfo, InputDevice

def write_report(report):
    # This writes the raw data to the virtual USB device
    with open('/dev/hidg0', 'rb+') as fd:
        fd.write(report)
        #fd.write(report.encode())
        
def clean_up():
    write_report(b'\x00\x00\x00\x00\x00\x00')

def check_latch(b_idx,l_max,set_unset,special_trigger=False):
    global button_map
    global button_latch
    global latch_count
    global loop
    global osbmap
    global template
    global subpage
    # set_unset = 0 if the button is released, 1 if pushed

    is_latched = False

    if button_latch == b_idx and button_latch!="":
        if latch_count >= l_max:
            if set_unset == 0:
                if special_trigger==True:
                    if b_idx == 713:
                        osb_load() # 713 when triggered starts the loading mode
                    elif b_idx == 712:
                        osb_label() # 712 when triggered redraws all labels
                    elif b_idx == 304:
                        reload_server() # 304 when triggered reloads the webserver
                else:
                    is_latched = True
                    if button_map[button_latch]["s"] == 1:
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[button_latch]["o"],1))
                    else:
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[button_latch]["o"],0))
            else:
                is_latched = True
        else:
            # Have not yet hit the triggering point
            if set_unset == 0:
                # Button released, increase latch count
                if button_map[button_latch]["s"] == 1:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[button_latch]["o"],1))
                else:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[button_latch]["o"],0))
                latch_count = latch_count + 1
            is_latched = False
    else:
        # So button_latch is not currently the button we are trying to latch
        old_latch = button_latch
        latch_count = 0
        if old_latch != "":
            if button_map[old_latch]["o"] in osbmap[template][subpage]:
                if osbmap[template][subpage][button_map[old_latch]["o"]][3] != -1:
                    old_value = button_map[button_invmap[osbmap[template][subpage][button_map[old_latch]["o"]][1]]]["s"]
                    if old_value == 1:
                        print("HOLDING OLD LATCH VALUE")
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[old_latch]["o"],1))
                    else:
                        print("CLEARING OLD LATCH VALUE")
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[old_latch]["o"],-1))
                else:
                    button_map[old_latch]["s"] = 0
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[old_latch]["o"],-1))
            else:
                button_map[old_latch]["s"] = 0
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[old_latch]["o"],-1))
        button_latch = b_idx
        if set_unset == 0:
            if button_latch != "":
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[button_latch]["o"],0))
            latch_count = 1
        if latch_count >= l_max:
            is_latched = True
        else:
            is_latched = False
    return is_latched

def manage_event(e):
    global button_map
    global loop
    global q
    global button_latch
    global latch_count
    global osbmap
    global template
    global subpage
    global reload_mode
    global load_idx 
    global hat
    global mfd_side
    if e.type == ecodes.EV_SYN:
        if e.code == ecodes.SYN_MT_REPORT:
            msg = 'time {:<16} +++++++++ {} ++++++++'
        else:
            msg = 'time {:<16} --------- {} --------'
        print(msg.format(e.timestamp(), ecodes.SYN[e.code]))
    else:
        print(e.code,e.value,e.type)

        if reload_mode == True:
            # So we ignore all other regular handling...
            if e.code in button_map:
                osb_supers = []
                if e.value == 1:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],1))
                else:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],-1))
                if e.value == 0:
                    # So trigger on button release
                    for r in osbmap:
                        osb_supers.append(r)
                    if e.code == 707:
                        load_idx = load_idx - 1
                        if load_idx < 0:
                            load_idx = 0
                        osb_load()
                    elif e.code == 706:
                        load_idx = load_idx + 1
                        if load_idx >= len(osb_supers):
                            load_idx = 0
                        osb_load()
                    elif e.code == 705:
                        loop.call_soon_threadsafe(q.put_nowait,"{},{}".format("side",mfd_side))
                        if mfd_side == "left":
                            mfd_side = "right"
                        else:
                            mfd_side = "left"
                        osb_load()
                    elif e.code == 704:
                        reload_mode = False
                        osb_label()
                    elif e.code == 319:
                        for b in button_map:
                            button_map[b]["s"] = 0
                        subpage = "conf0"
                        template = osb_supers[load_idx]
                        osb_label()

        else:
            if e.code in button_map:
                v_k = ""
                hold_latch = False
                hold_no_latch = False
                special_handling = False
                if e.code == 711 or button_map[711]["s"]==1:
                    # 711 is the bottom-right rocker, so we check if this is either set NOW
                    # or if it is currently held down (s==1)
                    v_k = e.code # Set so we can properly handle the special functions.
                print("LATCH: ",button_latch,latch_count,button_map[711]["s"])
                if e.code != 711 and button_map[711]["s"] == 1:
                    # This is held to trigger special functions. So let's check if another button is ALSO held.
                    if e.code == 713:
                        special_handling = True
                        check_latch(713,2,e.value,True)
                    elif e.code == 712:
                        # 712 is the topmost of the bottom left rocker
                        special_handling = True
                        check_latch(712,2,e.value,True)
                    elif e.code == 304:
                        # 304 is OSB1
                        special_handling = True
                        check_latch(304,2,e.value,True)
                    print("LATCH: ",button_latch,latch_count,button_map[711]["s"])
                if special_handling == False:
                    if button_map[e.code]["o"] in osbmap[template][subpage]:
                        v_k = osbmap[template][subpage][button_map[e.code]["o"]][1] # The virtual key to be triggered here
                        v_k_digit = False
                        if type(v_k) == int:
                            v_k_digit = True
                        else:
                            if v_k.isdigit() == True:
                                v_k_digit = True
                        if v_k_digit == False:
                            # Special handling for when we are triggering a mode switch.
                            if e.value == 1:
                                # Do nothing when the button is PUSHED except light the OSB
                                loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],1))
                                pass
                            else:
                                # So button is now released... change the new subpage
                                loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],-1))
                                subpage = v_k
                                osb_label()
                        else:
                            v_k = button_invmap[v_k] # Get the actual USB event ID back
                            submit_value = e.value
                            if osbmap[template][subpage][button_map[e.code]["o"]][2] != -1:
                                # So this button has a latch value that is other than -1, i.e. it has to be pushed multiple times
                                if e.value == 0:
                                    is_latched = check_latch(e.code,int(osbmap[template][subpage][button_map[e.code]["o"]][2]),e.value)
                                    if is_latched == True:
                                        if osbmap[template][subpage][button_map[e.code]["o"]][3] != -1:
                                            # This switch should be left in unless released.
                                            print("Special handling for OSB OUT {}".format(e.code))
                                            if button_map[v_k]["s"] == 1:
                                                # Currently set to 1; but button has been released, so now unset
                                                print("Button is HELD")
                                                submit_value = 1
                                                loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],1))
                                            else:
                                                submit_value = 0
                                                
                                        button_map[v_k]["s"] = submit_value
                                else:
                                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],1))
                                    is_latched = check_latch(e.code,int(osbmap[template][subpage][button_map[e.code]["o"]][2]),e.value)
                                    if is_latched == True:
                                        if osbmap[template][subpage][button_map[e.code]["o"]][3] != -1:
                                            # This switch should be left in unless released.
                                            print("Special handling for OSB IN {}".format(e.code))
                                            if button_map[v_k]["s"] == 1:
                                                # Currently set to 1; but button has been released, so now unset
                                                submit_value = 0
                                            else:
                                                submit_value = 1
                                        button_map[v_k]["s"] = submit_value
                            else:
                                # So this button has no latch value; treat it normally.
                                am = {0:"0",1:"4",2:"2",3:"6"} # Special keys for hat switch handling
                                check_latch("",-1,e.value)

                                if v_k >= 850:
                                    # Special handling for the rocker switches
                                    # Hat B is 850/851/852/853
                                    if e.value == 0:
                                        hat[1] = "8"
                                    else:
                                        hat[1] = am[v_k-850]
                                elif v_k >= 800:
                                    # Hat A is 800/801/802/803
                                    if e.value == 0:
                                        hat[0] = "8"
                                    else:
                                        hat[0] = am[v_k-800]
                                else:
                                    button_map[v_k]["s"] = submit_value # Set the button_map value to be either on or off, depending.
                                    if e.value == 1:
                                        loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],1)) # Highlight the OSB
                                    else:
                                        loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",button_map[e.code]["o"],-1)) # Blank the OSB
                    else:
                        check_latch("",-1,e.value)
                        if(e.code==711):
                            # Special handling for this one button because it's a special trigger for us.
                            button_map[e.code]["s"] = e.value
            else:
                print(e.code)
        sum_buttons()
                
async def export(websocket,path):
    while True:
        message = await q.get()
        await websocket.send(message)

async def read_ws(in_url):
    global r
    while True:
        async with websockets.connect(in_url,close_timeout=0.1) as ws:
            try:
                data = await ws.recv()
                await r.put(("ws",data))
            except websockets_error:
                return None

async def process_ws(in_url):
    global r
    ws_task = asyncio.create_task(read_ws(in_url))

    while True:
        source,data = await r.get()
        if source == "ws":
            print(data)

async def evhelper(dev):
    async for ev in dev.async_read_loop():
        manage_event(ev)

def osb_load():
    global osbmap
    global template
    global subpage
    global button_map
    global button_latch
    global latch_count
    global reload_mode
    global load_idx

    button_latch = "" # Unset button latch
    latch_count = 0 # Reset latch count

    if reload_mode == False:
        reload_mode = True
        reload_maps()
        for b in button_map:
            if b == 319:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,"COMMIT"))
            elif b == 707:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,"UP"))
            elif b == 706:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,"DN"))
            elif b == 705:
                if mfd_side == "left":
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,"RIGHT"))
                else:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,"LEFT"))
            elif b == 704:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,"EXIT"))
            else:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,""))
    else:
        if mfd_side == "left":
            loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[705]["o"],-1,"RIGHT"))
        else:
            loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[705]["o"],-1,"LEFT"))
    post_str = ""
    osbmap_supers = []
    for r in osbmap:
        osbmap_supers.append(r)
    print(osbmap)
    print("LOADIDX",load_idx)
    for i in range(0,len(osbmap_supers)):
        print(load_idx,osbmap_supers[i])
        if i == load_idx:
            post_str = "{}*{}*<br />".format(post_str,osbmap_supers[i])
        else:
            post_str = "{}{}<br />".format(post_str,osbmap_supers[i])
    loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("ctxt",-1,-1,post_str))


def osb_label():
    global osbmap
    global osbtxt
    global template
    global subpage
    global button_map
    global button_latch
    global latch_count
    global reload_mode

    reload_mode = False

    print("Rebuilding labels...")
    button_latch = ""
    latch_count = 0

    for b in button_map:
        #if b!=713:
        #    button_map[b]["s"] = 0
        d_v = -1
        if button_map[b]["o"] in osbmap[template][subpage]:
            if type(osbmap[template][subpage][button_map[b]["o"]][1]) == int:
                if button_map[button_invmap[osbmap[template][subpage][button_map[b]["o"]][1]]]["s"] == 1:
                    d_v = 1
            start_display = -1
            o_v = button_map[b]["o"]
            o_m = osbmap[template][subpage][o_v]
            print("O_Translate: {}".format(o_v))
            print(o_m)
            if o_m[3] != -1:
                # So in the OSB template, this is specified as sticky. So we need to check the value.
                print(button_invmap[o_m[1]])
                print(button_map[button_invmap[o_m[1]]])
            loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],d_v,osbmap[template][subpage][button_map[b]["o"]][0]))
        else:
            if button_map[b]["o"] >= 1 and button_map[b]["o"] <= 20:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1," "))
    loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("ctxt",-1,-1,osbtxt[template][subpage]))
       
def sum_buttons():
    global button_map
    global hat
    zero_s = "00 00 {}{} 00 00 00 00".format(hat[0],hat[1])
    zero = bytearray.fromhex(zero_s)
    zero_i = int.from_bytes(zero,"big")
    for b in button_map:
        zero_i = zero_i + (button_map[b]["i"]*button_map[b]["s"])
    zero_b = zero_i.to_bytes(7,byteorder="big")
    write_report(zero_b)

def reload_maps():
    global osbmap
    global osbtxt

    file_loc = ["pi","mfd_l","mfd_r"] # Possible usernames

    for f in file_loc:
        if pathlib.Path("/home/{}/pi_mfd/config.txt".format(f)).is_file() == True:
            fpath = "/home/{}/pi_mfd/config.txt".format(f)
    with open(fpath) as f:
        data = f.readlines()

    mainpage = ""
    subpage = ""

    osbmap = {}
    osbtxt = {}

    for d in data:
        # Lines can begin either with -, --, or an integer
        d = d.strip()
        if len(d) > 0:
            if d[:1] == "-":
                if d[:2] == "--":
                    # Then a subpage is being defined.
                    line = d.split(" ")
                    subpage = line[0][2:]
                    subpage_desc = d[(len(subpage)+3):]
                    osbtxt[mainpage][subpage] = subpage_desc
                    osbmap[mainpage][subpage] = {}
                else:
                    mainpage = d[1:]
                    osbmap[mainpage] = {}
                    osbtxt[mainpage] = {}
            else:
                if d[0:1].isdigit() == True:
                    # This means that we are defining a new OSB / VK relationship
                    is_latch = -1
                    is_held = -1
                    vk_val = ""
                    d_vals = d.split(",")
                    #print(d_vals)
                    if len(d_vals)>4:
                        is_held = d_vals[4]
                    if len(d_vals)>3:
                        is_latch = d_vals[3]
                    if d_vals[2].isdigit() == True:
                        vk_val = int(d_vals[2])
                    else:
                        vk_val = d_vals[2]
                    osbmap[mainpage][subpage][int(d_vals[0])] = [d_vals[1],vk_val,is_latch,is_held]
    #print(osbmap)
    #print(osbtxt)
                    

def reload_server():
    global button_map
    global latch_count
    global button_latch

    file_loc = ["pi","mfd_l","mfd_r"] # Possible usernames

    for f in file_loc:
        if pathlib.Path("/home/{}/pi_mfd/mfd.html".format(f)).is_file() == True:
            fpath = "/home/{}/pi_mfd/mfd.html".format(f)
            f_user = f

    for b in button_map:
        if b!=711:
            button_map[b]["s"] = 0 # Set all buttons but the reset switch to 0 value
    subprocess.run(["killall","chromium-browse"])
    subprocess.Popen(["sudo","-u","{}".format(f_user),"/usr/bin/chromium-browser","--kiosk",fpath])
    print("Reloading webserver...")
    latch_count = 0
    button_latch = ""

'''
INITIALIZATION CODE HERE
'''

button_map = {
    304:{"b":b"\x00\x00\x00\x01\x00\x00\x00","i":0,"s":0,"o":1},
    305:{"b":b"\x00\x00\x00\x02\x00\x00\x00","i":0,"s":0,"o":2},
    306:{"b":b"\x00\x00\x00\x04\x00\x00\x00","i":0,"s":0,"o":3},
    307:{"b":b"\x00\x00\x00\x08\x00\x00\x00","i":0,"s":0,"o":4},
    308:{"b":b"\x00\x00\x00\x10\x00\x00\x00","i":0,"s":0,"o":5},
    309:{"b":b"\x00\x00\x00\x20\x00\x00\x00","i":0,"s":0,"o":6},
    310:{"b":b"\x00\x00\x00\x40\x00\x00\x00","i":0,"s":0,"o":7},
    311:{"b":b"\x00\x00\x00\x80\x00\x00\x00","i":0,"s":0,"o":8},
    312:{"b":b"\x00\x00\x00\x00\x01\x00\x00","i":0,"s":0,"o":9},
    313:{"b":b"\x00\x00\x00\x00\x02\x00\x00","i":0,"s":0,"o":10},
    314:{"b":b"\x00\x00\x00\x00\x04\x00\x00","i":0,"s":0,"o":11},
    315:{"b":b"\x00\x00\x00\x00\x08\x00\x00","i":0,"s":0,"o":12},
    316:{"b":b"\x00\x00\x00\x00\x10\x00\x00","i":0,"s":0,"o":13},
    317:{"b":b"\x00\x00\x00\x00\x20\x00\x00","i":0,"s":0,"o":14},
    318:{"b":b"\x00\x00\x00\x00\x40\x00\x00","i":0,"s":0,"o":15},
    319:{"b":b"\x00\x00\x00\x00\x80\x00\x00","i":0,"s":0,"o":16},
    704:{"b":b"\x00\x00\x00\x00\x00\x01\x00","i":0,"s":0,"o":17},
    705:{"b":b"\x00\x00\x00\x00\x00\x02\x00","i":0,"s":0,"o":18},
    706:{"b":b"\x00\x00\x00\x00\x00\x04\x00","i":0,"s":0,"o":19},
    707:{"b":b"\x00\x00\x00\x00\x00\x08\x00","i":0,"s":0,"o":20},
    714:{"b":b"\x00\x00\x00\x00\x00\x10\x00","i":0,"s":0,"o":21},
    715:{"b":b"\x00\x00\x00\x00\x00\x20\x00","i":0,"s":0,"o":22},
    708:{"b":b"\x00\x00\x00\x00\x00\x40\x00","i":0,"s":0,"o":23},
    709:{"b":b"\x00\x00\x00\x00\x00\x80\x00","i":0,"s":0,"o":24},
    710:{"b":b"\x00\x00\x00\x00\x00\x00\x01","i":0,"s":0,"o":25},
    711:{"b":b"\x00\x00\x00\x00\x00\x00\x02","i":0,"s":0,"o":26},
    712:{"b":b"\x00\x00\x00\x00\x00\x00\x04","i":0,"s":0,"o":27},
    713:{"b":b"\x00\x00\x00\x00\x00\x00\x08","i":0,"s":0,"o":28},
    716:{"b":b"\x00\x00\x00\x00\x00\x00\x10","i":0,"s":0,"o":29},
    717:{"b":b"\x00\x00\x00\x00\x00\x00\x20","i":0,"s":0,"o":30},
    718:{"b":b"\x00\x00\x00\x00\x00\x00\x40","i":0,"s":0,"o":31},
    719:{"b":b"\x00\x00\x00\x00\x00\x00\x80","i":0,"s":0,"o":32},
    800:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":800},
    801:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":801},
    802:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":802},
    803:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":803},
    850:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":850},
    851:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":851},
    852:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":852},
    853:{"b":b"\x00\x00\x00\x00\x00\x00\x00","i":0,"s":0,"o":853},
    }

    #     703:{"b":b"\x00\x00\x00\x00\x80\x00\x00","i":0,"s":0,"o":16},


# 1-20: OSB 1-20
# 21/22 GAIN UP/DOWN 
# 23/24 SYM UP/DOWN
# 25/26 BRT UP/DOWN
# 27/28 CON UP/DOWN
# 29-32 Virtual buttons

button_invmap = {1:304,2:305,3:306,4:307,5:308,6:309,7:310,8:311,9:312,10:313,11:314,12:315,13:316,14:317,15:318,16:319,17:704,18:705,19:706,20:707,21:714,22:715,23:708,24:709,25:710,26:711,27:712,28:713,29:716,30:717,31:718,32:719,800:800,801:801,802:802,803:803,850:850,851:851,852:852,853:853}

for b in button_map:
    button_map[b]["i"] = int.from_bytes(button_map[b]["b"],"big")

#print(button_map)

template = "BLANK"
subpage = "conf0"
button_latch = ""
latch_count = 0
reload_mode = False
load_idx = 0
hat = ["8","8"]
mfd_side = "left" # Which side to display the MFD on (defaults to left)

osbmap = {} # Formerly stored in joy32_params.py
osbtxt = {} # Formerly stored in joy32_params.py

reload_maps() # Populate osbmap and osbtxt values

#print(osbmap["LABELED"])

q = asyncio.Queue() # output queue
r = asyncio.Queue() # input queue

loop = asyncio.get_event_loop()

start_server = websockets.serve(export,"127.0.0.1",5678)
dev = InputDevice("/dev/input/event0")

loop.run_until_complete(start_server)
loop.run_until_complete(process_ws("ws://127.0.0.1:5678"))
loop.run_until_complete(evhelper(dev))
loop.run_forever()