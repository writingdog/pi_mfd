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
from evdev import ecodes, list_devices, AbsInfo, InputDevice, events

remote_ip = ""
button_count = "b32"
print_report = False
in_extra_maps = False # Hide certain unused maps.

# For more easily building the button maps rather than doing everything manually.
bitmap = {0:"00 00 00 00",1:"01 00 00 00",2:"02 00 00 00",3:"04 00 00 00",4:"08 00 00 00",5:"10 00 00 00",6:"20 00 00 00",7:"40 00 00 00",8:"80 00 00 00",9:"00 01 00 00",10:"00 02 00 00",11:"00 04 00 00",12:"00 08 00 00",13:"00 10 00 00",14:"00 20 00 00",15:"00 40 00 00",16:"00 80 00 00",17:"00 00 01 00",18:"00 00 02 00",19:"00 00 04 00",20:"00 00 08 00",21:"00 00 10 00",22:"00 00 20 00",23:"00 00 40 00",24:"00 00 80 00",25:"00 00 00 01",26:"00 00 00 02",27:"00 00 00 04",28:"00 00 00 08",29:"00 00 00 10",30:"00 00 00 20",31:"00 00 00 40",32:"00 00 00 80"}
osb_physicals = {0:0,1:304,2:305,3:306,4:307,5:308,6:309,7:310,8:311,9:312,10:313,11:314,12:315,13:316,14:317,15:318,16:319,17:704,18:705,19:706,20:707,21:714,22:715,23:708,24:709,25:710,26:711,27:712,28:713,29:716,30:717,31:718,32:719,101:800,102:801,103:802,104:803,105:804,106:805,107:806,108:807,109:850,110:851,111:852,112:853,113:854,114:855,115:856,116:857}

try:
    with open("../mfd.txt") as f:
        data = f.readlines()
        print(data)
        for d in data:
            if "." in d: 
                # e.g., in this case, if it contains a period it is an IP address
                remote_ip = d.strip()
            elif "b" in d:
                if d.strip() == "b96x":
                    button_count = "b96"
                    print_report = True
                elif d.strip() == "b96":
                    button_count = "b96"
                    print_report = False
                elif d.strip() == "b64x":
                    button_count = "b64"
                    print_report = True
                elif d.strip() == "b32x":
                    button_count = "b32"
                    print_report = True
                elif d.strip() == "b64":
                    button_count = "b64"
                else:
                    button_count = "b32"
except:
    remote_ip = "127.0.0.1"

print(remote_ip,button_count)

def write_report(report):
    # This writes the raw data to the virtual USB device
    try:
        with open('/dev/hidg0', 'rb+') as fd:
            fd.write(report)
            if print_report == True:
                print(report)

    except:
        print("Not able to write event.")
        loop.call_soon_threadsafe(q.put_nowait,"ctxt_a,0,0,{}".format("Error: couldn't send last message to the virtual device."))
        #fd.write(report.encode())

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
    submap = osbmap[template][subpage] # just to keep this code cleaner

    
    if button_latch == b_idx and button_latch!="":
        logical_btn = button_map[button_latch]["o"] # The logical OSB button that is referred to by the latched button
        if logical_btn in submap:
            virtual_btn = submap[logical_btn] # The virtual button as defined in config.txt
        else:
            virtual_btn = {"vk":0,"held":False} # Define a dummy button if it isn't defined in the OSB Map
        if latch_count >= l_max:
            # So this means any triggered actions SHOULD fire
            if set_unset == 0:
                # Button RELEASED
                if special_trigger==True:
                    if b_idx == 713:
                        osb_load() # 713 when triggered starts the loading mode
                    elif b_idx == 712:
                        osb_label() # 712 when triggered redraws all labels
                    elif b_idx == 304:
                        reload_server() # 304 when triggered reloads the webserver
                    elif b_idx == 305:
                        reload_server_nonhost() # 305 when triggered reloads the webserver in the non-host mode (both MFDs)
                    elif b_idx == 306:
                        reload_all() # 306 (OSB3) when triggered kills everything and restarts it
                else:
                    is_latched = True
                    if virtual_btn["held"] != False:
                        hold_value = button_map[button_invmap[virtual_btn["vk"]]]["s"]
                        if hold_value == 1:
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",logical_btn))
                        else:
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},0".format("osb",logical_btn))
                    else:
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},0".format("osb",logical_btn))
            else:
                # Button FIRED
                is_latched = True
        else:
            # Have not yet hit the triggering point
            if set_unset == 0:
                # Button released, increase latch count
                if button_map[button_latch]["s"] == 1:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",logical_btn))
                else:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},0".format("osb",logical_btn))
                latch_count = latch_count + 1
            is_latched = False
    else:
        # So button_latch is not currently the button we are trying to latch
        old_latch = button_latch
        latch_count = 0 # Reset the latch count to 0
        if old_latch != "":
            logical_btn_old = button_map[old_latch]["o"]
            if logical_btn_old in submap:
                # Check to see if the older latched button was defined.
                if submap[logical_btn_old]["held"] != False:
                    # So this button is defined as being held, which means it should be left in when released
                    old_value = button_map[button_invmap[logical_btn_old]]["s"]
                    if old_value == 1:
                        print("HOLDING OLD LATCH VALUE")
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",logical_btn_old))
                    else:
                        print("CLEARING OLD LATCH VALUE")
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",logical_btn_old))
                else:
                    # This is a normal button; unset its value
                    button_map[old_latch]["s"] = 0
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",logical_btn_old))
            else:
                # Older latched button wasn't defined
                button_map[old_latch]["s"] = 0
                loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",logical_btn_old))
        button_latch = b_idx
        if button_latch!="":
            # Because it's possible that the latch is now no button
            logical_btn = button_map[button_latch]["o"] # The logical OSB button that is referred to by the latched button
            if set_unset == 0:
                # Button released
                if button_latch != "":
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},0".format("osb",logical_btn))
                latch_count = 1
            if latch_count >= l_max:
                is_latched = True
            else:
                is_latched = False
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
    global special_active # This is an external variable for button 26 / event 711

    submap = osbmap[template][subpage]
    if e.type == ecodes.EV_SYN:
        if e.code == ecodes.SYN_MT_REPORT:
            msg = 'time {:<16} +++++++++ {} ++++++++'
        else:
            msg = 'time {:<16} --------- {} --------'
        print(msg.format(e.timestamp(), ecodes.SYN[e.code]))
    else:
        print(e.code,e.value,e.type)
        if e.code == 4:
            # Status message, not a button press, ignore
            pass
        else:
            
            if e.code in button_status:
                button_status[e.code]["s"] = e.value # so the button_status map should always store whether this button is currently ON or OFF
                button_status[e.code]["last"] = button_status[e.code]["time"]
                button_status[e.code]["time"] = e.timestamp()
            else:
                button_status[e.code] = {
                    "s":e.value,
                    "last":e.timestamp(),
                    "time":e.timestamp()
                }
            # Handling button press or release
            if reload_mode == True:
                event_reload(e) # Special handling for this case
            else:
                if e.code in button_map:
                    physical_btn = button_map[e.code]["o"]
                    v_k = ""
                    special_handling = False
                    if e.code == 711 or special_active == True:
                        # 711 is the bottom-right rocker, so we check if this is either set NOW
                        # or if it is currently held down (s==1)
                        v_k = e.code # Set so we can properly handle the special functions.
                    print("LATCH: ",button_latch,latch_count,button_map[711]["s"])
                    if e.code != 711 and special_active == True:
                        # This is held to trigger special functions. So let's check if another button is ALSO held.
                        if e.code == 713:
                            special_handling = True
                            check_latch(713,2,e.value,True)
                        elif e.code == 712:
                            # 712 is the topmost of the bottom left rocker
                            special_handling = True
                            check_latch(712,2,e.value,True)
                        elif e.code == 304:
                            # 304 is OSB1, used to trigger webserver restart
                            special_handling = True
                            check_latch(304,2,e.value,True)
                        elif e.code == 305:
                            # 305 is OSB2, used to trigger webserver restart
                            special_handling = True
                            check_latch(305,2,e.value,True)
                        elif e.code == 306:
                            # 306 is OSB3, used to trigger restart
                            special_handling = True
                            check_latch(306,2,e.value,True)
                        print("LATCH: ",button_latch,latch_count,button_map[711]["s"])
                    if special_handling == False:
                        # So we are not triggering any potential control modes here
                        event_normal(e,submap,physical_btn)
                else:
                    print(e.code)
            if(e.code==711):
                # Special handling for this one button because it's a special trigger for us.
                if e.value == 1:
                    special_active = True
                else:
                    special_active = False
        sum_buttons()

def event_reload(e):
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
    global in_extra_maps
    
    button_specials = {318:"pos,x,-1",317:"pos,x,1",316:"pos,r",315:"pos,y,-1",314:"pos,y,1",309:"size,x,-.01",310:"size,x,.01",311:"size,r",312:"size,y,-.01",313:"size,y,.01"}
    if (mfd_side=="left"):
        button_specials[705] = "side,left"
    else:
        button_specials[705] = "side,right"

    submap = osbmap[template][subpage]
    if e.code in button_map:
        physical_btn = button_map[e.code]["o"]
        osb_supers = []
        if e.value == 1:
            loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",physical_btn))
        else:
            loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",physical_btn))
        if e.value == 0:
            # So trigger on button release
            if in_extra_maps == True:
                osb_supers.append("Return")
            for r in osbmap:
                if osbmap[r].extra == in_extra_maps:
                    # If we're showing extra profiles, use that list.
                    # Which means the osbmap.extra will be set "true"
                    osb_supers.append(r)
            if in_extra_maps == False:
                osb_supers.append("More")
            if e.code in button_specials:
                # So this is a code that should also send a special command to the MFD display logic
                loop.call_soon_threadsafe(q.put_nowait,"{}".format(button_specials[e.code]))
            if e.code == 707:
                # UP button in LOAD mode
                load_idx = load_idx - 1
                if load_idx < 0:
                    load_idx = len(osb_supers)-1
                osb_load()
            elif e.code == 706:
                # DOWN button in LOAD mode
                load_idx = load_idx + 1
                if load_idx >= len(osb_supers):
                    load_idx = 0
                osb_load()
            elif e.code == 705:
                # This switches the side of the display the MFD believes it is on.
                if mfd_side == "left":
                    mfd_side = "right"
                else:
                    mfd_side = "left"
                osb_load()
            elif e.code == 704:
                reload_mode = False
                osb_label()
            elif e.code == 319:
                # Commit button in LOAD mode
                if osb_supers[load_idx] == "Return":
                    in_extra_maps = False
                    load_idx = 0
                    osb_load()
                elif osb_supers[load_idx] == "More":
                    in_extra_maps = True
                    load_idx = 0
                    osb_load()
                else:
                    for b in button_map:
                        button_map[b]["s"] = 0
                    subpage = "conf0"
                    template = osb_supers[load_idx]
                    osb_label(True) # call osb_label with a mode switch to read in DEFAULT button values

def event_normal(e,submap,physical_btn,force_trigger=False):
    # Normal event handler (i.e. button push/release when not in any special mode)
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

    force_delay = False
    process_remaining = True

    submap = osbmap[template][subpage]
    if physical_btn in submap:
        virtual_btn = submap[physical_btn]
        if virtual_btn["delay"] != False:
            if force_trigger == False or e.value == 0:
                # This action was delayed, and we haven't timed out on it yet.
                # But always trigger when the button is released.
                force_delay = True
        if virtual_btn["page"] != False or virtual_btn["long_page"] != False:
            # Special handling for when we are triggering a mode switch.
            # This can be true if either the default action OR the long-hold action is a page switch
            # We add in the delay factor here in case we only trigger the page switch on a long hold
            if force_trigger == False:
                # So this was called NOT from a delay
                print("Called without force_trigger")
                if virtual_btn["page"] == True:
                    print("Virtual button is a page switcher")
                    # The default action is a mode switch
                    if e.value == 1:
                        print("Virtual button is a page switcher, triggering ON")
                        # Do nothing when the button is PUSHED except light the OSB
                        process_remaining = False
                        if virtual_btn["delay"] != False:
                            print("Virtual button has a delay, so halting remaining")
                            loop.call_later(float(virtual_btn["delay"])/1000,event_delayed,e,submap,physical_btn)
                        else:
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",physical_btn))
                        pass
                    else:
                        # So button is now released... change the new subpage
                        print("Virtual button was released")
                        if virtual_btn["delay"] != False:
                            # So button has a delay.
                            print("Virtual button has a delay set")
                            if virtual_btn["long_page"] == False:
                                # So this is a conventional button press.
                                v_k_l = button_invmap[virtual_btn["long"]]
                                if button_map[v_k_l]["s"] == 1:
                                    # The button is currently held in, and it's being released...
                                    print("Virtual button alternate is held IN, so we need to keep processing")
                                    pass
                                else:
                                    process_remaining = False
                                    loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",physical_btn))
                                    subpage = virtual_btn["vk"]
                                    osb_label()
                        else:
                            process_remaining = False # Do no more process handling
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",physical_btn))
                            subpage = virtual_btn["vk"]
                            osb_label()
            else:
                # So this was called FROM a delay
                print("Called from a force trigger")
                if virtual_btn["page"] == True:
                    # The default action is a mode switch
                    if e.value == 1:
                        # Do nothing when the button is PUSHED except light the OSB
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",physical_btn))
                        if virtual_btn["delay"] != False:
                            print("EXECUTING DELAY")
                            #process_remaining = False
                        pass
                    else:
                        # So button is now released... change the new subpage
                        process_remaining = False # Do no more process handling
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",physical_btn))
                        subpage = virtual_btn["vk"]
                        osb_label()
                else:
                    if virtual_btn["long_page"] == True:
                        # The long hold is a mode switch.
                        process_remaining = False # So do nothing after handling the mode switch.
                        if e.value == 1:
                            # Do nothing when the button is PUSHED except light the OSB
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",physical_btn))
                            pass
                        else:
                            # So button is now released... change the new subpage
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",physical_btn))
                            subpage = virtual_btn["long"]
                            osb_label()
        if process_remaining == False:
            # Halt execution if we tripped something above
            pass
        else:
            if force_trigger == True:
                # So this was called again, with a force delay. That means we need to pull the LONG vk, not the normal vk
                v_k = button_invmap[virtual_btn["long"]] # Get the alternate USB event ID back
                if virtual_btn["page"] == True:
                    v_k_l = button_invmap[virtual_btn["long"]] # Get the alternate USB event back
                else:
                    v_k_l = button_invmap[virtual_btn["vk"]] # Get the alternate USB event back
            else:
                if virtual_btn["page"] == True:
                    # This should only be true if it wasn't caught earlier when we check for page-switch events.
                    # So again the v_k should be the LONG hold value
                    v_k = button_invmap[virtual_btn["long"]] # Get the actual USB event ID back
                    v_k_l = button_invmap[virtual_btn["long"]]
                else:
                    v_k = button_invmap[virtual_btn["vk"]] # Get the actual USB event ID back
                    v_k_l = button_invmap[virtual_btn["vk"]]
            submit_value = e.value # Whether button is in or out
            if virtual_btn["latch"] != False:
                # So this button has a latch value that is other than -1, i.e. it has to be pushed multiple times
                if e.value == 0:
                    is_latched = check_latch(e.code,int(virtual_btn["latch"]),e.value)
                    if is_latched == True:
                        # Button is currently latched
                        if virtual_btn["held"] != False:
                            # "Held" switches should be left in until they are released.
                            print("Special handling for OSB OUT {}".format(e.code))
                            if button_map[v_k]["s"] == 1:
                                # Currently set to 1. Button has been released, but this means that the button was previously set ACTIVE
                                # So in this case, we don't want to release the hold on the button.
                                # This is just a special case, because the virtual button is set "on" when we first push it
                                # so we don't want to inadvertently release it when we let the button go
                                print("Button is HELD")
                                submit_value = 1 # So specify that the button should be thought of as held...
                                loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",physical_btn))
                            else:
                                # Currently set to 0. Which means that we should not do anything else special here.
                                submit_value = 0 # So specify that the button should be thought of as released
                        button_map[v_k]["s"] = submit_value
                else:
                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",physical_btn,1))
                    is_latched = check_latch(e.code,int(virtual_btn["latch"]),e.value)
                    if is_latched == True:
                        if virtual_btn["held"] != False:
                            # This switch should be left in unless released.
                            print("Special handling for OSB IN {}".format(e.code))
                            if button_map[v_k]["s"] == 1:
                                # Currently set to 1; but button has been released, so now unset it.
                                submit_value = 0
                            else:
                                submit_value = 1
                        button_map[v_k]["s"] = submit_value
                for c in virtual_btn["coset"]:
                    if c!=button_map[v_k]["o"]:
                        # So don't trigger this if there is for some reason a coset value that is the same as this key                    
                        if c >= 800:
                            do_hats(c,submit_value)
                        else:
                            button_map[button_invmap[c]]["s"] = 1
                        if c <= 20 or c>=32:
                            # That is, if C is a value low enough to have an attached OSB
                            if e.value == 1:
                                loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",c,1)) # Highlight the OSB
                            else:
                                if is_latched == True:
                                    loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",c,0)) # Latch the OSB
                                else:
                                    loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",c,-1)) # Blank the OSB
                for c in virtual_btn["counset"]:
                    if c!=button_map[v_k]["o"]:
                         # So don't trigger this if there is for some reason a coset value that is the same as this key
                        if c >= 800:
                            do_hats(c,submit_value)
                        else:
                            button_map[button_invmap[c]]["s"] = 0
                        if c <= 20 or c>=32:
                            # That is, if C is a value low enough to have an attached OSB
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",c,-1)) # Highlight the OSB
            else:
                # So this button has no latch value; treat it normally.
                check_latch("",-1,e.value)
                if virtual_btn["sequence"] != -1:
                    # This has a sequence defined. So we need to iterate all other buttons in the sequence.
                    seqvars = osbseq[template][virtual_btn["sequence"]]
                    seqdir = virtual_btn["direction"]
                    # Unset ALL values in the sequence so that we can set ONE new value
                    if seqvars["unset"] != False:
                        # So this sequence is supposed to unset an OSB when triggered.
                        button_map[button_invmap[seqvars["unset"]]]["s"] = 0
                        loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",seqvars["unset"],-1)) # Blank the OSB for the unset value
                    for s in seqvars["seq"]:
                        s = int(s)
                        if s >= 800:
                            do_hats(s,0)
                        else:
                            button_map[s]["s"] = 0
                    if e.value == 1:
                        # Need to move the pointer
                        new_idx = seqvars["idx"] + int(seqdir)
                        if new_idx >= len(seqvars["seq"]):
                            new_idx = 0
                        if new_idx < 0:
                            new_idx = len(seqvars["seq"])-1
                        osbseq[template][virtual_btn["sequence"]]["idx"] = new_idx
                        v_k = osbseq[template][virtual_btn["sequence"]]["seq"][new_idx]
                    #print(e.value,osbseq[template][virtual_btn["sequence"]])
                
                if v_k>=800:
                    # Special handling for the rocker switches
                    do_hats(v_k,e.value)
                else:
                    toggle_special_case = -1 # This is to catch a problem in coset/unset cases
                    if virtual_btn["held"] != False:
                        # So this button is normally supposed to be held in.
                        # Case current:new
                        # held:push         0
                        # held:release      1
                        # unheld:push       1
                        # unheld:release    0
                        if button_map[v_k]["s"] == 1:
                            if e.value == 1:
                                submit_value = 0
                            else:
                                submit_value = 1
                        else:
                            if e.value == 1:
                                submit_value = 1
                            else:
                                submit_value = 0
                        if virtual_btn["toggle"] != False:
                            # So this is a special kind of HELD button where, if it's OFF...
                            # Then we need to set its INVERSE state to "ON"
                            if submit_value == 0:
                                # Button is being released, so inverse should be ON
                                toggle_special_case = button_map[button_invmap[virtual_btn["toggle"]]]["o"]
                                button_map[button_invmap[virtual_btn["toggle"]]]["s"] = 1
                            else:
                                # Button is being held, so inverse should be OFF
                                button_map[button_invmap[virtual_btn["toggle"]]]["s"] = 0
                        print("Special handling for OSB ",e.value,submit_value)
                    for c in virtual_btn["coset"]:
                        print("COSET: ",c,button_invmap[c],v_k,button_map[v_k]["o"],submit_value)
                        if c!=button_map[v_k]["o"] and c!=toggle_special_case:
                            # So don't trigger this if there is for some reason a coset value that is the same as this key
                            if c >= 800:
                                do_hats(c,submit_value)
                            else:
                                button_map[button_invmap[c]]["s"] = 1 # New behavior. Always set this to OFF
                            if c <= 20 or c>=32:
                                # That is, if C is a value low enough to have an attached OSB
                                if e.value == 1:
                                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",c,1)) # Highlight the OSB
                                else:
                                    loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",c,-1)) # Blank the OSB
                    for c in virtual_btn["counset"]:
                        print("TRIGGERED COUNSET: ",c,button_invmap[c],v_k,button_map[v_k]["o"],submit_value)
                        if c!=button_map[v_k]["o"] and c!=toggle_special_case:
                            # So don't trigger this if there is for some reason a coset value that is the same as this key
                            if c >= 800:
                                do_hats(c,submit_value)
                            else:
                                button_map[button_invmap[c]]["s"] = 0 # New behavior. Always set this to OFF
                            if c <= 20 or c>=32:
                                # That is, if C is a value low enough to have an attached OSB
                                loop.call_soon_threadsafe(q.put_nowait,"{},{},{}".format("osb",c,-1)) # Blank the OSB
                    if force_delay != False:
                        #button_map[v_k]["s"] = submit_value # Set the button_map value to be either on or off, depending.
                        if submit_value == 1:
                            loop.call_later(float(virtual_btn["delay"])/1000,event_delayed,e,submap,physical_btn)
                        else:
                            # Always blank the OSB on release even if there's a delay
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",physical_btn,-1)) # Blank the OSB
                            # Always set the button_map value off even if there's a delay
                            button_map[v_k]["s"] = submit_value
                            button_map[v_k_l]["s"] = submit_value
                    else:
                        button_map[v_k]["s"] = submit_value # Set the button_map value to be either on or off, depending.
                        if submit_value == 1:
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",physical_btn,1)) # Highlight the OSB
                        else:
                            button_map[v_k_l]["s"] = submit_value # Unset the alternate LONG HOLD value
                            loop.call_soon_threadsafe(q.put_nowait,"{},{},-1".format("osb",physical_btn,-1)) # Blank the OSB
    else:
        check_latch("",-1,e.value)

def event_delayed(e,submap,physical_btn):
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

    print("Delayed events")
    print(e)

    if button_status[e.code]["s"] == 1:
        # We only trigger this if the button is still held in at the time
        event_normal(e,submap,physical_btn,True)
        #button_map[v_k]["s"] = 1
        #loop.call_soon_threadsafe(q.put_nowait,"{},{},1".format("osb",physical_btn,1)) # Highlight the OSB
    sum_buttons()

def do_hats(key,set_unset):
    global hat
    # key will be 800, 801, 802, 803 or 850,851,852,853
    # Hat B is 850/851/852/853
    # Hat A is 800/801/802/803
    am = {0:"0",1:"1",2:"2",3:"3",4:"4",5:"5",6:"6",7:"7"} # Special keys for hat switch handling
    if key >= 850:
        if set_unset == 0:
            hat[1] = "8"
        else:
            hat[1] = am[key-850]
    else:
        if set_unset == 0:
            hat[0] = "8"
        else:
            hat[0] = am[key-800]

async def export(websocket,path):
    asyncio.create_task(ws_listener(websocket,path))
    while True:
        message = await q.get()
        await websocket.send(message)

async def ws_listener(websocket,path):
    while True:
        async for message in websocket:
            print(message)
            if message == "open_ok":
                # This is from the MFD client, saying that it is now live.
                # Which is good?
                loop.call_soon_threadsafe(q.put_nowait,"ctxt_a,0,0,{}".format("Standing by to load profile.")) # Blank the OSB
                loop.call_soon_threadsafe(q.put_nowait,"{},{}".format("side",mfd_side))
            elif message[:3] == "dbg":
                dbg_vars = message.split(" ")
                v_evt = events.InputEvent(1625821883,277264,1,button_invmap[int(dbg_vars[1])],int(dbg_vars[2]))
                manage_event(v_evt)
            else:
                msg_decompose = message.split(",")
                if len(msg_decompose) == 2:
                    virtual_event = events.InputEvent(1625821883,277264,1,button_invmap[int(msg_decompose[0])],int(msg_decompose[1]))
                    manage_event(virtual_event)

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

    button_specials = {319:"COMMIT",707:"UP",706:"DN",318:"POSX-",317:"POSX+",316:"POS RST",315:"POSY-",314:"POSY+",705:"SWAP",704:"EXIT",309:"SZ X-",310:"SZ X+",311:"SZ RST",312:"SZ Y-",313:"SZ Y+"}

    if reload_mode == False:
        reload_mode = True
        reload_maps()
        loop.call_soon_threadsafe(q.put_nowait,"rst") # Reset all buttons for the display (rather than looping a bunch of stuff to the websockets)
        for b in button_map:
            if b in button_specials:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,button_specials[b]))
#            else:
#                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[b]["o"],-1,""))
    else:
        if mfd_side == "left":
            loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[705]["o"],-1,"RIGHT"))
        else:
            loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",button_map[705]["o"],-1,"LEFT"))
    post_str = ""
    osbmap_supers = []
    for r in osbmap:
        osbmap_supers.append(r)
    for i in range(0,len(osbmap_supers)):
        print(load_idx,osbmap_supers[i])
        if i == load_idx:
            post_str = "{}*{}*<br />".format(post_str,osbmap_supers[i])
        else:
            post_str = "{}{}<br />".format(post_str,osbmap_supers[i])
    loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("ctxt",-1,-1,post_str))


def osb_label(read_state=False):

    # read_state, if TRUE, should set button values from default in config.txt
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
    submap = osbmap[template][subpage]

    # Reset all screen text.

    loop.call_soon_threadsafe(q.put_nowait,"{}".format("rst"))

    for b in button_map:
        #if b!=713:
        #    button_map[b]["s"] = 0
        d_v = -1
        physical_btn = button_map[b]["o"]
        if physical_btn in submap:
            virtual_btn = submap[button_map[b]["o"]]
            if virtual_btn["page"] == False:
                if button_map[button_invmap[virtual_btn["vk"]]]["s"] == 1:
                    # So the button is currently ON, and should be displayed as ON
                    d_v = 1
            o_m = osbmap[template][subpage][physical_btn]
            #print("O_Translate: {}".format(physical_btn))
            #print(o_m)
            if virtual_btn["held"] != False and read_state==True:
                # Special case for when reloading from scratch.
                if virtual_btn["start_on"]==True:
                    # So this is a button that should start ON...
                    d_v = 1 # Button should start held, so specify OSB display as HELD
                    button_map[button_invmap[virtual_btn["vk"]]]["s"] = 1 # Set the virtual button to ON
                else:
                    # Two possibilities here. First, check to see if this is a toggle.
                    if virtual_btn["toggle"] != False:
                        # So this is a toggle. If so, then we need to set the OTHER state to ON
                        d_v = -1 # Just to make sure, we set the OSB display to blank
                        button_map[button_invmap[virtual_btn["vk"]]]["s"] = 0
                        button_map[button_invmap[virtual_btn["toggle"]]]["s"] = 1
                    else:
                        # It's not a toggle, which just means this is a HELD switch that starts OFF
                        # (For example, the toggle for jettisoning fuel or something)
                        # We don't need to do anything else
                        pass
            if physical_btn < 33:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{},{}".format("txt",physical_btn,d_v,virtual_btn["text"],virtual_btn["active_text"]))
            else:
                # Experiment with a set of additional 32 buttons displayed on the touchscreen
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{},{},{},{},{},{},{}".format("vcfg",physical_btn,d_v,virtual_btn["vk"],virtual_btn["x"],virtual_btn["y"],virtual_btn["w"],virtual_btn["h"],virtual_btn["text"],virtual_btn["active_text"]))
    '''

        I believe this can be removed because do this all with reset. Hopefully.

        else:
            if physical_btn >= 1 and physical_btn <= 20:
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("txt",physical_btn,-1," "))
            elif physical_btn >= 33 and physical_btn <= 64:
                # Experiment with a set of additional 32 buttons displayed on the touchscreen
                loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{},{},{},{},{},{}".format("vcfg",physical_btn,-1,-1,-1,-1,-1,-1," "))
    '''
    loop.call_soon_threadsafe(q.put_nowait,"{},{},{},{}".format("ctxt",-1,-1,osbtxt[template][subpage]))
       
def sum_buttons():
    global button_map
    global hat
    if button_count == "b32":
        zero_s = "00 00 {}{} 00 00 00 00".format(hat[0],hat[1])
    elif button_count == "b64":
        zero_s = "00 00 {}{} 00 00 00 00 00 00 00 00".format(hat[0],hat[1])
    elif button_count == "b96":
        zero_s = "00 00 {}{} 00 00 00 00 00 00 00 00 00 00 00 00".format(hat[0],hat[1])
    zero = bytearray.fromhex(zero_s)
    zero_i = int.from_bytes(zero,"big")
    for b in button_map:
        zero_i = zero_i + (button_map[b]["i"]*button_map[b]["s"])
    if button_count == "b32":
        zero_b = zero_i.to_bytes(7,byteorder="big")
    elif button_count == "b64":
        zero_b = zero_i.to_bytes(11,byteorder="big") # Correction for 64-button controller, hopefully.
    elif button_count == "b96":
        zero_b = zero_i.to_bytes(15,byteorder="big") # Correction for 64-button controller, hopefully.
    write_report(zero_b)

def reload_maps():
    global osbmap
    global osbtxt
    global osbseq
    global mfd_side

    file_loc = ["pi","mfd_l","mfd_r"] # Possible usernames

    for f in file_loc:
        if pathlib.Path("/home/{}/pi_mfd/config.txt".format(f)).is_file() == True:
            if f == "pi" or f == "mfd_r":
                mfd_side = "right" # This is a cheat so that the MFD will start on the proper side...
            fpath = "/home/{}/pi_mfd/config.txt".format(f)
    with open(fpath) as f:
        data = f.readlines()

    mainpage = ""
    subpage = ""

    osbmap = {}
    osbtxt = {}
    osbseq = {}

    for d in data:
        # Lines can begin either with -, --, or an integer
        d = d.strip()
        process_line = False
        if len(d) > 0:
            # Don't process empty lines.
            if d[0:1] != "#":
                # Don't process lines beginning with comment marker.
                process_line = True
        if process_line == True:
            if d[:1] == "-":
                if d[:3] == "---":
                    # Then a sequence is being defined
                    # Sequence looks like ---seq0 1,2,3,4
                    # So we define a new osbseq variable with "seq" = that array and "idx" = 0
                    line = d.split(" ")
                    sequence_id = line[0][3:]
                    sequence_vks = []
                    for s in line[1].split(","):
                        sequence_vks.append(int(s))
                    if len(line)>2:
                        us_v = line[2].split("=")
                        unset = int(us_v[1])
                    else:
                        unset = False
                    osbseq[mainpage][sequence_id] = {"seq":sequence_vks,"idx":0,"unset":unset}
                else:
                    if d[:2] == "--":
                        # Then a subpage is being defined.
                        line = d.split(" ")
                        subpage = line[0][2:]
                        subpage_desc = d[(len(subpage)+3):]
                        osbtxt[mainpage][subpage] = subpage_desc
                        osbmap[mainpage][subpage] = {}
                    else:
                        # Then this is a new superpage
                        mainpage_subs = d[1:].split(" ")
                        mainpage = mainpage_subs[0]
                        is_extra = False
                        if len(mainpage_subs) == 2:
                            # This means that the page might be defined as an "extra" map.
                            if mainpage_subs[1] == "extra":
                                is_extra = True
                        
                        osbmap[mainpage] = {"extra":is_extra}
                        osbtxt[mainpage] = {}
                        osbseq[mainpage] = {}
            else:
                if d[0:1].isdigit() == True:
                    # This means that we are defining a new OSB / VK relationship
                    is_latch = False # Should button be latched before triggering?
                    is_held = False # Should button be held?
                    seq = -1 # Sequence ID, if any
                    seq_dir = 0 # Sequence direction, if any
                    vk_val = ""
                    is_page = False # Does this include a switch to a new page?
                    d_vals = d.split(",")
                    coset = [] # Values to be set alongside this trigger
                    counset = [] # Values to be UNSET alongside this trigger
                    toggle = False # If an integer, button will toggle between two held ON states
                    start_on = False # If a held button should start as ON
                    delay = False
                    active_text = False # OSB should be changed when button is active
                    vbtn_x = -1 # If a virtual button, what is its relative x position?
                    vbtn_y = -1 # If a virtual button, what is its relative y position?
                    vbtn_w = -1 # If a virtual button, how many units wide is it?
                    vbtn_h = -1 # If a virtual button, how many units tall is it?

                    if d_vals[2].isdigit() == True:
                        vk_val = int(d_vals[2])
                    else:
                        vk_val = d_vals[2]
                        is_page = True

                    long_is_page = False
                    long_hold = vk_val
                    for i in range(3,len(d_vals)):
                        '''
                        Could be:
                        latch=int
                        held=1
                        sequence=str(id)|int(direction)
                        '''
                        d_v = d_vals[i].split("=")
                        if d_v[0] == "latch":
                            is_latch = int(d_v[1])
                        elif d_v[0] == "hold":
                            is_held = True
                            if int(d_v[1]) == 1:
                                start_on = True
                        elif d_v[0] == "sequence":
                            sequence_vars = d_v[1].split("|")
                            seq = sequence_vars[0]
                            seq_dir = int(sequence_vars[1])
                        elif d_v[0] == "set":
                            if(int(d_v[1])) < 0:
                                counset.append(-1*(int(d_v[1])))
                            else:
                                coset.append(int(d_v[1]))
                        elif d_v[0] == "toggle":
                            toggle = int(d_v[1])
                        elif d_v[0] == "delay":
                            delay = int(d_v[1])
                        elif d_v[0] == "vx":
                            vbtn_x = float(d_v[1])
                        elif d_v[0] == "vy":
                            vbtn_y = float(d_v[1])
                        elif d_v[0] == "vh":
                            vbtn_h = float(d_v[1])
                        elif d_v[0] == "vw":
                            vbtn_w = float(d_v[1])
                        elif d_v[0] == "long":
                            if d_v[1].isdigit() == True:
                                long_hold = int(d_v[1])
                            else:
                                long_hold = d_v[1]
                                long_is_page = True
                        elif d_v[0] == "active":
                            active_text = d_v[1]
                    if int(d_vals[0]) <= 32 or button_count != "b32":
                        # (Don't add extended buttons if the device doesn't support them)
                        osbmap[mainpage][subpage][int(d_vals[0])] = {
                            "text":d_vals[1],
                            "active_text":active_text,
                            "page":is_page,
                            "vk":vk_val,
                            "latch":is_latch,
                            "held":is_held,
                            "start_on":start_on,
                            "sequence":seq,
                            "direction":seq_dir,
                            "coset":coset,
                            "counset":counset,
                            "toggle":toggle,
                            "delay":delay,
                            "long":long_hold,
                            "long_page":long_is_page,
                            "x":vbtn_x,
                            "y":vbtn_y,
                            "w":vbtn_w,
                            "h":vbtn_h
                        }
                    # [d_vals[1],vk_val,is_latch,is_held]
    #print(osbmap["BLANK64"])

    # Next task: if the page has a "share" subpage defined, all of the other pages need those buttons too.
    for m in osbmap:
        print(m)
        print(osbmap[m])
        if "share" in osbmap[m]:
            # So now let's add the share buttons to every other subpage.
            for sub in osbmap[m]:
                if sub!= "share":
                    for share_btn in osbmap[m]["share"]:
                        osbmap[m][sub][share_btn] = osbmap[m]["share"][share_btn]

def reload_all():
    global loop
    file_loc = ["pi","mfd_l","mfd_r"] # Possible usernames
    for f in file_loc:
        if pathlib.Path("/home/{}/pi_mfd/mfd.html".format(f)).is_file() == True:
            fpath = "/home/{}/pi_mfd/mfd.html".format(f)
            f_user = f
    subprocess.Popen(["sudo","-u","{}".format(f_user),"/home/{}/Desktop/startup.sh".format(f_user),"--kiosk",fpath])
    #os.system("lxterminal -e 'bash -c \"bash /home/{}/Desktop/startup.sh;bash\"'".format(f_user))
    #os.system("lxterminal -e 'bash -c \"bash /home/{}/Desktop/startup.sh;bash\"'".format(f_user))

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

def reload_server_nonhost():
    global button_map
    global latch_count
    global button_latch

    file_loc = ["pi","mfd_l","mfd_r"] # Possible usernames

    for f in file_loc:
        if pathlib.Path("//home/{}/mfd.html".format(f)).is_file() == True:
            fpath = "file:///home/{}/mfd.html?main=true".format(f) # Adding the "main" switch so that it loads both servers.
            f_user = f

    for b in button_map:
        if b!=711:
            button_map[b]["s"] = 0 # Set all buttons but the reset switch to 0 value
    subprocess.run(["killall","chromium-browse"])
    subprocess.Popen(["sudo","-u","{}".format(f_user),"/usr/bin/chromium-browser","--kiosk",fpath,"--touch-events=enabled"])
    print("Reloading webserver...")
    latch_count = 0
    button_latch = ""

'''
INITIALIZATION CODE HERE
'''

button_map = {}

if button_count == "b32":
    for i in range(0,33):
        b_val = bytes.fromhex("00 00 00 {}".format(bitmap[i]))
        button_map[osb_physicals[i]] = {"b":b_val,"i":0,"s":0,"o":i}
    for i in range(101,117):
        b_val = bytes.fromhex("00 00 00 00 00 00 00")
        button_map[osb_physicals[i]] = {"b":b_val,"i":0,"s":0,"o":osb_physicals[i]}
elif button_count == "b64":
    for i in range(0,33):
        b_val = bytes.fromhex("00 00 00 {} 00 00 00 00".format(bitmap[i]))
        button_map[osb_physicals[i]] = {"b":b_val,"i":0,"s":0,"o":i}
    for i in range(1,33):
        b_val = bytes.fromhex("00 00 00 00 00 00 00 {}".format(bitmap[i]))
        button_map[403+i] = {"b":b_val,"i":0,"s":0,"o":32+i}
    for i in range(101,117):
        b_val = bytes.fromhex("00 00 00 00 00 00 00 00 00 00 00")
        button_map[osb_physicals[i]] = {"b":b_val,"i":0,"s":0,"o":osb_physicals[i]}
elif button_count == "b96":
    for i in range(0,33):
        b_val = bytes.fromhex("00 00 00 {} 00 00 00 00 00 00 00 00".format(bitmap[i]))
        button_map[osb_physicals[i]] = {"b":b_val,"i":0,"s":0,"o":i}
    for i in range(1,33):
        b_val = bytes.fromhex("00 00 00 00 00 00 00 {} 00 00 00 00".format(bitmap[i]))
        button_map[403+i] = {"b":b_val,"i":0,"s":0,"o":32+i}
    for i in range(1,33):
        b_val = bytes.fromhex("00 00 00 00 00 00 00 00 00 00 00 {}".format(bitmap[i]))
        button_map[503+i] = {"b":b_val,"i":0,"s":0,"o":64+i}
    for i in range(101,117):
        b_val = bytes.fromhex("00 00 00 00 00 00 00 00 00 00 00 00 00 00 00")
        button_map[osb_physicals[i]] = {"b":b_val,"i":0,"s":0,"o":osb_physicals[i]}

# 1-20: OSB 1-20
# 21/22 GAIN UP/DOWN 
# 23/24 SYM UP/DOWN
# 25/26 BRT UP/DOWN
# 27/28 CON UP/DOWN
# 29-32 Virtual buttons

#button_invmap = {0:0,1:304,2:305,3:306,4:307,5:308,6:309,7:310,8:311,9:312,10:313,11:314,12:315,13:316,14:317,15:318,16:319,17:704,18:705,19:706,20:707,21:714,22:715,23:708,24:709,25:710,26:711,27:712,28:713,29:716,30:717,31:718,32:719,800:800,801:801,802:802,803:803,804:804,805:805,806:806,807:807,850:850,851:851,852:852,853:853,854:854,855:855,856:856,857:857}
button_invmap = {}
button_status = {} # Just stores whether the physical button is pressed or released.

for b in button_map:
    button_invmap[int(button_map[b]["o"])] = int(b)
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
debug_mode = False
special_active = False # This is button 26 / event 711

osbmap = {} # Formerly stored in joy32_params.py
osbtxt = {} # Formerly stored in joy32_params.py
osbseq = {} # New, sequence definitions

reload_maps() # Populate the OSB map, text, and sequence

q = asyncio.Queue() # output queue
r = asyncio.Queue() # input queue

loop = asyncio.get_event_loop()

start_server = websockets.serve(export,remote_ip,5678)
#import_server = websockets.serve(process_ws,"127.0.0.1",5678)
dev = InputDevice("/dev/input/event0")

loop.run_until_complete(start_server)
#loop.run_until_complete(import_server)
#loop.run_until_complete(process_ws())
loop.run_until_complete(evhelper(dev))
loop.run_forever()