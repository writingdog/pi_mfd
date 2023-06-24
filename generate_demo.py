#!/usr/bin/python3

import os

cfg_raw = {}

with open("config.txt","r") as f:
    data = f.readlines()

current_main = ""
current_sub = ""
main_pages = {}
print(len(data))
for l in data:
    d = l.strip()
    #print(d[0:2])
    if d[0:3] == "---":
        # ignore the sequence definitions for now
        pass
    elif d[0:2] == "--":
        # This means a new subpage has been defined.
        current_sub = d[2:].split(" ")[0]
        cfg_raw[current_main][current_sub] = []
        #print("sub:",current_sub)
    elif d[0:1] == "-":
        # This means a new MAIN page has been defined.
        current_main = d[1:].split(" ")[0]
        current_sub = ""
        cfg_raw[current_main] = {}
        #print("main:",current_main)
    else:
        if len(d) == 0:
            # So we've hit the end of a definition block.
            current_main = ""
            current_sub = ""
        if current_main != "" and current_sub != "":
            button_data = d.split(",")
            print(button_data)
            b_osb = button_data[0]
            b_txt = button_data[1]
            b_trigger = button_data[2]
            b_vx = "false"
            b_vy = "false"
            b_vw = "false"
            b_vh = "false"
            if len(button_data)>2:
                for i in range(2,len(button_data)):
                    b_extra = button_data[i].split("=")
                    if(len(b_extra)==2):
                        if b_extra[0] == "vx":
                            b_vx = int(b_extra[1])
                        elif b_extra[0] == "vy":
                            b_vy = int(b_extra[1])
                        elif b_extra[0] == "vw":
                            b_vw = int(b_extra[1])
                        elif b_extra[0] == "vh":
                            b_vh = int(b_extra[1])
            cfg_raw[current_main][current_sub].append([b_osb,b_txt,b_trigger,b_vx,b_vy,b_vw,b_vh])

js_out = open("./scripts/demo.js","w")
js_out.write("var demo_buttons = {\n")

for m in cfg_raw:
    for s in cfg_raw[m]:
        if s!= "share":
            js_out.write("\t\"{}-{}\":{{\n".format(m,s))
            if "share" in cfg_raw[m]:
                for b in cfg_raw[m]["share"]:
                    js_out.write("\t\t{}:{{".format(b[0]))
                    js_out.write("\"text\":\"{}\",".format(b[1]))
                    js_out.write("\"trigger\":\"{}\",".format(b[2]))
                    js_out.write("\"vx\":{},".format(b[3]))
                    js_out.write("\"vy\":{},".format(b[4]))
                    js_out.write("\"vw\":{},".format(b[5]))
                    js_out.write("\"vh\":{}}},\n".format(b[6]))
            for b in cfg_raw[m][s]:
                js_out.write("\t\t{}:{{".format(b[0]))
                js_out.write("\"text\":\"{}\",".format(b[1]))
                js_out.write("\"trigger\":\"{}\",".format(b[2]))
                js_out.write("\"vx\":{},".format(b[3]))
                js_out.write("\"vy\":{},".format(b[4]))
                js_out.write("\"vw\":{},".format(b[5]))
                js_out.write("\"vh\":{}}},\n".format(b[6]))
            js_out.write("\t},\n")
js_out.write("};")
js_out.close()

